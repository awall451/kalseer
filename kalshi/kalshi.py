"""Kalshi public API client + fee math. Stdlib only, no auth (read-only endpoints).

Also a small CLI for the judgment step, so precise board/rules/settlement
reads don't need a hand-written fetch script every run:

  python3 kalshi/kalshi.py market TICKER [TICKER ...]   # full detail + rules
  python3 kalshi/kalshi.py event EVENT_TICKER           # board of all strikes
  python3 kalshi/kalshi.py series SERIES_TICKER [STATUS] # markets in a series
                                                         # (STATUS default: open)
  python3 kalshi/kalshi.py history SERIES_TICKER [N]    # settled values, newest
                                                         # N events (default 30)
  python3 kalshi/kalshi.py book TICKER [TICKER ...] [--depth N]  # taker depth
                                                         # per side, cumulative

Prices and settlement values print as the API's exact strings — settlement
sources are display-precision hazards, never round them through float.
"""

import json
import math
import sys
import time
import urllib.parse
import urllib.request
from decimal import Decimal

BASE = "https://api.elections.kalshi.com/trade-api/v2"


def _get(path: str, tries: int = 4, **params) -> dict:
    qs = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    url = f"{BASE}{path}" + (f"?{qs}" if qs else "")
    req = urllib.request.Request(url, headers={"User-Agent": "paper-research/0.1"})
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except Exception:
            if attempt == tries - 1:
                raise
            time.sleep(2 ** attempt)


def iter_markets(status: str = "open", max_pages: int = 200,
                 min_close_ts: int | None = None, max_close_ts: int | None = None):
    """Yield all markets with the given status, paginating."""
    cursor = None
    for _ in range(max_pages):
        d = _get("/markets", limit=1000, status=status, cursor=cursor,
                 min_close_ts=min_close_ts, max_close_ts=max_close_ts)
        yield from d.get("markets", [])
        cursor = d.get("cursor")
        if not cursor:
            return


def iter_events(status: str = "open", with_nested_markets: bool = False,
                max_pages: int = 200):
    """Yield all events with the given status, paginating (200/page).

    Unlike the /markets walk, this exhausts: parlay combinations are not
    events, so the open universe is ~14k events, not 800k+ markets.
    """
    cursor = None
    for _ in range(max_pages):
        d = _get("/events", limit=200, status=status, cursor=cursor,
                 with_nested_markets=with_nested_markets or None)
        yield from d.get("events", [])
        cursor = d.get("cursor")
        if not cursor:
            return


def get_market(ticker: str, tries: int = 4) -> dict:
    return _get(f"/markets/{ticker}", tries=tries)["market"]


def get_event(event_ticker: str, tries: int = 4) -> dict:
    return _get(f"/events/{event_ticker}", tries=tries,
                with_nested_markets=True)["event"]


def get_series(series_ticker: str) -> dict:
    return _get(f"/series/{series_ticker}")["series"]


def get_orderbook(ticker: str, depth: int = 8, tries: int = 4) -> dict:
    """Resting bids per side as exact strings, worst to best:
    {"yes_dollars": [[price, qty], ...], "no_dollars": [...]}."""
    return _get(f"/markets/{ticker}/orderbook", tries=tries, depth=depth)["orderbook_fp"]


def get_markets(**params) -> list[dict]:
    """One page of /markets filtered by e.g. series_ticker=, status=."""
    return _get("/markets", limit=1000, **params).get("markets", [])


def settled_markets(series_ticker: str, max_pages: int = 5) -> list[dict]:
    """Every settled market in a series, following the cursor (a busy
    multi-city series like KXRAIN fills a 1000-market page in under 6 weeks)."""
    out, cursor = [], None
    for _ in range(max_pages):
        d = _get("/markets", limit=1000, series_ticker=series_ticker,
                 status="settled", cursor=cursor)
        out.extend(d.get("markets", []))
        cursor = d.get("cursor")
        if not cursor:
            break
    return out


def taker_fee(price: float, contracts: int = 1, rate: float = 0.07) -> float:
    """Kalshi taker fee in dollars: ceil-to-cent of rate * C * P * (1-P).

    General rate is 0.07; some index series are lower. We use 0.07 everywhere
    (conservative for paper-trading purposes).
    """
    raw = rate * contracts * price * (1.0 - price)
    # round before ceil so float epsilon (1.7500000000002) doesn't overcharge
    return math.ceil(round(raw * 100, 6)) / 100


def round_trip_cost(price: float) -> float:
    """Fee per contract if we take liquidity on entry and hold to settlement.

    Settlement itself has no fee; exiting early would incur a second taker fee.
    We model entry fee only (hold-to-settle) — matches the paper strategy.
    """
    return taker_fee(price, 1)


# --- CLI ---------------------------------------------------------------------

def _s(m, key) -> str:
    """Field as the API's exact string; '-' when absent."""
    v = m.get(key)
    return "-" if v in (None, "") else str(v)


def fmt_market(m: dict) -> str:
    """Full detail for one market, rules included (read the settlement date
    in the rules FIRST — it is not always the ticker's date)."""
    sub = m.get("yes_sub_title") or m.get("subtitle") or ""
    title = " | ".join(x for x in (m.get("title"), sub) if x)
    lines = [f"{_s(m, 'ticker')}  [{_s(m, 'status')}]"]
    if title:
        lines.append(f"  {title}")
    lines.append(f"  yes bid/ask {_s(m, 'yes_bid_dollars')}/{_s(m, 'yes_ask_dollars')}"
                 f"  vol24h {_s(m, 'volume_24h_fp')}  oi {_s(m, 'open_interest_fp')}")
    lines.append(f"  close_time {_s(m, 'close_time')}")
    if m.get("result"):
        lines.append(f"  result {m['result']}  "
                     f"expiration_value {_s(m, 'expiration_value')}")
    rules = (m.get("rules_primary") or "").strip()
    if rules:
        lines.append(f"  rules: {rules}")
    return "\n".join(lines)


def fmt_board_row(m: dict) -> str:
    """One board line: exact price strings, result once settled."""
    sub = m.get("yes_sub_title") or m.get("subtitle") or ""
    outcome = m.get("result") or _s(m, "status")
    return (f"{_s(m, 'ticker'):<42} {_s(m, 'yes_bid_dollars'):>6}"
            f" {_s(m, 'yes_ask_dollars'):>6} {_s(m, 'volume_24h_fp'):>10}"
            f"  {outcome:<10} {sub}")


def fmt_history(markets: list[dict], limit: int | None = None) -> list[str]:
    """Settled values as a dated series, newest event first.

    The settlement source's own number, read back from Kalshi: e.g.
    KXTRUMPAPPROVE's expiration_value is that day's RCP average, readable
    here even when the source site refuses us. One line per event when all
    its strikes settled on one value; one per market when they differ
    (per-city families). Markets with no expiration_value are skipped."""
    events = {}
    for m in markets:
        if m.get("expiration_value") in (None, ""):
            continue
        events.setdefault(m.get("event_ticker") or _s(m, "ticker"), []).append(m)
    newest = sorted(events.items(), key=lambda kv: max(_s(m, "close_time") for m in kv[1]),
                    reverse=True)[:limit]
    lines = []
    for ev, ms in newest:
        if len({m["expiration_value"] for m in ms}) == 1:
            lines.append(f"{ev:<34} {_s(ms[0], 'close_time')}  {ms[0]['expiration_value']}")
        else:
            lines.extend(f"{_s(m, 'ticker'):<34} {_s(m, 'close_time')}  {m['expiration_value']}"
                         for m in sorted(ms, key=lambda m: _s(m, "ticker")))
    return lines


def fmt_book(ticker: str, book: dict) -> list[str]:
    """Taker ladders, best price first, with cumulative size.

    Kalshi's book holds bids only: a YES buyer lifts resting NO bids at
    1 − NO bid, a NO buyer lifts YES bids at 1 − YES bid. Decimal keeps the
    derived prices exact (1 − 0.9600 is 0.0400, not 0.039999…)."""
    lines = [ticker]
    for side, against in (("YES", "no_dollars"), ("NO", "yes_dollars")):
        head = f"  buy {side} (from {against.split('_')[0].upper()} bids)"
        lines.append(f"{head:<24}{'price':>8}{'qty':>11}{'cum':>11}")
        bids = book.get(against) or []
        if not bids:
            lines.append("    (empty)")
        cum = Decimal(0)
        for price, qty in reversed(bids):
            cum += Decimal(qty)
            lines.append(f"{'':<24}{Decimal(1) - Decimal(price):>8}{qty:>11}{cum:>11}")
    return lines


def main(argv: list[str]):
    if not argv or argv[0] not in ("market", "event", "series", "history", "book"):
        sys.exit(__doc__)
    cmd, args = argv[0], argv[1:]
    if not args:
        sys.exit(__doc__)
    if cmd == "market":
        for t in args:
            print(fmt_market(get_market(t)))
    elif cmd == "event":
        ev = get_event(args[0])
        print(f"{ev.get('event_ticker', args[0])}  {ev.get('title', '')}"
              f"  [{ev.get('category', '')}]")
        for m in ev.get("markets", []):
            print(fmt_board_row(m))
    elif cmd == "series":
        status = args[1] if len(args) > 1 else "open"
        for m in get_markets(series_ticker=args[0], status=status):
            print(fmt_board_row(m))
    elif cmd == "history":
        limit = int(args[1]) if len(args) > 1 else 30
        for line in fmt_history(settled_markets(args[0]), limit=limit):
            print(line)
    elif cmd == "book":
        depth = 8
        if "--depth" in args:
            i = args.index("--depth")
            depth, args = int(args[i + 1]), args[:i] + args[i + 2:]
        for t in args:
            print("\n".join(fmt_book(t, get_orderbook(t, depth=depth))))


if __name__ == "__main__":
    main(sys.argv[1:])
