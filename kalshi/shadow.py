"""Shadow execution: the orders a live executor WOULD send, scored against the
real order book. No API keys, no money, nothing is ever sent.

Paper trading fills every trade at whatever price the judgment step names.
Real limit orders fill only against levels that exist in the book — partly,
later, or never. Shadow mode measures that gap before any real money:

  - paper.py open/close call record(): the exact limit order is built (the
    payload a live executor would POST) and walked against the live book at
    that moment. What crosses fills now at the book's prices; the rest rests.
  - reconcile() (daily step) fills resting remainders from public trade prints
    at or through the limit — OPTIMISTIC, since queue position is unknown —
    and expires them when the market stops trading.
  - summary() compares paper P&L to what the shadow fills would have made,
    and publishes public/shadow.json for the dashboard.

Rows live in $KALSEER_DATA_DIR/shadow/orders.jsonl, one per order.

Usage:
  python3 shadow.py reconcile   # update resting orders, publish shadow.json
  python3 shadow.py report      # print the paper-vs-shadow comparison
"""

import datetime as dt
import json
import os
import sys
import uuid
from decimal import Decimal as D

import kalshi

ENABLED = os.environ.get("KALSEER_SHADOW", "1") != "0"
OPEN_STATUSES = ("partial", "resting")
TRADING = ("active", "open", "initialized")


def _paper():
    import paper  # lazy: paper imports this module
    return paper


def orders_path():
    return _paper().DATA / "shadow" / "orders.jsonl"


def load_orders() -> list[dict]:
    p = orders_path()
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text().splitlines() if line.strip()]


def save_orders(rows: list[dict]):
    p = orders_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".part")
    tmp.write_text("".join(json.dumps(r) + "\n" for r in rows))
    os.replace(tmp, p)


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _num(x: D):
    """Decimal -> int when whole, else float (counts can be fractional)."""
    return int(x) if x == x.to_integral_value() else float(x)


# ── book walk ────────────────────────────────────────────────────────────────

def ladder(book: dict, action: str, side: str) -> list[tuple[D, D]]:
    """Taker levels for this order, best price first.

    Kalshi's book holds bids only (worst -> best). Buying YES lifts NO bids at
    1 - NO bid; buying NO lifts YES bids. Selling hits your own side's bids."""
    if action == "buy":
        against = book.get("no_dollars" if side == "yes" else "yes_dollars") or []
        return sorted((D(1) - D(p), D(q)) for p, q in against)
    own = book.get(f"{side}_dollars") or []
    return sorted(((D(p), D(q)) for p, q in own), reverse=True)


def simulate(book: dict, action: str, side: str, limit, count) -> tuple:
    """(contracts filled now, VWAP or None) for a limit order against book."""
    limit, want = D(str(limit)), D(str(count))
    filled, notional = D(0), D(0)
    for price, qty in ladder(book, action, side):
        if (price > limit) if action == "buy" else (price < limit):
            break
        take = min(qty, want - filled)
        filled += take
        notional += take * price
        if filled >= want:
            break
    if not filled:
        return 0, None
    return _num(filled), float(notional / filled)


def build_order(kind: str, ticker: str, side: str, price, count, cid: str) -> dict:
    """The create-order payload a live executor would send.

    UNVERIFIED against Kalshi's current create-order schema — field names
    (notably the *_price_dollars form) must be checked against the API docs
    before any live executor uses this."""
    return {
        "ticker": ticker,
        "client_order_id": cid,
        "action": "buy" if kind == "open" else "sell",
        "side": side,
        "count": count,
        "type": "limit",
        f"{side}_price_dollars": f"{D(str(price)):.4f}",
        "time_in_force": "good_till_canceled",
    }


def _status(filled_now, remaining) -> str:
    if not remaining:
        return "filled"
    return "partial" if filled_now else "resting"


def record(kind: str, ticker: str, side: str, price, count, paper_ref: str) -> str | None:
    """Record the shadow order for a paper open/close. Never raises: a shadow
    failure must not cost the paper trade it shadows."""
    if not ENABLED:
        return None
    cid = str(uuid.uuid4())
    order = build_order(kind, ticker, side, price, count, cid)
    row = {"id": cid, "created": _now(), "kind": kind, "ticker": ticker, "side": side,
           "paper_ref": paper_ref, "paper_price": float(price), "count": count,
           "order": order}
    try:
        book = kalshi.get_orderbook(ticker, depth=100, tries=2)
        filled, vwap = simulate(book, order["action"], side, price, count)
        remaining = _num(D(str(count)) - D(str(filled)))
        row.update({"book": book, "filled_now": filled, "vwap_now": vwap,
                    "filled_later": 0, "remaining": remaining,
                    "status": _status(filled, remaining)})
    except Exception as e:  # record the miss; it is data about the executor too
        row.update({"filled_now": 0, "vwap_now": None, "filled_later": 0,
                    "remaining": count, "status": "error", "error": str(e)})
    try:
        save_orders(load_orders() + [row])
    except Exception as e:
        print(f"! shadow: could not record {ticker}: {e}", file=sys.stderr)
        return None
    print(f"SHADOW {order['action'].upper()} {side.upper()} {count}x {ticker} "
          f"@ {price}: {row['status']} (filled now {row['filled_now']})")
    return cid


# ── reconcile ────────────────────────────────────────────────────────────────

def _ts(iso: str) -> float:
    return dt.datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()


def fetch_trades(ticker: str, since: str, max_pages: int = 10) -> list[dict]:
    trades, cursor = [], None
    for _ in range(max_pages):
        r = kalshi._get("/markets/trades", tries=2, ticker=ticker,
                        min_ts=int(_ts(since)), limit=1000, cursor=cursor)
        trades += r.get("trades", [])
        cursor = r.get("cursor")
        if not cursor:
            break
    return trades


def reconcile():
    rows = load_orders()
    changed = 0
    for r in rows:
        if r.get("status") not in OPEN_STATUSES:
            continue
        side, buy = r["side"], r["order"]["action"] == "buy"
        limit = D(r["order"][f"{side}_price_dollars"])
        try:
            prints = fetch_trades(r["ticker"], r["created"])
            m = kalshi.get_market(r["ticker"], tries=2)
        except Exception as e:
            print(f"! shadow reconcile {r['ticker']}: {e}")
            continue
        remaining, later = D(str(r["remaining"])), D(str(r["filled_later"]))
        created = _ts(r["created"])
        for t in sorted(prints, key=lambda t: t["created_time"]):
            if remaining <= 0:
                break
            if _ts(t["created_time"]) <= created:
                continue
            px = D(t[f"{side}_price_dollars"])
            if (px <= limit) if buy else (px >= limit):
                take = min(remaining, D(t.get("count_fp") or t.get("count") or 0))
                remaining -= take
                later += take
        r["filled_later"], r["remaining"] = _num(later), _num(remaining)
        if remaining <= 0:
            r["status"] = "filled"
        elif m.get("status") not in TRADING:
            r["status"] = "expired"
        r["reconciled"] = _now()
        changed += 1
    save_orders(rows)
    s = summary()
    print(f"shadow: {changed} resting order(s) reconciled; "
          f"{s['orders']} orders, fill rate {s['fill_rate']:.0%}" if s["orders"]
          else "shadow: no orders yet")


# ── report ───────────────────────────────────────────────────────────────────

def _filled(r) -> float:
    return float(D(str(r.get("filled_now", 0))) + D(str(r.get("filled_later", 0))))


def _avg_price(r) -> float | None:
    """Average fill price: book VWAP for the immediate part, the limit for
    resting fills (a resting order fills at its own price)."""
    now, later = r.get("filled_now", 0), r.get("filled_later", 0)
    if not now and not later:
        return None
    limit = float(r["order"][f"{r['side']}_price_dollars"])
    return ((r.get("vwap_now") or 0) * now + limit * later) / (now + later)


def summary() -> dict:
    rows = load_orders()
    opens = [r for r in rows if r["kind"] == "open"]
    requested = sum(r["count"] for r in opens)
    filled = sum(_filled(r) for r in opens)
    by_status = {}
    for r in rows:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1

    paper_mod = _paper()
    closed = []
    if paper_mod.CLOSED.exists():
        closed = [json.loads(line) for line in paper_mod.CLOSED.read_text().splitlines()
                  if line.strip()]
    by_id = {r["id"]: r for r in opens}
    settled = []
    for c in closed:
        r = by_id.get(c.get("shadow_id"))
        if not r or c.get("result") == "closed":
            continue  # early exits: P&L depends on the close order's fill too
        n, avg = _filled(r), _avg_price(r)
        pnl = 0.0
        if n:
            pnl = n * ((1.0 if c["won"] else 0.0) - avg) - kalshi.taker_fee(avg, n)
        settled.append({"ticker": c["ticker"], "won": c["won"],
                        "paper_contracts": c["contracts"], "paper_pnl": c["pnl"],
                        "shadow_contracts": _num(D(str(n))), "shadow_pnl": round(pnl, 2)})
    s = {
        "generated": _now(),
        "orders": len(rows),
        "opens": len(opens),
        "requested": requested,
        "filled": _num(D(str(filled))),
        "fill_rate": filled / requested if requested else 0.0,
        "by_status": by_status,
        "settled": settled,
        "paper_pnl": round(sum(t["paper_pnl"] for t in settled), 2),
        "shadow_pnl": round(sum(t["shadow_pnl"] for t in settled), 2),
    }
    out = paper_mod.DATA / "public" / "shadow.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    slim = [{k: v for k, v in r.items() if k != "book"} for r in reversed(rows)]
    out.write_text(json.dumps({"summary": s, "orders": slim}, indent=1) + "\n")
    return s


def cmd_report():
    s = summary()
    if not s["orders"]:
        print("no shadow orders yet")
        return
    print(f"{s['orders']} shadow orders ({s['opens']} opens) | requested "
          f"{s['requested']} contracts, filled {s['filled']} ({s['fill_rate']:.0%}) | "
          f"{s['by_status']}")
    for t in s["settled"]:
        print(f"  {t['ticker']}: paper {t['paper_contracts']}x ${t['paper_pnl']:+.2f}"
              f" | shadow {t['shadow_contracts']}x ${t['shadow_pnl']:+.2f}")
    print(f"settled totals: paper ${s['paper_pnl']:+.2f} vs shadow ${s['shadow_pnl']:+.2f}")


COMMANDS = {"reconcile": reconcile, "report": cmd_report}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        sys.exit(__doc__)
    COMMANDS[sys.argv[1]]()
