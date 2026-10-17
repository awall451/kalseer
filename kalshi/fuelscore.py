"""Mechanical daily model race off the AAA journal. Stdlib only; no network
unless --settled.

The judgment step scores three mechanical forecasts of tomorrow's AAA print
every run and gates drift trades on a bar. They need no judgment, so they
need no frozen pre-reg either: every day the journal holds is scorable,
including days a dead run never pre-registered.

  python3 kalshi/fuelscore.py regular             # gas (KXAAAGASD/W/M)
  python3 kalshi/fuelscore.py diesel --window 10  # diesel (KXDIESELD/W)
  python3 kalshi/fuelscore.py regular --days 30   # more scored rows
  python3 kalshi/fuelscore.py regular --settled   # + KXAAAGASD/KXDIESELD
                                                  # finals the journal lacks

  RW     tomorrow = today
  MOM    tomorrow = today + today's change
  DRIFT  tomorrow = today + mean of the last N daily changes (--window, 5)
  bar    2 x sample sd / sqrt(N) of those changes; drift clears when
         |mean| > bar

Rows print newest first: actual, then each model's forecast and its error
(actual − forecast) in cents. A model is never scored across a missing day
('-' instead). The '# n=' summary is MAE and wins over days all three models
scored (ties win for each tied model); '# next' is tomorrow's forecasts and
the drift bar. Prices come from the journal's exact strings via Decimal.

--settled fills days the journal lacks (it starts 9/24) from Kalshi's
settled daily markets, whose expiration_value is the exact AAA print dated
by the event ticker. The journal wins any day both hold; '# settled' reports
how many days were added and any day the two disagree. Slow: it pages every
settled strike (~1-2 min).
"""

import json
import os
import pathlib
import sys
from datetime import date, datetime, timedelta
from decimal import Decimal

import kalshi

DATA = pathlib.Path(os.environ.get("KALSEER_DATA_DIR",
                                   pathlib.Path(__file__).parents[1] / "data"))
JOURNAL = DATA / "aaa" / "prints.jsonl"

GRADES = ("regular", "mid_grade", "premium", "diesel")
MODELS = ("RW", "MOM", "DRIFT")
CENT = Decimal(100)
SETTLED = {"regular": "KXAAAGASD", "diesel": "KXDIESELD"}


def series(grade: str) -> list[tuple[str, Decimal]]:
    """[(date, price)] oldest first; the last row for a date wins (the
    prompt reads the last line as today's print)."""
    by_day = {}
    for line in JOURNAL.read_text().splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        cell = ((rec.get("prices") or {}).get("current") or {}).get(grade)
        if cell:
            by_day[rec["date"]] = Decimal(cell.lstrip("$"))
    return sorted(by_day.items())


def settled_prints(grade: str) -> dict[str, Decimal]:
    """{date: print} from the grade's settled daily series. The API drops
    trailing zeros ('4.347'); pad back to AAA's 4 places."""
    out = {}
    for m in kalshi.settled_markets(SETTLED[grade]):
        value, event = m.get("expiration_value"), m.get("event_ticker") or ""
        if value in (None, "") or "-" not in event:
            continue
        day = datetime.strptime(event.split("-")[1], "%y%b%d").date()
        out[day.isoformat()] = Decimal(value).quantize(Decimal("0.0001"))
    return out


def _back(day: str, n: int) -> str:
    return (date.fromisoformat(day) - timedelta(days=n)).isoformat()


def _changes(prices: dict, day: str, n: int) -> list[Decimal] | None:
    """The n daily changes ending on `day`, or None if any print is missing."""
    run = [prices.get(_back(day, k)) for k in range(n, -1, -1)]
    if None in run:
        return None
    return [b - a for a, b in zip(run, run[1:])]


def forecasts(prices: dict, day: str, window: int) -> dict:
    """Each model's forecast for the day after `day` (None if unscorable)."""
    last = prices.get(day)
    if last is None:
        return dict.fromkeys(MODELS)
    mom, drift = _changes(prices, day, 1), _changes(prices, day, window)
    return {"RW": last,
            "MOM": last + mom[0] if mom else None,
            "DRIFT": last + sum(drift) / window if drift else None}


def _bar(prices: dict, day: str, window: int) -> str | None:
    ch = _changes(prices, day, window)
    if not ch or window < 2:
        return None
    mean = sum(ch) / window
    sd = (sum((c - mean) ** 2 for c in ch) / (window - 1)).sqrt()
    bar = 2 * sd / Decimal(window).sqrt()
    verdict = "drift clears" if abs(mean) > bar else "no drift"
    return (f"last-{window} mean {mean * CENT:+.2f}c sd {sd * CENT:.2f}c "
            f"bar {bar * CENT:.2f}c -> {verdict}")


def main(argv: list[str]):
    if not argv or argv[0] not in GRADES:
        sys.exit(__doc__)
    grade, window, days, opts = argv[0], 5, 10, argv[1:]
    use_settled = "--settled" in opts
    opts = [o for o in opts if o != "--settled"]
    if use_settled and grade not in SETTLED:
        sys.exit(f"--settled: no daily series for {grade} "
                 f"(only {', '.join(SETTLED)})")
    while opts:
        if opts[0] in ("--window", "--days") and len(opts) > 1:
            if opts[0] == "--window":
                window = int(opts[1])
            else:
                days = int(opts[1])
            opts = opts[2:]
        else:
            sys.exit(__doc__)
    rows = series(grade)
    note = None
    if use_settled:
        journaled = dict(rows)
        finals = settled_prints(grade)
        clash = [f"{d} journal {journaled[d]} vs settled {finals[d]}"
                 for d in sorted(journaled)
                 if d in finals and finals[d] != journaled[d]]
        merged = {**finals, **journaled}
        note = (f"# settled: +{len(merged) - len(journaled)} days from "
                f"{SETTLED[grade]} (journal wins)"
                + (f"; disagree: {'; '.join(clash)}" if clash else ""))
        rows = sorted(merged.items())
    if not rows:
        print(f"# no {grade} prints in {JOURNAL}")
        return
    prices = dict(rows)
    errs = {m: [] for m in MODELS}
    wins = dict.fromkeys(MODELS, 0)
    lines = []
    for day, actual in rows[1:]:
        fc = forecasts(prices, _back(day, 1), window)
        parts = [day, f"{actual}"]
        for m in MODELS:
            parts.append(f"{m} -" if fc[m] is None else
                         f"{m} {fc[m]:.4f} {(actual - fc[m]) * CENT:+.2f}")
        lines.append("  ".join(parts))
        if None not in fc.values():
            e = {m: abs(actual - fc[m]) * CENT for m in MODELS}
            best = min(e.values())
            for m in MODELS:
                errs[m].append(e[m])
                wins[m] += e[m] == best
    for line in reversed(lines[-days:]):
        print(line)
    if note:
        print(note)
    n = len(errs["RW"])
    if n:
        print(f"# n={n} ({grade}, window {window}): " + "  ".join(
            f"{m} MAE {sum(errs[m]) / n:.3f}c wins {wins[m]}" for m in MODELS))
    last = rows[-1][0]
    fc = forecasts(prices, last, window)
    nxt = [f"{m} {fc[m]:.4f}" for m in MODELS if fc[m] is not None]
    bar = _bar(prices, last, window)
    print(f"# next {_back(last, -1)}: " + "  ".join(nxt)
          + (f" | {bar}" if bar else ""))


if __name__ == "__main__":
    main(sys.argv[1:])
