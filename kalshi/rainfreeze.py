"""Mechanical RAW / MKT pre-regs for the KXRAIN family. Stdlib only, no auth.

The rain family scores three forecasts per city-day by Brier: RAW (the NWS
"Today" PoP), MKT (the board's mid at the morning run) and MINE. RAW and MKT
are mechanical, yet a day is lost whenever the judgment step doesn't pull
the grids (10/16: "no DC/NYC/OKC pre-regs frozen this run ... UNSCORABLE").

  python3 kalshi/rainfreeze.py freeze          # pipeline step: freeze today
  python3 kalshi/rainfreeze.py score [--days N] # Brier vs Kalshi results

`freeze` runs daily in bin/daily.sh before the judgment step and appends one
row per city to $DATA/wx/rain-freeze.jsonl: the first forecast periods as
NWS gave them (name, start, PoP, shortForecast — the Tonight period is the
straddle flag) and the KXRAIN board's exact bid/ask strings. RAW is the PoP
of the daytime period that starts on the market's local date (null PoP is
0); None once that period has rolled off. A leg that fails is recorded as
None and the other still freezes; exit 1 only if no city answered at all.

`score` reads the FIRST row per city-day (a freeze is binding; re-runs don't
overwrite it) and prints newest first: result, then each leg's p and Brier.
MINE stays in the watchlist — this only guarantees the mechanical legs.
"""

import datetime as dt
import json
import os
import pathlib
import sys
from decimal import ROUND_HALF_UP, Decimal

import kalshi
import wx

DATA = pathlib.Path(os.environ.get("KALSEER_DATA_DIR",
                                   pathlib.Path(__file__).parents[1] / "data"))
JOURNAL = DATA / "wx" / "rain-freeze.jsonl"

# Grid points the watchlist's pre-regs use (cli-precip-day-boundary, 10/15)
CITIES = {"DC": ("LWX", 97, 69), "NYC": ("OKX", 33, 37), "OKC": ("OUN", 94, 90)}
PERIODS = 2
Q4 = Decimal("0.0001")


def _periods(forecast: dict) -> list[dict]:
    return forecast.get("periods") or (forecast.get("properties") or {}).get(
        "periods") or []


def raw_pop(periods: list[dict], day: str) -> float | None:
    """The daytime period's PoP for `day` as a probability, or None."""
    for p in periods:
        if p.get("isDaytime") and str(p.get("startTime", ""))[:10] == day:
            value = (p.get("probabilityOfPrecipitation") or {}).get("value")
            return (value or 0) / 100
    return None


def ticker(city: str, day: str) -> str:
    return f"KXRAIN-{dt.date.fromisoformat(day):%y%b%d}-{city}".upper()


def freeze(today: str | None = None) -> tuple[int, list[str]]:
    """Append today's freeze per city. Returns (cities fully ok, failed)."""
    ok, failed, out = 0, [], []
    for city, (office, x, y) in CITIES.items():
        rec = {"city": city, "grid": f"{office} {x},{y}",
               "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(
                   timespec="seconds")}
        periods = []
        try:
            periods = _periods(wx._get(f"/gridpoints/{office}/{x},{y}/forecast"))
        except Exception as e:
            print(f"rainfreeze: {city}: NWS forecast failed: {e}",
                  file=sys.stderr)
        day = (str(periods[0].get("startTime", ""))[:10] if periods
               else today or dt.date.today().isoformat())
        rec.update(date=day, ticker=ticker(city, day), raw=raw_pop(periods, day),
                   periods=[{"name": p.get("name"), "start": p.get("startTime"),
                             "pop": (p.get("probabilityOfPrecipitation")
                                     or {}).get("value"),
                             "short": p.get("shortForecast")}
                            for p in periods[:PERIODS]])
        board = None
        try:
            board = kalshi.get_market(rec["ticker"])
        except Exception as e:
            print(f"rainfreeze: {city}: board {rec['ticker']} failed: {e}",
                  file=sys.stderr)
        rec.update(yes_bid=(board or {}).get("yes_bid_dollars"),
                   yes_ask=(board or {}).get("yes_ask_dollars"))
        if periods and board:
            ok += 1
        else:
            failed.append(city)
        if periods or board:
            out.append(rec)
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
    """First row per (date, city), oldest first."""
    first = {}
    for line in frozen_lines():
        r = json.loads(line)
        first.setdefault((r["date"], r["city"]), r)
    return [first[k] for k in sorted(first)]


def _brier(p: Decimal, y: int) -> Decimal:
    return ((p - y) ** 2).quantize(Q4, rounding=ROUND_HALF_UP)


def score(days: int = 14):
    rows = frozen()
    if not rows:
        print(f"# no freezes in {JOURNAL}")
        return
    since = (dt.date.fromisoformat(rows[-1]["date"])
             - dt.timedelta(days=days)).isoformat()
    briers = {"RAW": [], "MKT": []}
    lines = []
    for r in rows:
        if r["date"] < since:
            continue
        try:
            result = kalshi.get_market(r["ticker"]).get("result") or ""
        except Exception:
            result = ""
        legs = {}
        if r.get("raw") is not None:
            legs["RAW"] = Decimal(str(r["raw"]))
        if kalshi.board_mid(r.get("yes_bid"), r.get("yes_ask")) is not None:
            legs["MKT"] = (Decimal(r["yes_bid"]) + Decimal(r["yes_ask"])) / 2
        parts = [r["date"], r["city"], result if result in ("yes", "no")
                 else "pending"]
        for leg in ("RAW", "MKT"):
            if leg not in legs:
                parts.append(f"{leg} -")
                continue
            p = legs[leg]
            shown = f"{p:.2f}" if leg == "RAW" else f"{p.normalize():f}"
            if result in ("yes", "no"):
                b = _brier(p, result == "yes")
                parts.append(f"{leg} {shown} {b}")
            else:
                parts.append(f"{leg} {shown}")
        if result in ("yes", "no") and len(legs) == 2:
            for leg, p in legs.items():
                briers[leg].append((p - (result == "yes")) ** 2)
        lines.append("  ".join(parts))
    for line in reversed(lines):
        print(line)
    n = len(briers["RAW"])
    if n:
        print(f"# n={n} (city-days with both legs settled, last {days}d): "
              + "  ".join(f"{leg} {(sum(b) / n).quantize(Q4, ROUND_HALF_UP)}"
                          for leg, b in briers.items()))


def main(argv: list[str]):
    if argv[:1] == ["freeze"]:
        before = len(frozen_lines())
        ok, failed = freeze()
        print(f"rainfreeze: {ok}/{len(CITIES)} cities frozen in full"
              + (f"; failed: {' '.join(failed)}" if failed else ""))
        if len(frozen_lines()) == before:
            sys.exit(1)
        return
    if argv[:1] == ["score"]:
        days = 14
        if argv[1:2] == ["--days"] and len(argv) > 2:
            days = int(argv[2])
        elif argv[1:]:
            sys.exit(__doc__)
        score(days)
        return
    sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
