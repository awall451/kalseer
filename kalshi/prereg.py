"""Append-only binding pre-regs, scored against Kalshi's results. Stdlib only.

Every calibration ledger (RT, Hormuz, LAX heat, macro) is a "PRE-REG
(frozen ..., binding)" line in watchlist prose with hand-copied board mids,
then a hand Brier sum days later. This journals the probabilities with the
board they were made against, timestamped, and does the sums.

  python3 kalshi/prereg.py add EVENT LEG STRIKE=P [STRIKE=P ...]
  python3 kalshi/prereg.py score [--days N] [PREFIX]

`add` reads the event's board and appends one row to $DATA/preregs.jsonl:
P(YES) per market (STRIKE is the ticker's last part: 57 for KXRT-SOC-57,
T6.38 for KXDIESELW-26OCT19-T6.38) and every priced market's exact bid/ask
at that moment. LEG is a name (MINE, RAW, RW, ...; upper-cased). It refuses
an unknown strike, a P outside 0-1, a market that has already closed, and a
second row for the same EVENT + LEG: the first is binding, so a revision
needs a new leg name (MINE2).

`score` reads each row (newest first; rows within --days N, default 30, of
the newest; optionally only events starting with PREFIX) and once every priced
strike has settled prints the leg's Brier sum and the frozen board's (mids)
over the same strikes, and the winner. A per-leg summary closes it.
"""

import json
import os
import pathlib
import sys
from datetime import datetime, timedelta, timezone

import kalshi

DATA = pathlib.Path(os.environ.get("KALSEER_DATA_DIR",
                                   pathlib.Path(__file__).parents[1] / "data"))
JOURNAL = DATA / "preregs.jsonl"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def rows() -> list[dict]:
    if not JOURNAL.exists():
        return []
    return [json.loads(l) for l in JOURNAL.read_text().splitlines()
            if l.strip()]


def _closed(m: dict, now: datetime) -> bool:
    close = m.get("close_time")
    if close and datetime.fromisoformat(close.replace("Z", "+00:00")) <= now:
        return True
    return m.get("status") not in (None, "active", "open")


def add(event: str, leg: str, probs: dict[str, float],
        now: datetime | None = None):
    now = now or _now()
    leg = leg.upper()
    if any(r["event"] == event and r["leg"] == leg for r in rows()):
        sys.exit(f"prereg: {event} {leg} already frozen and binding; "
                 f"use a new leg name (e.g. {leg}2)")
    markets = {m.get("ticker"): m
               for m in kalshi.get_event(event).get("markets") or []}
    out = {}
    for strike, p in probs.items():
        ticker = f"{event}-{strike}"
        if ticker not in markets:
            have = " ".join(t[len(event) + 1:] for t in sorted(markets))
            sys.exit(f"prereg: no market {ticker}; strikes: {have}")
        if not 0 <= p <= 1:
            sys.exit(f"prereg: {strike}={p} is not a probability")
        if _closed(markets[ticker], now):
            sys.exit(f"prereg: {ticker} has closed; a pre-reg now is not "
                     "binding")
        out[ticker] = p
    board = {t: [m.get("yes_bid_dollars"), m.get("yes_ask_dollars")]
             for t, m in sorted(markets.items())}
    rec = {"event": event, "leg": leg,
           "at": now.isoformat(timespec="seconds"), "probs": out,
           "board": board}
    JOURNAL.parent.mkdir(parents=True, exist_ok=True)
    with JOURNAL.open("a") as f:
        f.write(json.dumps(rec) + "\n")
    return rec


def _mid(quote) -> float | None:
    if not quote or not (quote[0] and quote[1]):
        return None
    return (float(quote[0]) + float(quote[1])) / 2


def score(days: int = 30, prefix: str = ""):
    todo = [r for r in rows() if r["event"].startswith(prefix)]
    if todo:
        since = (datetime.fromisoformat(max(r["at"] for r in todo))
                 - timedelta(days=days)).isoformat()
        todo = [r for r in todo if r["at"] >= since]
    if not todo:
        print(f"# no pre-regs in {JOURNAL}"
              + (f" for {prefix}" if prefix else ""))
        return
    boards, lines, totals = {}, [], {}
    for r in todo:
        if r["event"] not in boards:
            try:
                boards[r["event"]] = kalshi.get_event(r["event"]).get(
                    "markets") or []
            except Exception:
                boards[r["event"]] = []
        result = {m.get("ticker"): m for m in boards[r["event"]]}
        head = f"{r['at'][:10]}  {r['event']}  {r['leg']}"
        settled = [result.get(t, {}).get("result") in ("yes", "no")
                   for t in r["probs"]]
        if not settled or not all(settled):
            lines.append(f"{head}  pending")
            continue
        value = next((m.get("expiration_value") for m in result.values()
                      if m.get("expiration_value") not in (None, "")), "?")
        mine = board = 0.0
        for t, p in r["probs"].items():
            y = result[t]["result"] == "yes"
            mid = _mid(r["board"].get(t))
            mine += (p - y) ** 2
            board += ((mid if mid is not None else 0.5) - y) ** 2
        win = r["leg"] if mine < board else "BOARD" if board < mine else "tie"
        lines.append(f"{head}  = {value}  n{len(r['probs'])}  "
                     f"{r['leg']} {mine:.4f}  BOARD {board:.4f}  -> {win}")
        t = totals.setdefault(r["leg"], [0, 0.0, 0.0, 0, 0])
        t[0] += 1
        t[1] += mine
        t[2] += board
        t[3] += mine < board
        t[4] += board < mine
    for line in reversed(lines):
        print(line)
    for leg, (n, mine, board, w, l) in sorted(totals.items()):
        print(f"# {leg}: n={n} events, Brier sum {mine:.4f} vs BOARD "
              f"{board:.4f}, wins {w}-{l}")


def main(argv: list[str]):
    if argv[:1] == ["add"] and len(argv) >= 4:
        probs = {}
        for arg in argv[3:]:
            strike, eq, p = arg.partition("=")
            if not eq:
                sys.exit(__doc__)
            probs[strike] = float(p)
        rec = add(argv[1], argv[2], probs, now=_now())
        mids = "  ".join(
            f"{t[len(rec['event']) + 1:]} {p:g}/{_mid(rec['board'][t]) or 0:.3f}"
            for t, p in rec["probs"].items())
        print(f"prereg: {rec['event']} {rec['leg']}: {len(rec['probs'])} "
              f"strikes frozen at {rec['at']} (p/board mid: {mids})")
        return
    if argv[:1] == ["score"]:
        days, rest = 30, argv[1:]
        if rest[:1] == ["--days"] and len(rest) > 1:
            days, rest = int(rest[1]), rest[2:]
        if len(rest) > 1:
            sys.exit(__doc__)
        score(days, rest[0] if rest else "")
        return
    sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
