"""Mechanical RAW / MKT pre-regs for KXHIGH daily-high boards. Stdlib only.

The LAX Santa Ana ledger (watchlist lax-santa-ana-heat) needs ">=3 Santa Ana
days with grid vs CLI before pricing a bias", yet 10/17 was lost because the
judgment step pulled no grid. The grid high and the bucket board are
mechanical, so the pipeline freezes them, like rainfreeze.py for KXRAIN.

  python3 kalshi/highfreeze.py freeze           # pipeline step: freeze today
  python3 kalshi/highfreeze.py score [--days N]  # vs Kalshi's settled max

`freeze` appends one row per city to $DATA/wx/high-freeze.jsonl: the NWS
grid's daytime-period high for the market's local date (None once that
period has rolled off), its shortForecast, and every bucket of the
KXHIGH<city> event with exact bid/ask strings. A leg that fails is recorded
empty and the other still freezes; exit 1 only if no city answered at all.

`score` reads the FIRST row per city-day (binding) and prints newest first:
the settled max (Kalshi's expiration_value, the official number whichever
source the series names), the grid's error, and for RAW (normal around the
grid high, sd 3F, integer-degree bucket edges) and MKT (bucket mids) the
probability on the winning bucket and the all-bucket Brier. A bucket with an
empty or wider-than-0.20 book has no mid (kalshi.board_mid), so that day has
no MKT leg.

BIAS is RAW recentred on grid high minus the city's mean grid error over its
last 7 earlier settled days in the window (none from the day itself, so no
lookahead); it needs 3 such days. '# CITY:' lines give each city's grid bias,
and the summary adds BIAS vs MKT mean Brier over the days that have both.

EXTRA cities (the busiest boards outside the four) resolve their grid via
NWS /points each run and are summarised on their own '# extra' line.
"""

import datetime as dt
import json
import math
import os
import pathlib
import sys

import kalshi
import wx

DATA = pathlib.Path(os.environ.get("KALSEER_DATA_DIR",
                                   pathlib.Path(__file__).parents[1] / "data"))
JOURNAL = DATA / "wx" / "high-freeze.jsonl"

# KXHIGH<city> -> NWS grid (LAX: lax-santa-ana-heat; NY: Central Park, the
# grid the rain family uses for KXRAIN NYC; TDC / TOKC settle on CLIDCA /
# CLIOKC, the stations of KXRAIN DC / OKC, so they reuse rainfreeze's grids)
CITIES = {"LAX": ("LOX", 148, 41), "NY": ("OKX", 33, 37),
          "TDC": ("LWX", 97, 69), "TOKC": ("OUN", 94, 90)}
# The busiest KXHIGH boards outside the family (24h volume 10/28: MIA 13.7k,
# CHI 8.2k, AUS 7.5k vs TOKC 2.0k): the CLI station's coordinates, resolved
# to a grid via NWS /points each run (as rainfreeze.EXTRA). Scored in their
# own `# extra` summary.
EXTRA = {"MIA": (25.7881, -80.3169),    # CLIMIA, Miami Intl
         "CHI": (41.7861, -87.7524),    # CLIMDW, Chicago Midway
         "AUS": (30.1831, -97.6799)}    # CLIAUS, Austin-Bergstrom
SD = 3.0
BIAS_N, BIAS_MIN = 7, 3  # BIAS leg: mean grid error of the last <=7, >=3


def _periods(forecast: dict) -> list[dict]:
    return forecast.get("periods") or (forecast.get("properties") or {}).get(
        "periods") or []


def grid_high(periods: list[dict], day: str) -> int | None:
    for p in periods:
        if p.get("isDaytime") and str(p.get("startTime", ""))[:10] == day:
            return p.get("temperature")
    return None


def event_ticker(city: str, day: str) -> str:
    return f"KXHIGH{city}-{dt.date.fromisoformat(day):%y%b%d}".upper()


def _buckets(markets: list[dict]) -> list[dict]:
    return [{"ticker": m.get("ticker"), "strike_type": m.get("strike_type"),
             "floor": m.get("floor_strike"), "cap": m.get("cap_strike"),
             "yes_bid": m.get("yes_bid_dollars"),
             "yes_ask": m.get("yes_ask_dollars")} for m in markets]


def _cdf(x: float, mu: float) -> float:
    return 0.5 * (1 + math.erf((x - mu) / (SD * math.sqrt(2))))


def raw_p(bucket: dict, high: float) -> float:
    """P(settled max lands in bucket) for a normal around the grid high.

    Settled maxima are whole degrees: 'less' cap 87 is "86 or below",
    'greater' floor 94 is "95 or above", 'between' 87-88 is 87 to 88."""
    kind, lo, hi = bucket["strike_type"], bucket["floor"], bucket["cap"]
    if kind == "less":
        return _cdf(hi - 0.5, high)
    if kind == "greater":
        return 1 - _cdf(lo + 0.5, high)
    return _cdf(hi + 0.5, high) - _cdf(lo - 0.5, high)


def _grid(city: str) -> tuple[str, int, int]:
    """A family city's fixed grid, or an EXTRA city's from NWS /points."""
    if city in CITIES:
        return CITIES[city]
    lat, lon = EXTRA[city]
    p = wx._get(f"/points/{lat:.4f},{lon:.4f}")
    p = p.get("properties") or p
    return p["gridId"], int(p["gridX"]), int(p["gridY"])


def freeze(today: str | None = None) -> tuple[int, list[str]]:
    """Append today's freeze per city. Returns (cities fully ok, failed)."""
    ok, failed, out = 0, [], []
    for city in [*CITIES, *EXTRA]:
        rec = {"city": city, "grid": None,
               "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(
                   timespec="seconds")}
        periods = []
        try:
            if city in EXTRA:
                rec["grid"] = "points {:.4f},{:.4f}".format(*EXTRA[city])
            office, x, y = _grid(city)
            rec["grid"] = f"{office} {x},{y}"
            periods = _periods(wx._get(f"/gridpoints/{office}/{x},{y}/forecast"))
        except Exception as e:
            print(f"highfreeze: {city}: NWS forecast failed: {e}",
                  file=sys.stderr)
        day = (str(periods[0].get("startTime", ""))[:10] if periods
               else today or dt.date.today().isoformat())
        today_p = [p for p in periods if p.get("isDaytime")
                   and str(p.get("startTime", ""))[:10] == day]
        rec.update(date=day, event=event_ticker(city, day),
                   high=grid_high(periods, day),
                   short=today_p[0].get("shortForecast") if today_p else None)
        markets = []
        try:
            markets = kalshi.get_event(rec["event"]).get("markets") or []
        except Exception as e:
            print(f"highfreeze: {city}: board {rec['event']} failed: {e}",
                  file=sys.stderr)
        rec["buckets"] = _buckets(markets)
        if periods and markets:
            ok += 1
        else:
            failed.append(city)
        if periods or markets:
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


def _mid(b: dict) -> float | None:
    return kalshi.board_mid(b.get("yes_bid"), b.get("yes_ask"))


def _leg(name: str, probs: list[float], won: list[bool]) -> tuple[str, float]:
    brier = sum((p - y) ** 2 for p, y in zip(probs, won))
    return (f"{name} p {sum(p for p, y in zip(probs, won) if y):.4f} "
            f"B {brier:.4f}"), brier


HELD_HOURS = 24  # KXHIGH settles hours after close; a day later is a hold


def _held(markets: list[dict]) -> str:
    """'  HELD: …' when every market closed over HELD_HOURS ago with no
    result (KXHIGHLAX-26OCT22: CLILAX revised 71 -> 72 -> 71, on the edge)."""
    closes = [m.get("close_time") for m in markets]
    if not closes or not all(closes):
        return ""
    close = max(closes)
    try:
        closed = dt.datetime.fromisoformat(close.replace("Z", "+00:00"))
    except ValueError:
        return ""
    age = dt.datetime.now(dt.timezone.utc) - closed
    if age < dt.timedelta(hours=HELD_HOURS):
        return ""
    return f"  HELD: closed {close}, Kalshi has not settled"


def score(days: int = 14):
    rows = frozen()
    if not rows:
        print(f"# no freezes in {JOURNAL}")
        return
    since = (dt.date.fromisoformat(rows[-1]["date"])
             - dt.timedelta(days=days)).isoformat()
    # family / extra tallies: (grid errors, RAW+MKT briers, BIAS-vs-MKT pairs)
    groups = {g: ([], {"RAW": [], "MKT": []}, []) for g in ("", "extra ")}
    lines, city_errs = [], {}
    for r in rows:
        errs, briers, bias_pairs = groups[
            "extra " if r["city"] in EXTRA else ""]
        if r["date"] < since:
            continue
        try:
            markets = kalshi.get_event(r["event"]).get("markets") or []
        except Exception:
            markets = []
        result = {m.get("ticker"): m.get("result") for m in markets}
        values = [m.get("expiration_value") for m in markets
                  if m.get("result") in ("yes", "no")
                  and m.get("expiration_value") not in (None, "")]
        high, buckets = r.get("high"), r.get("buckets") or []
        grid = f"grid {high}" if high is not None else "grid -"
        if not values:
            lines.append(f"{r['date']}  {r['city']}  pending  {grid}"
                         + _held(markets))
            continue
        actual = float(values[0])
        parts = [r["date"], r["city"], f"{actual:g}"]
        prior = city_errs.setdefault(r["city"], [])[-BIAS_N:]
        if high is not None:
            errs.append(high - actual)
            city_errs[r["city"]].append(high - actual)
            parts.append(f"{grid} err {high - actual:+g}")
        else:
            parts.append(grid)
        won = [result.get(b["ticker"]) == "yes" for b in buckets]
        legs = {}
        if buckets and high is not None:
            legs["RAW"] = [raw_p(b, high) for b in buckets]
            if len(prior) >= BIAS_MIN:
                centre = high - sum(prior) / len(prior)
                legs["BIAS"] = [raw_p(b, centre) for b in buckets]
        mids = [_mid(b) for b in buckets]
        if buckets and None not in mids:
            legs["MKT"] = mids
        scored = {}
        for name in ("RAW", "MKT", "BIAS"):
            if name not in legs or not any(won):
                parts.append(f"{name} -")
                continue
            text, scored[name] = _leg(name, legs[name], won)
            parts.append(text)
        if "RAW" in scored and "MKT" in scored:
            briers["RAW"].append(scored["RAW"])
            briers["MKT"].append(scored["MKT"])
        if "BIAS" in scored and "MKT" in scored:
            bias_pairs.append((scored["BIAS"], scored["MKT"]))
        lines.append("  ".join(parts))
    for line in reversed(lines):
        print(line)
    for city, e in sorted(city_errs.items()):
        if e:
            print(f"# {city}: n={len(e)} grid bias {sum(e) / len(e):+.1f}F "
                  f"MAE {sum(map(abs, e)) / len(e):.1f}F")
    for label, (errs, briers, bias_pairs) in groups.items():
        _summary(label, days, errs, briers, bias_pairs)


def _summary(label: str, days: int, errs: list, briers: dict,
             bias_pairs: list):
    if errs:
        n = len(errs)
        what = (f"settled {'/'.join(EXTRA)} city-days" if label
                else "settled city-days")
        summary = (f"# {label}n={n} {what} (last {days}d): grid bias "
                   f"{sum(errs) / n:+.1f}F MAE {sum(map(abs, errs)) / n:.1f}F")
        if briers["RAW"]:
            summary += "  " + "  ".join(
                f"{k} B {sum(v) / len(v):.4f}" for k, v in briers.items())
        if bias_pairs:
            k = len(bias_pairs)
            summary += (f"  BIAS B {sum(b for b, _ in bias_pairs) / k:.4f} "
                        f"vs MKT B {sum(m for _, m in bias_pairs) / k:.4f} "
                        f"(n={k})")
        print(summary)


def main(argv: list[str]):
    if argv[:1] == ["freeze"]:
        before = len(frozen_lines())
        ok, failed = freeze()
        print(f"highfreeze: {ok}/{len(CITIES) + len(EXTRA)} cities frozen in full"
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
