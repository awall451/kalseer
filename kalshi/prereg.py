"""Append-only binding pre-regs, scored against Kalshi's results. Stdlib only.

Every calibration ledger (RT, Hormuz, LAX heat, macro) is a "PRE-REG
(frozen ..., binding)" line in watchlist prose with hand-copied board mids,
then a hand Brier sum days later. This journals the probabilities with the
board they were made against, timestamped, and does the sums.

  python3 kalshi/prereg.py add EVENT LEG STRIKE=P [STRIKE=P ...]
  python3 kalshi/prereg.py score [--days N] [--since DATE] [PREFIX]

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
`--since DATE` keeps only rows frozen on or after DATE, so a record counted
from a given week (the Hormuz revival rule, "MINE beats board on >= 3 of the
next 4 scored weeks, counted from week 10", until now a hand counter) is the
summary's wins line.

  python3 kalshi/prereg.py point EVENT LEG VALUE
  python3 kalshi/prereg.py test EVENT LEG ABOVE=SIDE BELOW=SIDE

`point` freezes a point forecast of the event's settlement value (the daily
fuel "MINE 4.2530", until now only in watchlist prose), with the board, under
the same one-row-per-EVENT+LEG rule; it refuses an event whose markets have
all closed. `score` prints its error (actual - forecast). For KXAAAGASD /
KXDIESELD it adds fuelscore's RW / MOM / DRIFT forecasts of the same print
(off the journal, window 5) and the closest; the summary gives each one's MAE
and "best" count over those rows (ties count for each). Any other event's
point is journaled with its `# board centre` (a 'greater' ladder crossing on
the ladder), and `score` races the leg against that BOARD: the closer per row
and a "vs BOARD" head-to-head in the summary (the RT ledger's "score finals
vs RW and the board", until now prose).

`test` freezes a pass's two-sided falsifier, which until now was rewritable
prose resolved by hand (11/18: "TEST: >= 5.935 -> MINE/MOM right; <= 5.930 ->
board/WKDAY right"): `test KXDIESELD-26NOV19 TEST 5.935=MINE/MOM
5.930=BOARD/WKDAY`. The first threshold must sit above the second; each
counts for its own side. Same binding rules as `point`. `score` prints the
settled value and the side it landed on, or 'neither (between)', and a
'# tests:' line tallies resolved/between/pending and wins per side.

  python3 kalshi/prereg.py odds EVENT [LEG=VALUE ...]

`odds` (read-only, KXAAAGASD / KXDIESELD) prices the event's live board off
each forecast of its print: the event's frozen points, LEG=VALUE extras not
yet frozen (starred), and fuelscore's RW / MOM / DRIFT / WKDAY. Each is a
normal with sd = sqrt(pi/2) x that forecaster's MAE over the series' pre-regs
printed in the 30 days before (no odds under 5), and every strike shows
P(print > strike) and the edge, P - ask for YES or bid - P for NO. Until now
the passes did it by hand with whatever sd came to mind (11/18 "sd ~0.64c from
MAE 0.51", 11/19 "On MOM (sd ~0.75c)", i.e. MAE itself).

  python3 kalshi/prereg.py edges [--days N] [--sd-mult K] [PREFIX]

`edges` (offline) replays `odds` on the board frozen with each daily fuel
event's first point row, with the sds it would have had that morning. Every
edge >= 0.10 counts as one contract at the frozen ask (YES) or bid (NO), and
each is scored on the journal print. A '# edges SERIES LEG:' line per
forecaster gives the trades taken and won, the summed edges claimed against
the P&L they got (before fees), and its Brier over the priced strikes
against the board's mids. The dailies pass large edges every day because the
board has the better centre record (11/20 "MINE P(>5.860) 0.92 vs ask
0.74"); this line says whether passing them was right. `--sd-mult K`
replays with every sd x K (summary lines tagged '(sd xK)'), so whether a
tighter or wider normal fixes the cheap-ticket band is a sweep, not a
change to `odds`.

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
import math
import os
import pathlib
import sys
from datetime import date, datetime, timedelta, timezone
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
ODDS_DAYS = 30  # trailing days of scored pre-regs behind each odds sd
ODDS_MIN = 5    # fewer scored errors than this: no odds
SD_PER_MAE = math.sqrt(math.pi / 2)  # a normal's sd over its mean |error|
EDGE_MIN = 0.10  # an `edges` trade: the prompt's ~10c mid-range rule of thumb
# `edges ... by cost:` splits trades at these prices of the side taken
COST_BANDS = (0.25, 0.75)


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
    # the '# board centre' it was frozen against, when on a 'greater' ladder
    line = kalshi.centre_line(list(markets.values()))
    if line and _num(centre := line.split(": ", 1)[1]) is not None:
        rec["centre"] = centre
    JOURNAL.parent.mkdir(parents=True, exist_ok=True)
    with JOURNAL.open("a") as f:
        f.write(json.dumps(rec) + "\n")
    return rec


def test(event: str, leg: str, above: str, below: str,
         now: datetime | None = None):
    """Freeze a two-sided test of the event's settlement value: SIDE=VALUE
    pairs, a value at or above `above`'s threshold for its side, at or
    below `below`'s for the other."""
    now = now or _now()
    leg = leg.upper()
    sides = []
    for arg in (above, below):
        value, eq, side = arg.partition("=")
        if not eq or not side:
            sys.exit(__doc__)
        if _num(value) is None:
            sys.exit(f"prereg: {value} is not a number")
        sides.append([value, side])
    if _num(sides[0][0]) <= _num(sides[1][0]):
        sys.exit(f"prereg: the above threshold {sides[0][0]} must sit above "
                 f"the below one {sides[1][0]}")
    if any(r["event"] == event and r["leg"] == leg for r in rows()):
        sys.exit(f"prereg: {event} {leg} already frozen and binding; "
                 f"use a new leg name (e.g. {leg}2)")
    markets = {m.get("ticker"): m
               for m in kalshi.get_event(event).get("markets") or []}
    if not markets:
        sys.exit(f"prereg: no markets for {event}")
    if all(_closed(m, now) for m in markets.values()):
        sys.exit(f"prereg: {event} has closed; a test now is not binding")
    board = {t: [m.get("yes_bid_dollars"), m.get("yes_ask_dollars")]
             for t, m in sorted(markets.items())}
    rec = {"event": event, "leg": leg,
           "at": now.isoformat(timespec="seconds"),
           "test": {"above": sides[0], "below": sides[1]}, "board": board}
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


def score(days: int = 30, prefix: str = "", start: str = ""):
    todo = [r for r in rows() if r["event"].startswith(prefix)
            and r["at"][:10] >= start]
    if todo:
        since = (datetime.fromisoformat(max(r["at"] for r in todo))
                 - timedelta(days=days)).isoformat()
        todo = [r for r in todo if r["at"] >= since]
    if not todo:
        print(f"# no pre-regs in {JOURNAL}"
              + (f" for {prefix}" if prefix else "")
              + (f" since {start}" if start else ""))
        return
    boards, lines, totals, points, tests = {}, [], {}, {}, []
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
        if "test" in r:
            lines.append(_score_test(r, result, head, tests))
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
    for (leg, series), t in sorted(points.items()):
        line = (f"# {leg} point {series}: n={len(t['err'])}, "
                f"MAE {_mae(t['err'])}")
        if t["race"]:
            n = len(t["race"])
            names = (leg,) + fuelscore.MODELS
            line += (f"; vs fuelscore on n={n}: " + "  ".join(
                f"{m} MAE {_mae([e[m] for e in t['race']])} "
                f"best {sum(min(e.values()) == e[m] for e in t['race'])}"
                for m in names))
            line += "; " + _vs_mom(leg, t["race"])
        if t["board"]:
            b = t["board"]
            line += (f"; vs BOARD on n={len(b)}: BOARD MAE "
                     f"{_mae([e['BOARD'] for e in b])}; {leg} closer "
                     f"{sum(e[leg] < e['BOARD'] for e in b)}, BOARD closer "
                     f"{sum(e['BOARD'] < e[leg] for e in b)}, tied "
                     f"{sum(e['BOARD'] == e[leg] for e in b)}")
        print(line)
    if tests:
        won = [w for w in tests if w not in (None, "")]
        line = (f"# tests: n={len(tests)}, resolved {len(won)}, between "
                f"{tests.count('')}, pending {tests.count(None)}")
        if won:
            line += "; " + "  ".join(f"{side} {won.count(side)}"
                                     for side in sorted(set(won)))
        print(line)


def _vs_mom(leg: str, race: list[dict]) -> str:
    """The leg against MOM alone, oldest-first race in: totals and the last
    5 newest first (11/5's diesel retirement watch: 'if MOM wins 3 of the
    next 5'); the '-> best' column can't say it when DRIFT or RW wins."""
    def who(e):
        return leg if e[leg] < e["MOM"] else "MOM" if e["MOM"] < e[leg] \
            else "tie"
    calls = [who(e) for e in race]
    last = calls[-5:][::-1]
    return (f"{leg} vs MOM: {leg} closer {calls.count(leg)}, MOM closer "
            f"{calls.count('MOM')}, tied {calls.count('tie')}; last "
            f"{len(last)} newest first: {' '.join(last)}")


def _mae(errs: list) -> str:
    return f"{sum(errs) / len(errs):.4f}" if errs else "-"


def _score_point(r: dict, result: dict, head: str, points: dict) -> str:
    """One point row: the settled value, each forecast's error (actual -
    forecast) and, for the daily fuel series, fuelscore's models beside it."""
    # the run journals the print minutes before judgment; Kalshi settles
    # hours later on that exact print
    found = _settled_value(r, result)
    if found is None:
        return f"{head}  pending"
    actual, source = found
    models = _fuel_models(r["event"])
    if models:
        actual = actual.quantize(Decimal("0.0001"))
    # non-fuel: race the frozen board centre (fuelfreeze scores the fuel one)
    board = ({} if models or r.get("centre") is None
             else {"BOARD": _num(r["centre"])})
    fc = {r["leg"]: _num(r["point"]), **models, **board}
    err = {m: actual - f for m, f in fc.items()}
    t = points.setdefault((r["leg"], r["event"].split("-")[0]),
                          {"err": [], "race": [], "board": []})
    t["err"].append(abs(err[r["leg"]]))
    if models:
        t["race"].append({m: abs(e) for m, e in err.items()})
    if board:
        t["board"].append({m: abs(e) for m, e in err.items()})
    best = min(abs(e) for e in err.values())
    win = " ".join(m for m, e in err.items() if abs(e) == best)
    fmt = ".4f" if models else "f"  # fuel: AAA's 4 places
    return (f"{head}  = {actual}  " + "  ".join(
        f"{m} {fc[m]:{fmt}} err {e:+{fmt}}" for m, e in err.items())
        + (f"  -> {win}" if models or board else "") + source)


def _settled_value(r: dict, result: dict):
    """(value, source note) the event settled on, or the journal value it
    will settle on (noted), or None while neither is known."""
    values = [m.get("expiration_value") for m in result.values()
              if m.get("result") in ("yes", "no")
              and m.get("expiration_value") not in (None, "")]
    actual = _num(values[0]) if values else None
    if actual is not None:
        return actual, ""
    found = _journal_value(r["event"])
    if found is None:
        return None
    return found[0], f"  ({found[1]}, Kalshi unsettled)"


def _score_test(r: dict, result: dict, head: str, tests: list) -> str:
    """One test row: which side the settled value landed on. `tests` gets
    the winning side, '' between the thresholds, None pending."""
    (hi, up), (lo, down) = r["test"]["above"], r["test"]["below"]
    found = _settled_value(r, result)
    if found is None:
        tests.append(None)
        return f"{head}  pending"
    actual, source = found
    win = up if actual >= _num(hi) else down if actual <= _num(lo) else ""
    tests.append(win)
    return (f"{head}  = {actual}  >= {hi} {up} | <= {lo} {down}  -> "
            + (win or "neither (between)") + source)


def _fuel_centres(event: str, prices: dict) -> dict:
    """fuelscore's RW / MOM / DRIFT / WKDAY for a daily fuel event's print
    off `prices`, the ones it can make."""
    day = datetime.strptime(event.split("-")[1], "%y%b%d").date()
    base = (day - timedelta(days=1)).isoformat()
    fc = {**fuelscore.forecasts(prices, base, FUEL_WINDOW),
          "WKDAY": fuelscore.wkday(prices, base)}
    return {m: v for m, v in fc.items() if v is not None}


def odds(event: str, extra: dict[str, str]) -> list[str]:
    """Each forecast's P(print > strike) on a daily fuel event's live board:
    a normal with sd = SD_PER_MAE x the forecaster's MAE over the series'
    pre-regs whose print is journaled in the ODDS_DAYS before this one."""
    series = event.split("-")[0]
    found = (_fuel_prints(event)
             if series in fuelscore.SETTLED.values() else None)
    if not found:
        sys.exit(f"prereg: odds covers the daily fuel prints only "
                 f"({' / '.join(fuelscore.SETTLED.values())}), not {event}")
    day, prices = found
    cells, sds = _forecasters(event, day, prices, extra)
    out = [f"# odds {event}: P(print > strike), a normal around each "
           f"forecast with sd = {SD_PER_MAE:.4f} x its MAE over {series} "
           f"pre-regs in the {ODDS_DAYS} days before {day}; edge = P - ask "
           "(YES) or bid - P (NO), before fees",
           "# " + "  ".join(cells)]
    ladder = [m for m in kalshi.get_event(event).get("markets") or []
              if m.get("strike_type") == "greater"
              and m.get("floor_strike") is not None]
    for m in sorted(ladder, key=lambda m: float(m["floor_strike"])):
        bid, ask = m.get("yes_bid_dollars"), m.get("yes_ask_dollars")
        priced = kalshi.board_mid(bid, ask) is not None
        row = [m["ticker"][len(event) + 1:],
               f"{bid}/{ask}" if priced else "unpriced"]
        for tag, (centre, sd) in sds.items():
            p = fuelfreeze._p_above(float(m["floor_strike"]), centre, sd)
            edge = ""
            if priced and p > float(ask):
                edge = f" YES+{p - float(ask):.2f}"
            elif priced and p < float(bid):
                edge = f" NO+{float(bid) - p:.2f}"
            row.append(f"{tag} {p:.2f}{edge}")
        out.append("  ".join(row))
    return out


def _forecasters(event: str, day, prices: dict, extra: dict):
    """(header cells, {tag: (centre, sd)}) for `odds`: each forecast of a
    daily fuel event's print and its sd off the series' scored pre-regs in
    the ODDS_DAYS before `day` (none under ODDS_MIN of them)."""
    series = event.split("-")[0]
    frozen = {r["leg"]: _num(r["point"]) for r in rows()
              if r["event"] == event and "point" in r}
    centres = {**{leg.upper(): _num(v) for leg, v in extra.items()},
               **frozen, **_fuel_centres(event, prices)}
    since = day - timedelta(days=ODDS_DAYS)
    errs, seen = {}, set()
    for r in rows():
        if "point" not in r or r["event"].split("-")[0] != series:
            continue
        d = (_fuel_prints(r["event"]) or [None])[0]
        actual = prices.get(d.isoformat()) if d else None
        if actual is None or not since <= d < day:
            continue
        errs.setdefault(r["leg"], []).append(abs(actual - _num(r["point"])))
        if r["event"] not in seen:
            seen.add(r["event"])
            for m, v in _fuel_centres(r["event"], prices).items():
                errs.setdefault(m, []).append(abs(actual - v))
    sds, cells = {}, []
    for name, centre in centres.items():
        tag = name + ("" if name in frozen or name in fuelscore.MODELS
                      or name == "WKDAY" else "*")
        e = errs.get(name, [])
        if len(e) < ODDS_MIN:
            cells.append(f"{tag} {centre:.4f} (n{len(e)}: no odds)")
            continue
        mae = float(sum(e)) / len(e)
        sds[tag] = (float(centre), max(mae * SD_PER_MAE,
                                       fuelfreeze.SD_FLOOR))
        cells.append(f"{tag} {centre:.4f} sd {sds[tag][1] * 100:.2f}c "
                     f"(MAE {mae * 100:.2f}c n{len(e)})")
    if any(c.split()[0].endswith("*") for c in cells):
        cells.append("(* not frozen)")
    return cells, sds


def edges(days: int = 30, prefix: str = "", sd_mult: float = 1.0):
    """Replay `odds` on the board each daily fuel event's first point row
    froze: every edge >= EDGE_MIN is one contract at the frozen ask (YES)
    or bid (NO), scored on the journal print; per forecaster, what the edges
    claimed vs what they paid, and its Brier against the board's mids.
    `sd_mult` scales every sd (floored at SD_FLOOR) and tags the summary."""
    firsts = {}
    for r in rows():
        series = r["event"].split("-")[0]
        if ("point" in r and series in fuelscore.SETTLED.values()
                and r["event"].startswith(prefix)):
            firsts.setdefault(r["event"], r)
    found = {e: _fuel_prints(e) for e in firsts}
    found = {e: f for e, f in found.items() if f}
    printed = [d for e, (d, p) in found.items() if d.isoformat() in p]
    if not printed:
        print("# edges: no daily fuel point rows with a journaled print"
              + (f" for {prefix}" if prefix else ""))
        return
    since = max(printed) - timedelta(days=days)
    print(f"# edges: odds replayed on the board frozen with each daily fuel "
          f"event's first point row; every edge >= {EDGE_MIN:.2f} is one "
          "contract at the frozen ask (YES) or bid (NO), before fees, "
          "scored on the print (claimed = summed edges, got = P&L)")
    mult = "" if sd_mult == 1 else f" (sd x{sd_mult:.2f})"
    if mult:
        print(f"# edges: sd x{sd_mult:.2f} (--sd-mult): every odds sd scaled, "
              f"sd = {SD_PER_MAE * sd_mult:.4f} x MAE")
    totals = {}
    for event, (day, prices) in sorted(found.items(),
                                       key=lambda kv: kv[1][0]):
        r = firsts[event]
        head = f"{r['at'][:10]}  {event}"
        if day < since:
            continue
        actual = prices.get(day.isoformat())
        if actual is None:
            print(f"{head}  pending")
            continue
        quotes = []
        for t, (bid, ask) in sorted(r["board"].items()):
            strike = _num(t.split("-", 2)[-1].lstrip("T"))
            mid = kalshi.board_mid(bid, ask)
            if strike is None or mid is None or strike == actual:
                continue  # unpriced, or a print on the strike: Kalshi's call
            quotes.append((float(strike), float(bid), float(ask), mid,
                           actual > strike))
        if not quotes:
            continue
        cells, sds = _forecasters(event, day, prices, {})
        parts = [c for c in cells if c.endswith("no odds)")]
        for tag, (centre, sd) in sds.items():
            if sd_mult != 1:
                sd = max(sd * sd_mult, fuelfreeze.SD_FLOOR)
            t = totals.setdefault((event.split("-")[0], tag),
                                  [set(), 0, 0, 0.0, 0.0, 0.0, 0.0, 0,
                                   [[0, 0, 0.0, 0.0] for _ in range(3)]])
            n = claimed = got = 0.0
            for strike, bid, ask, mid, yes in quotes:
                p = fuelfreeze._p_above(strike, centre, sd)
                t[5] += (p - yes) ** 2
                t[6] += (mid - yes) ** 2
                t[7] += 1
                if p - ask >= EDGE_MIN:
                    n, claimed, got = n + 1, claimed + p - ask, got + yes - ask
                    t[2] += yes
                    side = (ask, p, yes)
                elif bid - p >= EDGE_MIN:
                    n, claimed, got = n + 1, claimed + bid - p, got + bid - yes
                    t[2] += not yes
                    side = (1 - bid, 1 - p, not yes)
                else:
                    continue
                cost, said, won = side
                lo, hi = COST_BANDS
                b = t[8][0 if cost < lo else 1 if cost <= hi else 2]
                b[0], b[1] = b[0] + 1, b[1] + won
                b[2], b[3] = b[2] + said, b[3] + won - cost
            t[0].add(event)
            t[1] += int(n)
            t[3] += claimed
            t[4] += got
            parts.append(f"{tag} {centre:.4f} taken {int(n)} claimed "
                         f"{claimed:+.2f} got {got:+.2f}")
        print(f"{head}  = {actual:.4f}  n{len(quotes)}  " + "  ".join(parts))
    lo, hi = COST_BANDS
    names = (f"<{lo:.2f}", f"{lo:.2f}-{hi:.2f}", f">{hi:.2f}")
    for (series, tag), (evs, n, won, claimed, got, mine, board, m,
                        bands) in sorted(totals.items()):
        print(f"# edges {series} {tag}{mult}: n={len(evs)} events, taken {n} "
              f"(edge >= {EDGE_MIN:.2f}), won {won}, claimed {claimed:+.2f} got "
              f"{got:+.2f} per contract; Brier {mine:.4f} vs BOARD "
              f"{board:.4f} over {m} strikes")
        cells = [f"{name} taken {k} won {w} (said {said / k:.2f}) got "
                 f"{pnl:+.2f}" if k else f"{name} taken 0"
                 for name, (k, w, said, pnl) in zip(names, bands)]
        print(f"# edges {series} {tag}{mult} by cost: " + " | ".join(cells))


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
    if argv[:1] == ["test"] and len(argv) == 5:
        rec = test(argv[1], argv[2], argv[3], argv[4], now=_now())
        (hi, up), (lo, down) = rec["test"]["above"], rec["test"]["below"]
        print(f"prereg: {rec['event']} {rec['leg']}: >= {hi} {up}, <= {lo} "
              f"{down} frozen at {rec['at']}")
        return
    if argv[:1] == ["odds"] and len(argv) >= 2:
        extra = {}
        for arg in argv[2:]:
            leg, eq, value = arg.partition("=")
            if not eq or _num(value) is None:
                sys.exit(__doc__)
            extra[leg] = value
        print("\n".join(odds(argv[1], extra)))
        return
    if argv[:1] == ["edges"]:
        days, mult, rest = 30, 1.0, argv[1:]
        while rest[:1] in (["--days"], ["--sd-mult"]) and len(rest) > 1:
            if rest[0] == "--days":
                days = int(rest[1])
            else:
                mult = float(rest[1])
            rest = rest[2:]
        if len(rest) > 1 or mult <= 0:
            sys.exit(__doc__)
        edges(days, rest[0] if rest else "", mult)
        return
    if argv[:1] == ["score"]:
        days, start, rest = 30, "", argv[1:]
        while rest[:1] in (["--days"], ["--since"]) and len(rest) > 1:
            if rest[0] == "--days":
                days = int(rest[1])
            else:
                try:
                    start = date.fromisoformat(rest[1]).isoformat()
                except ValueError:
                    sys.exit(__doc__)
            rest = rest[2:]
        if len(rest) > 1:
            sys.exit(__doc__)
        score(days, rest[0] if rest else "", start)
        return
    sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
