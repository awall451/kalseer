"""Paper-trade ledger + calibration report.

Positions live in data/portfolio.json. Settled trades move to data/closed.jsonl.
Every position records Claude's fair-value estimate so we can measure
calibration, not just P&L.

Usage:
  python3 paper.py open TICKER yes|no PRICE CONTRACTS FAIR_VALUE "reasoning..."
  python3 paper.py settle          # poll API, settle finished markets
  python3 paper.py status          # open positions + bankroll
  python3 paper.py report          # P&L + calibration buckets
"""

import datetime as dt
import json
import os
import pathlib
import sys

import kalshi

# All mutable state (ledger, briefs, published JSON) lives outside the repo so
# the engine stays data-free; point KALSEER_DATA_DIR at your data checkout.
DATA = pathlib.Path(os.environ.get("KALSEER_DATA_DIR",
                                   pathlib.Path(__file__).parents[1] / "data"))
PORTFOLIO = DATA / "portfolio.json"
CLOSED = DATA / "closed.jsonl"
STARTING_BANKROLL = float(os.environ.get("KALSEER_STARTING_BANKROLL", "500"))  # pretend dollars

# Hard guardrails for unsupervised (headless) trading. Enforced here, not in
# the prompt, so a bad reasoning day can't blow up the bankroll.
MAX_TRADES_PER_DAY = 3
MAX_TOTAL_EXPOSURE = 0.40  # fraction of equity that may be at risk
MAX_POSITION_FRAC = 0.10   # fraction of equity in any single position
EXIT_GUARDRAIL = 2         # distinct exit code: rejection is data, not error


def load():
    if PORTFOLIO.exists():
        return json.loads(PORTFOLIO.read_text())
    return {"bankroll": STARTING_BANKROLL, "positions": []}


def save(p):
    DATA.mkdir(parents=True, exist_ok=True)
    PORTFOLIO.write_text(json.dumps(p, indent=1))


def position_cost(pos) -> float:
    return pos["entry_price"] * pos["contracts"] + pos["fee_paid"]


def trades_opened_today(p) -> int:
    today = dt.datetime.now(dt.timezone.utc).date().isoformat()
    n = sum(1 for x in p["positions"] if x["opened"][:10] == today)
    if CLOSED.exists():
        for line in CLOSED.read_text().splitlines():
            if line.strip() and json.loads(line)["opened"][:10] == today:
                n += 1
    return n


def guardrail_violation(p, cost: float) -> str | None:
    """Return a rejection reason, or None if the trade is allowed."""
    exposure = sum(position_cost(x) for x in p["positions"])
    equity = p["bankroll"] + exposure
    if trades_opened_today(p) >= MAX_TRADES_PER_DAY:
        return f"daily trade cap reached ({MAX_TRADES_PER_DAY}/day)"
    if cost > MAX_POSITION_FRAC * equity:
        return (f"position ${cost:.2f} exceeds {MAX_POSITION_FRAC:.0%} of "
                f"equity ${equity:.2f} (max ${MAX_POSITION_FRAC * equity:.2f})")
    if exposure + cost > MAX_TOTAL_EXPOSURE * equity:
        return (f"total exposure ${exposure + cost:.2f} would exceed "
                f"{MAX_TOTAL_EXPOSURE:.0%} of equity ${equity:.2f}")
    return None


def cmd_open(ticker, side, price, contracts, fair_value, reasoning):
    price, fair_value, contracts = float(price), float(fair_value), int(contracts)
    assert side in ("yes", "no")
    assert 0 < price < 1 and 0 < fair_value < 1
    p = load()
    fee = kalshi.taker_fee(price, contracts)
    cost = price * contracts + fee
    if cost > p["bankroll"]:
        sys.exit(f"cost ${cost:.2f} exceeds bankroll ${p['bankroll']:.2f}")
    reason = guardrail_violation(p, cost)
    if reason:
        print(f"REJECTED {ticker}: {reason}", file=sys.stderr)
        sys.exit(EXIT_GUARDRAIL)
    p["bankroll"] = round(p["bankroll"] - cost, 2)
    pos = {
        "ticker": ticker,
        "side": side,
        "entry_price": price,
        "contracts": contracts,
        "fee_paid": fee,
        "fair_value": fair_value,  # our estimated P(side wins)
        "edge_at_entry": round(fair_value - price, 3),
        "reasoning": reasoning,
        "opened": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
    }
    p["positions"].append(pos)
    save(p)
    print(f"OPEN {side.upper()} {contracts}x {ticker} @ {price:.2f} "
          f"(fee ${fee:.2f}, fair {fair_value:.2f}, edge {pos['edge_at_entry']:+.2f}) "
          f"bankroll ${p['bankroll']:.2f}")


def cmd_settle():
    p = load()
    still_open, n = [], 0
    for pos in p["positions"]:
        try:
            m = kalshi.get_market(pos["ticker"])
        except Exception as e:
            print(f"! {pos['ticker']}: {e}")
            still_open.append(pos)
            continue
        result = m.get("result") or ""
        # Kalshi reports resolved markets as "finalized" (also seen: "settled")
        if m.get("status") not in ("settled", "finalized") or result not in ("yes", "no"):
            still_open.append(pos)
            continue
        won = result == pos["side"]
        payout = pos["contracts"] * (1.0 if won else 0.0)
        p["bankroll"] = round(p["bankroll"] + payout, 2)
        pos.update({
            "result": result,
            "won": won,
            "payout": payout,
            "pnl": round(payout - pos["entry_price"] * pos["contracts"] - pos["fee_paid"], 2),
            "settled": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        })
        with CLOSED.open("a") as f:
            f.write(json.dumps(pos) + "\n")
        n += 1
        print(f"SETTLED {pos['ticker']} -> {result.upper()} "
              f"({'WIN' if won else 'LOSS'}, pnl ${pos['pnl']:+.2f})")
    p["positions"] = still_open
    save(p)
    print(f"{n} settled, {len(still_open)} still open, bankroll ${p['bankroll']:.2f}")


def cmd_status():
    p = load()
    at_risk = sum(x["entry_price"] * x["contracts"] + x["fee_paid"] for x in p["positions"])
    print(f"bankroll ${p['bankroll']:.2f}  |  at risk ${at_risk:.2f}  |  "
          f"{len(p['positions'])} open positions")
    for x in p["positions"]:
        print(f"  {x['side'].upper():>3} {x['contracts']:>3}x {x['ticker']:<40} "
              f"@ {x['entry_price']:.2f} fair {x['fair_value']:.2f}  ({x['opened'][:10]})")


def cmd_report():
    closed = []
    if CLOSED.exists():
        closed = [json.loads(l) for l in CLOSED.read_text().splitlines() if l.strip()]
    if not closed:
        print("no settled trades yet")
        return
    pnl = sum(x["pnl"] for x in closed)
    wins = sum(1 for x in closed if x["won"])
    staked = sum(x["entry_price"] * x["contracts"] + x["fee_paid"] for x in closed)
    print(f"{len(closed)} settled | {wins} wins ({wins/len(closed):.0%}) | "
          f"pnl ${pnl:+.2f} | roi {pnl/staked:+.1%} on ${staked:.2f} staked\n")
    print("calibration (our fair value vs reality):")
    buckets = {}
    for x in closed:
        b = min(int(x["fair_value"] * 10), 9)
        buckets.setdefault(b, []).append(1 if x["won"] else 0)
    for b in sorted(buckets):
        outcomes = buckets[b]
        lo, hi = b / 10, b / 10 + 0.1
        print(f"  said {lo:.0%}-{hi:.0%}: happened {sum(outcomes)/len(outcomes):.0%} "
              f"(n={len(outcomes)})")


COMMANDS = {"open": cmd_open, "settle": cmd_settle, "status": cmd_status, "report": cmd_report}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        sys.exit(__doc__)
    COMMANDS[sys.argv[1]](*sys.argv[2:])
