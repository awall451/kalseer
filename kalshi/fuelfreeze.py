"""Mechanical RW / MOM / DRIFT odds on every open AAA fuel strike. Stdlib only.

The judgment step logs "divergence datums" (watchlist aaa-gas-tracking-oct:
the board at a strike vs the trend models' k-print odds, "board now 3-1")
by hand: a normal around each model's centre, frozen in watchlist prose,
scored days later. The models and the board are mechanical, so the pipeline
freezes them after the AAA print, like rainfreeze.py / highfreeze.py.

  python3 kalshi/fuelfreeze.py freeze           # pipeline step: freeze today
  python3 kalshi/fuelfreeze.py score [--days N]  # vs Kalshi's settled results

`freeze` appends one row per open event of KXAAAGASD/W/M and KXDIESELD/W to
$DATA/aaa/fuel-freeze.jsonl. The event settles on the AAA print dated by its
ticker, k prints after the journal's newest (the base). Centres (fuelscore's
models stretched over k prints): RW base, MOM base + k x the last change,
DRIFT base + k x the mean of the last --window (5) changes. Each model's P(print
> strike) is a normal with sd = sample sd of those changes x sqrt(k), floored
at 0.05c. Every strike keeps its exact bid/ask strings. Strikes where the board
mid and a model differ by >= 0.25 are printed as divergences; a strike with
no quotes or a spread over 0.20 has no board mid, so it is never a
divergence and never enters the BOARD Brier. Events the
journal already settles (k <= 0) are skipped. Exit 1 only if no series
answered at all.

`score` reads the FIRST row per event (binding) and prints newest first: the
settled print (Kalshi's expiration_value), each leg's mean per-strike Brier,
and a board-vs-model tally over divergent strikes, where whichever is
closer to the outcome wins. The summary's n is every settled event; a leg
scored on fewer (BOARD, when books were empty) shows its own (nK). Those
means run over different strikes, so a paired line scores each model and
BOARD on the same board-priced strikes (mK of them). Until Kalshi settles an
event, it scores off the AAA journal's print for its date (the exact value
it settles on), marked "(AAA journal, Kalshi unsettled)"; a strike the
print sits exactly on is left out.

EMP is a fourth, non-parametric leg: P(print > strike) is the share of every
k-print change in the trailing EMP_DAYS (90) that lands base + change above
the strike, smoothed (n_above + 0.5) / (n + 1). History is Kalshi's settled
KXAAAGASD / KXDIESELD prints (fuelscore.settled_prints) with the journal over
them; under EMP_MIN (10) changes EMP is None. It carries the shock weeks the
5-change trend sd never sees (brief 10/20: "1.3c sd is far too tight").

EMPD is EMP centred on DRIFT: the same changes less their mean, plus DRIFT's
k-print move (None without a DRIFT centre). EMP carries the history's own
drift (September's diesel run-up, in a 9-day gas decline), so a board-EMP
loss can be the tails or the drift; EMPD keeps the tails and drops the drift.

WKDAY is log-only: on k=1 KXAAAGASD events only, a normal around
fuelscore.wkday's centre (MOM scaled by the weekday's mean |change|) with the
legs' sd. It is not in SCORED, so the summary, paired and divergence lines
never move; `score` grades it on its own line against MOM (same strikes) and
BOARD (board-priced ones). Brief 11/2: the weekday falsifier went 2-0.

The board's centre is where its mids cross 0.5, linear between the two
bracketing priced floors (brief 11/8: "the gas board was centred ~4.0195 and
missed by only +0.08c, the best of every forecaster", read by hand). `freeze`
prints it per event next to each model's centre; `score` adds each centre's
miss (print - centre, cents) and the closest to the event's line, and a
'# centre miss' line pairs each model with BOARD on the events whose board
crosses 0.5 on the ladder (an off-ladder centre, '<f' or '>f', is not scored).
"""

import datetime as dt
import json
import math
import os
import pathlib
import sys
from decimal import Decimal

import fuelscore
import kalshi

DATA = pathlib.Path(os.environ.get("KALSEER_DATA_DIR",
                                   pathlib.Path(__file__).parents[1] / "data"))
JOURNAL = DATA / "aaa" / "fuel-freeze.jsonl"

SERIES = {"KXAAAGASD": "regular", "KXAAAGASW": "regular",
          "KXAAAGASM": "regular", "KXDIESELD": "diesel",
          "KXDIESELW": "diesel"}
MODELS = fuelscore.MODELS
SCORED = MODELS + ("EMP", "EMPD")
LEGS = ("BOARD",) + SCORED
# log-only (never in SCORED): fuelscore.wkday's centre, next-print gas only
WKDAY_SERIES = ("KXAAAGASD",)
EMP_DAYS = 90  # trailing days of k-print changes behind EMP
EMP_MIN = 10   # fewer changes than this: no EMP odds
WINDOW = 5
SD_FLOOR = 0.0005  # dollars: 0.05c
GAP = 0.25
MAX_SPREAD = Decimal("0.20")  # wider books are no board price


def settle_day(event: str) -> str:
    return dt.datetime.strptime(event.split("-")[1], "%y%b%d").date().isoformat()


def _p_above(strike: float, centre: float, sd: float) -> float:
    return 0.5 * (1 - math.erf((strike - centre) / (sd * math.sqrt(2))))


def model(prices: dict, base_day: str, k: int, window: int = WINDOW) -> dict:
    """Centres and the k-print sd off the journal; centres None if a
    window day is missing (fuelscore never scores across a gap)."""
    base = prices[base_day]
    ch = fuelscore._changes(prices, base_day, window)
    if not ch:
        return {"centre": dict.fromkeys(MODELS), "sd": None}
    mean = sum(ch) / window
    sd = float((sum((c - mean) ** 2 for c in ch) / (window - 1)).sqrt())
    return {"centre": {"RW": base, "MOM": base + k * ch[-1],
                       "DRIFT": base + k * mean},
            "sd": max(sd, SD_FLOOR) * math.sqrt(k)}


def history(grade: str) -> dict:
    """{date: print}: Kalshi's settled daily prints (back past the journal's
    start), the journal over them. A failed fetch leaves the journal."""
    try:
        out = dict(fuelscore.settled_prints(grade))
    except Exception as e:
        print(f"fuelfreeze: {grade}: settled history failed: {e}",
              file=sys.stderr)
        out = {}
    out.update(fuelscore.series(grade))
    return out


def empirical(prices: dict, base_day: str, k: int,
              days: int | None = None) -> list[Decimal]:
    """Every k-print change starting in the trailing `days` (EMP_DAYS)
    before base_day, both ends printed."""
    base = dt.date.fromisoformat(base_day)
    out = []
    for back in range(k, (days or EMP_DAYS) + 1):
        a = (base - dt.timedelta(days=back)).isoformat()
        b = (base - dt.timedelta(days=back - k)).isoformat()
        if a in prices and b in prices:
            out.append(prices[b] - prices[a])
    return out


def _p_emp(strike, base: Decimal, changes: list) -> float | None:
    """Share of changes landing above the strike, smoothed off 0 and 1."""
    if strike is None or len(changes) < EMP_MIN:
        return None
    above = sum(base + c > Decimal(str(strike)) for c in changes)
    return (above + 0.5) / (len(changes) + 1)


def _p_empd(strike, base: Decimal, changes: list,
            shift: Decimal | None) -> float | None:
    """EMP's changes de-meaned and moved by `shift` (DRIFT's k-print move)."""
    if shift is None or len(changes) < EMP_MIN:
        return None
    mean = sum(changes) / len(changes)
    return _p_emp(strike, base + shift - mean, changes)


def _mid(s: dict) -> float | None:
    """The board's price, or None when the book is no board: no quotes at
    all (0.0000/0.0000) or a spread wider than MAX_SPREAD (0.01/0.99)."""
    if not (s.get("yes_bid") and s.get("yes_ask")):
        return None
    bid, ask = Decimal(s["yes_bid"]), Decimal(s["yes_ask"])
    if not bid < ask <= bid + MAX_SPREAD:
        return None
    return float(bid + ask) / 2


def freeze() -> tuple[list[str], list[str]]:
    """Append today's freeze per open event. Returns (events, failed series)."""
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    journals = {g: dict(fuelscore.series(g)) for g in set(SERIES.values())}
    hist = {g: history(g) for g in sorted(journals)}
    out, failed = [], []
    for series, grade in SERIES.items():
        try:
            markets = kalshi.get_markets(series_ticker=series, status="open")
        except Exception as e:
            print(f"fuelfreeze: {series}: board failed: {e}", file=sys.stderr)
            failed.append(series)
            continue
        prices = journals[grade]
        if not prices:
            continue
        base_day = max(prices)
        by_event = {}
        for m in markets:
            by_event.setdefault(m.get("event_ticker"), []).append(m)
        for event, ms in sorted(by_event.items()):
            day = settle_day(event)
            k = (dt.date.fromisoformat(day)
                 - dt.date.fromisoformat(base_day)).days
            if k <= 0:
                continue
            fit = model(prices, base_day, k)
            if series in WKDAY_SERIES and k == 1:
                # no sd (a window gap) prices no leg, WKDAY included
                fit["centre"]["WKDAY"] = (None if fit["sd"] is None
                                          else fuelscore.wkday(prices,
                                                               base_day))
            changes = empirical(hist[grade], base_day, k)
            strikes = []
            for m in sorted(ms, key=lambda m: m.get("floor_strike") or 0):
                floor = m.get("floor_strike")
                p = {name: (None if c is None or floor is None else
                            _p_above(floor, float(c), fit["sd"]))
                     for name, c in fit["centre"].items()}
                p["EMP"] = _p_emp(floor, prices[base_day], changes)
                drift = fit["centre"]["DRIFT"]
                p["EMPD"] = _p_empd(floor, prices[base_day], changes,
                                    None if drift is None
                                    else drift - prices[base_day])
                strikes.append({"ticker": m.get("ticker"), "floor": floor,
                                "yes_bid": m.get("yes_bid_dollars"),
                                "yes_ask": m.get("yes_ask_dollars"), "p": p})
            out.append({"event": event, "series": series, "grade": grade,
                        "date": day, "base_date": base_day,
                        "base": f"{prices[base_day]:.4f}", "k": k,
                        "window": WINDOW, "fetched_at": now,
                        "centre": {n: None if c is None else f"{c:.4f}"
                                   for n, c in fit["centre"].items()},
                        "sd": None if fit["sd"] is None
                        else round(fit["sd"] * 100, 4),
                        "emp_n": len(changes), "strikes": strikes})
    if out:
        JOURNAL.parent.mkdir(parents=True, exist_ok=True)
        with JOURNAL.open("a") as f:
            f.writelines(json.dumps(r) + "\n" for r in out)
    return [r["event"] for r in out], failed


def centre(rec: dict) -> tuple[str, float | None]:
    """The board's implied centre: where the board mids cross 0.5, linear
    between the two priced floors that bracket it (econfreeze.median's
    rule). ('<', f) or ('>', f) when the crossing is off the ladder;
    ('-', None) when no strike has a board mid."""
    pts = sorted((s["floor"], mid) for s in rec["strikes"]
                 if s.get("floor") is not None
                 and (mid := _mid(s)) is not None)
    if not pts:
        return "-", None
    if pts[0][1] < 0.5:
        return "<", pts[0][0]
    for (a, pa), (b, pb) in zip(pts, pts[1:]):
        if pa >= 0.5 > pb:
            return "", a + (b - a) * (pa - 0.5) / (pa - pb)
    return ">", pts[-1][0]


def centres(rec: dict) -> dict[str, tuple[str, float | None]]:
    """BOARD's centre, then each model's frozen centre ('', value)."""
    out = {"BOARD": centre(rec)}
    for name, c in (rec.get("centre") or {}).items():
        if c is not None:
            out[name] = ("", float(c))
    return out


def centre_line(rec: dict) -> str:
    return (f"  {rec['event']} centre: " + "  ".join(
        f"{n} -" if v is None else f"{n} {side}{v:.4f}"
        for n, (side, v) in centres(rec).items()))


def centre_misses(rec: dict, actual: Decimal) -> tuple[str, dict]:
    """'centre miss (c): …' for the event's line, and {leg: |miss| cents}
    over the legs whose centre is on the ladder."""
    parts, miss = [], {}
    for n, (side, v) in centres(rec).items():
        if v is None or side:
            parts.append(f"{n} {side}{v:.4f}" if v is not None else f"{n} -")
            continue
        err = (float(actual) - v) * 100
        parts.append(f"{n} {v:.4f} {err:+.2f}")
        miss[n] = abs(round(err, 6))
    text = "centre miss (c): " + "  ".join(parts)
    if len(miss) > 1:
        best = min(miss.values())
        text += "  -> closest " + "/".join(n for n, m in miss.items()
                                          if m == best)
    return text, miss


def divergences(rec: dict) -> list[str]:
    lines = []
    for s in rec["strikes"]:
        mid = _mid(s)
        if mid is None:
            continue
        far = [f"{n} {p:.2f}" for n, p in s["p"].items()
               if p is not None and abs(mid - p) >= GAP]
        if far:
            lines.append(f"  {rec['event']} >{s['floor']:g} board {mid:.2f}  "
                         + "  ".join(far))
    return lines


def frozen_lines() -> list[str]:
    if not JOURNAL.exists():
        return []
    return [l for l in JOURNAL.read_text().splitlines() if l.strip()]


def frozen() -> list[dict]:
    """First row per event, oldest settlement day first."""
    first = {}
    for line in frozen_lines():
        r = json.loads(line)
        first.setdefault(r["event"], r)
    return sorted(first.values(), key=lambda r: (r["date"], r["event"]))


def _journal_print(journals: dict, r: dict) -> Decimal | None:
    """The AAA journal's print for the row's settlement day, or None;
    `journals` caches each grade's series."""
    if r.get("grade") not in journals:
        try:
            journals[r.get("grade")] = dict(fuelscore.series(r["grade"]))
        except (KeyError, OSError, ValueError):
            journals[r.get("grade")] = {}
    return journals[r.get("grade")].get(r["date"])


def _today() -> dt.date:
    return dt.datetime.now(dt.timezone.utc).date()


def score(days: int = 14):
    rows = frozen()
    if not rows:
        print(f"# no freezes in {JOURNAL}")
        return
    # count back from the newest frozen day that isn't in the future: the
    # month-end event (11/10: 11/30) pushed a 14-day window past every
    # settled daily, so the bare `score` showed only pending rows
    today = _today().isoformat()
    past = [r["date"] for r in rows if r["date"] <= today]
    since = (dt.date.fromisoformat(past[-1] if past else today)
             - dt.timedelta(days=days)).isoformat()
    briers = {leg: [] for leg in LEGS}
    tally = {n: [0, 0] for n in SCORED}
    paired = {n: [0.0, 0.0, 0] for n in SCORED}  # model, board, strikes
    # log-only WKDAY: [WKDAY, MOM, strikes] on its strikes, then
    # [WKDAY, BOARD, strikes] on the board-priced ones, and its events
    wk, wk_board, wk_events = [0.0, 0.0, 0], [0.0, 0.0, 0], 0
    # centre misses in cents on events with an on-ladder board centre:
    # model, board, model closer, board closer, events
    cpair = {}
    settled = 0
    lines, journals = [], {}
    for r in rows:
        if r["date"] < since:
            continue
        head = f"{r['date']}  {r['event']}  k{r['k']}"
        try:
            markets = kalshi.get_event(r["event"]).get("markets") or []
        except Exception:
            markets = []
        result = {m.get("ticker"): m.get("result") for m in markets}
        values = [m.get("expiration_value") for m in markets
                  if m.get("result") in ("yes", "no")
                  and m.get("expiration_value") not in (None, "")]
        source = ""
        if not values:
            actual = _journal_print(journals, r)
            if actual is None:
                lines.append(f"{head}  pending")
                continue
            # the exact print the event settles on; a strike it sits on
            # is left unscored
            result = {s["ticker"]: "yes" if actual > Decimal(str(s["floor"]))
                      else "no" for s in r["strikes"]
                      if s["floor"] is not None
                      and actual != Decimal(str(s["floor"]))}
            values = [actual]
            source = "  (AAA journal, Kalshi unsettled)"
        legs = {leg: [] for leg in LEGS}
        wkday = []
        for s in r["strikes"]:
            if result.get(s["ticker"]) not in ("yes", "no"):
                continue
            y = result[s["ticker"]] == "yes"
            mid = _mid(s)
            if mid is not None:
                legs["BOARD"].append((mid - y) ** 2)
            w, mom = s["p"].get("WKDAY"), s["p"].get("MOM")
            if w is not None and mom is not None:
                wkday.append((w - y) ** 2)
                wk[0] += (w - y) ** 2
                wk[1] += (mom - y) ** 2
                wk[2] += 1
                if mid is not None:
                    wk_board[0] += (w - y) ** 2
                    wk_board[1] += (mid - y) ** 2
                    wk_board[2] += 1
            for n in SCORED:
                p = s["p"].get(n)
                if p is None:
                    continue
                legs[n].append((p - y) ** 2)
                if mid is not None:
                    paired[n][0] += (p - y) ** 2
                    paired[n][1] += (mid - y) ** 2
                    paired[n][2] += 1
                if mid is not None and abs(mid - p) >= GAP:
                    gap = abs(mid - y) - abs(p - y)
                    if gap:
                        tally[n][gap > 0] += 1
        settled += 1
        actual = Decimal(values[0]).quantize(Decimal("0.0001"))
        parts = [r["date"], r["event"], f"{actual}", f"k{r['k']}"]
        for leg in LEGS:
            v = legs[leg]
            parts.append(f"{leg} {sum(v) / len(v):.4f}" if v else f"{leg} -")
            if v:
                briers[leg].append(sum(v) / len(v))
        if wkday:
            wk_events += 1
            parts.append(f"WKDAY {sum(wkday) / len(wkday):.4f}")
        text, miss = centre_misses(r, actual)
        parts.append(text)
        if "BOARD" in miss:
            for n, m in miss.items():
                if n != "BOARD":
                    c = cpair.setdefault(n, [0.0, 0.0, 0, 0, 0])
                    c[0] += m
                    c[1] += miss["BOARD"]
                    c[2] += m < miss["BOARD"]
                    c[3] += miss["BOARD"] < m
                    c[4] += 1
        lines.append("  ".join(parts) + source)
    for line in reversed(lines):
        print(line)
    if settled:
        print(f"# n={settled} settled events (last {days}d), mean per-strike "
              "Brier: " + "  ".join(
                  f"{leg} {sum(v) / len(v):.4f}"
                  + ("" if len(v) == settled else f" (n{len(v)})")
                  for leg, v in briers.items() if v))
        pairs = [f"{m} {mb / k:.4f} vs BOARD {bb / k:.4f} (m{k})"
                 for m, (mb, bb, k) in paired.items() if k]
        if pairs:
            print("# same strikes, board-priced only (per-strike Brier): "
                  + "  ".join(pairs))
        print(f"# divergences (|board - model| >= {GAP}, closer to the "
              "outcome wins): " + "  ".join(
                  f"board-{m} {w}-{l}" for m, (w, l) in tally.items()))
    if cpair:
        print("# centre miss, same events (mean |print - centre|, closer "
              "wins): " + "  ".join(
                  f"{n} {mm / k:.2f}c vs BOARD {bm / k:.2f}c {w}-{l} (m{k})"
                  for n, (mm, bm, w, l, k) in cpair.items()))
    if wk[2]:
        text = (f"# log-only WKDAY (k1 gas, not in the lines above): "
                f"n={wk_events} events (m{wk[2]} strikes) WKDAY "
                f"{wk[0] / wk[2]:.4f} vs MOM {wk[1] / wk[2]:.4f}")
        if wk_board[2]:
            text += (f"; board-priced WKDAY {wk_board[0] / wk_board[2]:.4f}"
                     f" vs BOARD {wk_board[1] / wk_board[2]:.4f}"
                     f" (m{wk_board[2]})")
        print(text)


def main(argv: list[str]):
    if argv[:1] == ["freeze"]:
        events, failed = freeze()
        rows = {json.loads(l)["event"]: json.loads(l)
                for l in frozen_lines()[-len(events):]} if events else {}
        print(f"fuelfreeze: {len(events)} events frozen"
              + (f" ({' '.join(events)})" if events else "")
              + (f"; failed: {' '.join(failed)}" if failed else ""))
        for e in events:
            print(centre_line(rows[e]))
            for line in divergences(rows[e]):
                print(line)
        if len(failed) == len(SERIES):
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
