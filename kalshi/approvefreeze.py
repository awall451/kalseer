"""Mechanical RW / EMP pre-regs on the daily RCP approval board. Stdlib only.

KXTRUMPAPPROVE (Trump's RCP approval average at 1 PM ET, 0.1-point buckets)
is one of the busiest boards in every scan, and the judgment step passes on
it every run because RCP is unreadable (403 server-side; operator item #20).
Kalshi's settled expiration_values are the RCP series itself, one per day,
so a no-change walk and the history's own daily moves can be frozen against
the board every morning, like highfreeze.py for KXHIGH. The weekly board
KXAPRPOTUS (RCP at 11 AM ET each Friday, 0.3-point buckets) settles on the
same average, so it is frozen off the same daily history with k = the days
from the newest settle to its Friday.

  python3 kalshi/approvefreeze.py freeze           # pipeline step
  python3 kalshi/approvefreeze.py score [--days N]  # vs Kalshi's results

`freeze` appends one row per open KXTRUMPAPPROVE / KXAPRPOTUS event to
$DATA/rcp/approve-freeze.jsonl: the newest settled value before the event's
day (the base) and k, the days between them; every bucket's exact bid/ask
strings; and two legs per bucket. RW is a normal around the base, sd = the
sample sd of the last WINDOW (30) daily moves x sqrt(k), floored at 0.05 points,
with bucket edges halfway between tenths ('less' 38.5 is 38.4 or below,
'greater' 38.7 is 38.8 or above). EMP is the share of every k-day move in the
trailing EMP_DAYS (90) that lands the base in the bucket, smoothed
(n_in + 0.5) / (n + 1); under EMP_MIN (5) moves it is None. Without any
history only the board is kept. Events the history already settles are
skipped. A failed KXAPRPOTUS listing is reported and the daily board is still
frozen. Exit 1 only if nothing was journaled.

`score` reads the FIRST row per event (binding) and prints newest first: the
settled value, and for BOARD (bucket mids, kalshi.board_mid), RW and EMP the
probability on the winning bucket and the all-bucket Brier. A leg missing on
any bucket (an empty or wide book for BOARD) is left out for that day. The
summary gives each leg's mean Brier over the days where all three exist.
KXAPRPOTUS rows follow in their own `# KXAPRPOTUS` section with their own
summary; a weekly event's binding row is its first freeze, days out.
"""

import datetime as dt
import json
import math
import os
import pathlib
import sys

import kalshi

DATA = pathlib.Path(os.environ.get("KALSEER_DATA_DIR",
                                   pathlib.Path(__file__).parents[1] / "data"))
JOURNAL = DATA / "rcp" / "approve-freeze.jsonl"

SERIES = "KXTRUMPAPPROVE"  # the daily board, and the history every board uses
WEEKLY = "KXAPRPOTUS"      # Friday 11 AM ET, 0.3-point buckets, same RCP average
BOARDS = (SERIES, WEEKLY)
WINDOW = 30    # daily moves behind RW's sd
SD_FLOOR = 0.5  # tenths: 0.05 points
EMP_DAYS = 90  # trailing days of k-day moves behind EMP
EMP_MIN = 5    # fewer moves than this: no EMP odds
GAP = 0.15     # board vs leg gap printed at freeze
LEGS = ("BOARD", "RW", "EMP")


def _tenths(x) -> int:
    return round(float(str(x).strip().rstrip("%")) * 10)


def event_day(event: str) -> str:
    return dt.datetime.strptime(event.split("-")[1], "%y%b%d").date().isoformat()


def history(markets: list[dict]) -> dict[str, int]:
    """{day: settled value in tenths} from the series' settled markets."""
    out = {}
    for m in markets:
        value, event = m.get("expiration_value"), m.get("event_ticker") or ""
        if value in (None, "") or "-" not in event:
            continue
        try:
            out[event_day(event)] = _tenths(value)  # some read '38.7%'
        except ValueError:
            continue
    return out


def bucket(m: dict) -> dict:
    return {"ticker": m.get("ticker"), "strike_type": m.get("strike_type"),
            "floor": m.get("floor_strike"), "cap": m.get("cap_strike"),
            "yes_bid": m.get("yes_bid_dollars"),
            "yes_ask": m.get("yes_ask_dollars")}


def _edges(b: dict) -> tuple[float, float]:
    """The bucket as an interval on tenths: 'less' cap 38.5 is v < 385,
    'greater' floor 38.7 is v > 387, 'between' is floor..cap inclusive."""
    kind = b["strike_type"]
    if kind == "less":
        return -math.inf, _tenths(b["cap"]) - 0.5
    if kind == "greater":
        return _tenths(b["floor"]) + 0.5, math.inf
    return _tenths(b["floor"]) - 0.5, _tenths(b["cap"]) + 0.5


def hits(b: dict, v: int) -> bool:
    lo, hi = _edges(b)
    return lo < v < hi


def changes(hist: dict, base_day: str, k: int) -> list[int]:
    """Every k-day move whose end day falls in the EMP_DAYS up to base_day."""
    base = dt.date.fromisoformat(base_day)
    start = (base - dt.timedelta(days=EMP_DAYS)).isoformat()
    out = []
    for day in sorted(hist):
        if not start < day <= base_day:
            continue
        prev = (dt.date.fromisoformat(day) - dt.timedelta(days=k)).isoformat()
        if prev in hist:
            out.append(hist[day] - hist[prev])
    return out


def _cdf(x: float, mu: float, sd: float) -> float:
    if x == math.inf:
        return 1.0
    if x == -math.inf:
        return 0.0
    return 0.5 * (1 + math.erf((x - mu) / (sd * math.sqrt(2))))


def rw_p(b: dict, base: int, sd: float) -> float:
    lo, hi = _edges(b)
    return _cdf(hi, base, sd) - _cdf(lo, base, sd)


def emp_p(b: dict, base: int, moves: list[int]) -> float | None:
    if len(moves) < EMP_MIN:
        return None
    n_in = sum(hits(b, base + c) for c in moves)
    return (n_in + 0.5) / (len(moves) + 1)


def rw_sd(hist: dict, base_day: str, k: int) -> float:
    daily = changes(hist, base_day, 1)[-WINDOW:]
    sd = 0.0
    if len(daily) > 1:
        mean = sum(daily) / len(daily)
        sd = math.sqrt(sum((c - mean) ** 2 for c in daily) / (len(daily) - 1))
    return max(sd, SD_FLOOR) * math.sqrt(k)


def _mid(b: dict) -> float | None:
    return kalshi.board_mid(b.get("yes_bid"), b.get("yes_ask"))


def _mode(buckets: list[dict], leg: str) -> str:
    probs = [(b[leg] if leg != "BOARD" else _mid(b), b) for b in buckets]
    probs = [(p, b) for p, b in probs if p is not None]
    if not probs:
        return f"{leg} -"
    p, b = max(probs, key=lambda x: x[0])
    return f"{leg} {b['ticker'].rsplit('-', 1)[-1]} {p:.2f}"


def freeze() -> tuple[int, list[str]]:
    """Append a row per open event. Returns (events with legs, events without)."""
    hist = {}
    try:
        hist = history(kalshi.settled_markets(SERIES))
    except Exception as e:
        print(f"approvefreeze: settled history failed: {e}", file=sys.stderr)
    by_event = {}
    for series in BOARDS:
        try:
            listed = kalshi.get_markets(series_ticker=series, status="open")
        except Exception as e:
            if series == SERIES:
                raise
            print(f"approvefreeze: {series} listing failed: {e}", file=sys.stderr)
            continue
        for m in listed:
            by_event.setdefault(m.get("event_ticker"), []).append(m)
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    ok, failed, out = 0, [], []
    for event in sorted(e for e in by_event if e):
        day = event_day(event)
        if day in hist:
            continue
        rec = {"event": event, "date": day, "fetched_at": now,
               "base_day": None, "base": None, "k": None, "n_emp": 0, "sd": None}
        buckets = [bucket(m) for m in by_event[event]]
        prior = [d for d in hist if d < day]
        if prior:
            base_day = max(prior)
            base = hist[base_day]
            k = (dt.date.fromisoformat(day)
                 - dt.date.fromisoformat(base_day)).days
            moves, sd = changes(hist, base_day, k), rw_sd(hist, base_day, k)
            rec.update(base_day=base_day, base=f"{base / 10:.1f}", k=k,
                       n_emp=len(moves), sd=round(sd / 10, 3))
            for b in buckets:
                b["RW"] = round(rw_p(b, base, sd), 4)
                e = emp_p(b, base, moves)
                b["EMP"] = None if e is None else round(e, 4)
            ok += 1
        else:
            for b in buckets:
                b["RW"] = b["EMP"] = None
            failed.append(event)
        rec["buckets"] = buckets
        out.append(rec)
        print(f"  {event} base {rec['base']} ({rec['base_day']}, k={rec['k']})  "
              + "  ".join(_mode(buckets, leg) for leg in LEGS))
        for b in buckets:
            mid = _mid(b)
            gaps = [f"{leg} {b[leg]:.2f}" for leg in ("RW", "EMP")
                    if mid is not None and b[leg] is not None
                    and abs(b[leg] - mid) >= GAP]
            if gaps:
                print(f"  {b['ticker']} board {mid:.2f}  " + "  ".join(gaps))
    if out:
        JOURNAL.parent.mkdir(parents=True, exist_ok=True)
        with JOURNAL.open("a") as f:
            f.writelines(json.dumps(r) + "\n" for r in out)
    return ok, failed


def frozen_lines() -> list[str]:
    if not JOURNAL.exists():
        return []
    return [l for l in JOURNAL.read_text().splitlines() if l.strip()]


def frozen() -> list[dict]:
    """First row per event, oldest first."""
    first = {}
    for line in frozen_lines():
        r = json.loads(line)
        first.setdefault(r["event"], r)
    return sorted(first.values(), key=lambda r: r["date"])


def _leg(name: str, probs: list[float], won: list[bool]) -> tuple[str, float]:
    brier = sum((p - y) ** 2 for p, y in zip(probs, won))
    return (f"{name} p {sum(p for p, y in zip(probs, won) if y):.4f} "
            f"B {brier:.4f}"), brier


def score(days: int = 30):
    rows = frozen()
    if not rows:
        print(f"# no freezes in {JOURNAL}")
        return
    for series in BOARDS:
        mine = [r for r in rows if r["event"].startswith(series + "-")]
        if not mine:
            continue
        if series != SERIES:
            print(f"# {series} (weekly, Friday 11 AM ET)")
        _score_series(series, mine, days)


def _score_series(series: str, rows: list[dict], days: int):
    since = (dt.date.fromisoformat(rows[-1]["date"])
             - dt.timedelta(days=days)).isoformat()
    settled = kalshi.settled_markets(series)
    result = {m.get("ticker"): m.get("result") for m in settled}
    value = {m.get("event_ticker"): m.get("expiration_value") for m in settled
             if m.get("expiration_value") not in (None, "")}
    briers, lines = {leg: [] for leg in LEGS}, []
    for r in rows:
        if r["date"] < since:
            continue
        buckets = r.get("buckets") or []
        won = [result.get(b["ticker"]) == "yes" for b in buckets]
        if r["event"] not in value or not any(won):
            lines.append(f"{r['date']}  pending  base {r.get('base')}")
            continue
        parts = [r["date"], str(value[r["event"]]).rstrip("%"),
                 f"base {r.get('base')} k={r.get('k')}"]
        legs = {"BOARD": [_mid(b) for b in buckets],
                "RW": [b.get("RW") for b in buckets],
                "EMP": [b.get("EMP") for b in buckets]}
        scored = {}
        for name in LEGS:
            if not buckets or None in legs[name]:
                parts.append(f"{name} -")
                continue
            text, scored[name] = _leg(name, legs[name], won)
            parts.append(text)
        if len(scored) == len(LEGS):
            for name in LEGS:
                briers[name].append(scored[name])
        lines.append("  ".join(parts))
    for line in reversed(lines):
        print(line)
    n = len(briers["BOARD"])
    settled_n = sum(1 for l in lines if "pending" not in l)
    summary = f"# n={settled_n} settled days (last {days}d)"
    if n:
        summary += f"; all legs on {n}: " + "  ".join(
            f"{k} B {sum(v) / n:.4f}" for k, v in briers.items())
    print(summary)


def main(argv: list[str]):
    if argv[:1] == ["freeze"]:
        before = len(frozen_lines())
        ok, failed = freeze()
        print(f"approvefreeze: {ok} event(s) frozen with legs"
              + (f"; board only: {' '.join(failed)}" if failed else ""))
        if len(frozen_lines()) == before:
            sys.exit(1)
        return
    if argv[:1] == ["score"]:
        days = 30
        if argv[1:2] == ["--days"] and len(argv) > 2:
            days = int(argv[2])
        elif argv[1:]:
            sys.exit(__doc__)
        score(days)
        return
    sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
