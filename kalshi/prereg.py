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

  python3 kalshi/prereg.py point EVENT LEG VALUE

`point` freezes a point forecast of the event's settlement value (the daily
fuel "MINE 4.2530", until now only in watchlist prose), with the board, under
the same one-row-per-EVENT+LEG rule; it refuses an event whose markets have
all closed. `score` prints its error (actual - forecast). For KXAAAGASD /
KXDIESELD it adds fuelscore's RW / MOM / DRIFT forecasts of the same print
(off the journal, window 5) and the closest; the summary gives each one's MAE
and "best" count over those rows (ties count for each).

Every AAA fuel series (gas/diesel daily, weekly, monthly) settles on the
exact AAA print of the event's date, so until Kalshi settles one, `score`
uses the journal's print for that day, marked "(AAA journal, Kalshi
unsettled)": a point's error, or a ladder's 'above' strikes (a print exactly
on a strike waits for Kalshi).

KXHORMUZWEEKLY settles on the sum of PortWatch's daily transit calls over
the 7 days ending on the event's date, no earlier than the Tuesday after;
the pipeline journals those first prints that morning. Once all 7 days are
journaled, `score` uses their first-print sum the same way, marked
"(PortWatch journal, Kalshi unsettled)" (it matched Kalshi on every fully
journaled week, 9/20..10/25).
"""

import json
import os
import pathlib
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

import fuelfreeze
import fuelscore
import kalshi
import portwatch

DATA = pathlib.Path(os.environ.get("KALSEER_DATA_DIR",
                                   pathlib.Path(__file__).parents[1] / "data"))
JOURNAL = DATA / "preregs.jsonl"
FUEL_WINDOW = 5  # fuelscore's default DRIFT window
HORMUZ = "KXHORMUZWEEKLY"  # weekly sum of PortWatch daily transit calls


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


def _num(value) -> Decimal | None:
    """An expiration_value or point as a Decimal ('29,000' and '4.2%' too)."""
    try:
        return Decimal(str(value).replace(",", "").rstrip("%"))
    except (InvalidOperation, ValueError):
        return None


def point(event: str, leg: str, value: str, now: datetime | None = None):
    """Freeze a point forecast of the event's settlement value."""
    now = now or _now()
    leg = leg.upper()
    if any(r["event"] == event and r["leg"] == leg for r in rows()):
        sys.exit(f"prereg: {event} {leg} already frozen and binding; "
                 f"use a new leg name (e.g. {leg}2)")
    if _num(value) is None:
        sys.exit(f"prereg: {value} is not a number")
    markets = {m.get("ticker"): m
               for m in kalshi.get_event(event).get("markets") or []}
    if not markets:
        sys.exit(f"prereg: no markets for {event}")
    if all(_closed(m, now) for m in markets.values()):
        sys.exit(f"prereg: {event} has closed; a pre-reg now is not binding")
    board = {t: [m.get("yes_bid_dollars"), m.get("yes_ask_dollars")]
             for t, m in sorted(markets.items())}
    rec = {"event": event, "leg": leg,
           "at": now.isoformat(timespec="seconds"), "point": value,
           "board": board}
    JOURNAL.parent.mkdir(parents=True, exist_ok=True)
    with JOURNAL.open("a") as f:
        f.write(json.dumps(rec) + "\n")
    return rec


def _fuel_prints(event: str):
    """(print day, {date: price} off the journal) for an AAA-settled fuel
    event (fuelfreeze.SERIES); None for any other or an unreadable journal."""
    grade = fuelfreeze.SERIES.get(event.split("-")[0])
    if not grade:
        return None
    try:
        day = datetime.strptime(event.split("-")[1], "%y%b%d").date()
        return day, dict(fuelscore.series(grade))
    except (IndexError, ValueError, OSError):
        return None


def _fuel_models(event: str) -> dict:
    """fuelscore's RW / MOM / DRIFT forecasts for a KXAAAGASD / KXDIESELD
    event's print, off the journal; {} for any other event or a gap."""
    found = (_fuel_prints(event)
             if event.split("-")[0] in fuelscore.SETTLED.values() else None)
    if not found:
        return {}
    day, prices = found
    fc = fuelscore.forecasts(prices, (day - timedelta(days=1)).isoformat(),
                             FUEL_WINDOW)
    return {} if None in fc.values() else fc


def _journal_print(event: str) -> Decimal | None:
    """The journal's AAA print a daily fuel event settles on, or None."""
    found = _fuel_prints(event)
    return found[1].get(found[0].isoformat()) if found else None


def _hormuz_week(event: str) -> Decimal | None:
    """The first-print sum over the 7 days a Hormuz weekly event ends on,
    or None until PortWatch has published every one of them."""
    try:
        end = datetime.strptime(event.split("-")[1], "%y%b%d").date()
        first = {}
        for r in portwatch._read("Hormuz"):
            first.setdefault(r["date"], r["n_total"])  # Kalshi's: the first
    except (IndexError, ValueError, OSError):
        return None
    days = [(end - timedelta(days=i)).isoformat() for i in range(7)]
    if any(first.get(d) is None for d in days):
        return None
    return sum(Decimal(str(first[d])) for d in days)


def _journal_value(event: str):
    """(value, source) an unsettled event will settle on, off our own
    journal, or None: not a journaled family, or not published yet."""
    if event.split("-")[0] == HORMUZ:
        value, source = _hormuz_week(event), "PortWatch journal"
    else:
        value, source = _journal_print(event), "AAA journal"
    return None if value is None else (value, source)


def _journal_outcomes(event: str, tickers, result: dict):
    """(value, {ticker: YES?}, source) for a ladder off the journal value,
    or None: no value yet, a strike that isn't 'above', or a value exactly
    on one (left to Kalshi)."""
    found = _journal_value(event)
    if found is None:
        return None
    actual, source = found
    out = {}
    for t in tickers:
        m = result.get(t) or {}
        floor = m.get("floor_strike")
        if m.get("strike_type") != "greater" or floor is None:
            return None
        floor = Decimal(str(floor))
        if actual == floor:
            return None
        out[t] = actual > floor
    return actual, out, source


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
    """None (scored as 0.5) for an unpriced market: no quote, an empty
    0.0000/0.0000 book, or one wider than kalshi.MAX_SPREAD."""
    if not quote:
        return None
    return kalshi.board_mid(quote[0], quote[1])


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
    boards, lines, totals, points = {}, [], {}, {}
    for r in todo:
        if r["event"] not in boards:
            try:
                boards[r["event"]] = kalshi.get_event(r["event"]).get(
                    "markets") or []
            except Exception:
                boards[r["event"]] = []
        result = {m.get("ticker"): m for m in boards[r["event"]]}
        head = f"{r['at'][:10]}  {r['event']}  {r['leg']}"
        if "point" in r:
            lines.append(_score_point(r, result, head, points))
            continue
        settled = [result.get(t, {}).get("result") in ("yes", "no")
                   for t in r["probs"]]
        source = ""
        if settled and all(settled):
            value = next((m.get("expiration_value") for m in result.values()
                          if m.get("expiration_value") not in (None, "")),
                         "?")
            yes = {t: result[t]["result"] == "yes" for t in r["probs"]}
        else:
            found = _journal_outcomes(r["event"], r["probs"], result)
            if not found:
                lines.append(f"{head}  pending")
                continue
            value, yes, source = found
            source = f"  ({source}, Kalshi unsettled)"
        mine = board = 0.0
        for t, p in r["probs"].items():
            y = yes[t]
            mid = _mid(r["board"].get(t))
            mine += (p - y) ** 2
            board += ((mid if mid is not None else 0.5) - y) ** 2
        win = r["leg"] if mine < board else "BOARD" if board < mine else "tie"
        lines.append(f"{head}  = {value}  n{len(r['probs'])}  "
                     f"{r['leg']} {mine:.4f}  BOARD {board:.4f}  -> {win}"
                     + source)
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
    for leg, t in sorted(points.items()):
        line = f"# {leg} point: n={len(t['err'])}, MAE {_mae(t['err'])}"
        if t["race"]:
            n = len(t["race"])
            names = (leg,) + fuelscore.MODELS
            line += (f"; vs fuelscore on n={n}: " + "  ".join(
                f"{m} MAE {_mae([e[m] for e in t['race']])} "
                f"best {sum(min(e.values()) == e[m] for e in t['race'])}"
                for m in names))
        print(line)


def _mae(errs: list) -> str:
    return f"{sum(errs) / len(errs):.4f}" if errs else "-"


def _score_point(r: dict, result: dict, head: str, points: dict) -> str:
    """One point row: the settled value, each forecast's error (actual -
    forecast) and, for the daily fuel series, fuelscore's models beside it."""
    values = [m.get("expiration_value") for m in result.values()
              if m.get("result") in ("yes", "no")
              and m.get("expiration_value") not in (None, "")]
    actual = _num(values[0]) if values else None
    source = ""
    if actual is None:
        # the run journals the print minutes before judgment; Kalshi
        # settles hours later on that exact print
        found = _journal_value(r["event"])
        if found is None:
            return f"{head}  pending"
        actual, source = found
        source = f"  ({source}, Kalshi unsettled)"
    models = _fuel_models(r["event"])
    if models:
        actual = actual.quantize(Decimal("0.0001"))
    fc = {r["leg"]: _num(r["point"]), **models}
    err = {m: actual - f for m, f in fc.items()}
    t = points.setdefault(r["leg"], {"err": [], "race": []})
    t["err"].append(abs(err[r["leg"]]))
    if models:
        t["race"].append({m: abs(e) for m, e in err.items()})
    best = min(abs(e) for e in err.values())
    win = " ".join(m for m, e in err.items() if abs(e) == best)
    fmt = ".4f" if models else "f"  # fuel: AAA's 4 places
    return (f"{head}  = {actual}  " + "  ".join(
        f"{m} {fc[m]:{fmt}} err {e:+{fmt}}" for m, e in err.items())
        + (f"  -> {win}" if models else "") + source)


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
    if argv[:1] == ["point"] and len(argv) == 4:
        rec = point(argv[1], argv[2], argv[3], now=_now())
        print(f"prereg: {rec['event']} {rec['leg']}: point {rec['point']} "
              f"frozen at {rec['at']}")
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
