"""Rotten Tomatoes fresh-count pin for the judgment step. Pure math, no net.

The rt-method-notes watchlist item (DURABLE METHOD NOTE): displayed% +
review count usually PINS the fresh/rotten split exactly — the 1pp rounding
band contains ~n/100 integers; for n < 100 almost always exactly one; when
two or more fit, disambiguate from yesterday's pinned split plus arrivals,
else use the CONSERVATIVE count for the direction traded. The judgment
session re-derives that arithmetic by hand every RT day on a number trades
settle against; this makes it one command and surfaces the second candidate
a hand calculation can miss (45% on 128 hides 57 behind the ledger's 58).

  python3 kalshi/rt.py pin 53 114                 # displayed %, review count
  python3 kalshi/rt.py pin 45 128 --prev 58/127   # yesterday's pin filters
  python3 kalshi/rt.py floor 90 70 85             # ... + market threshold
  python3 kalshi/rt.py floor 45 128 44 --prev 58/127

A candidate is any fresh count whose exact rate rounds to the displayed
percent. An exact .5 rate is listed for both neighbors and flagged — RT's
rounding side at the boundary is unverified. A display no integer split can
produce is a misread and a loud exit, never silence.

`floor` is the THREE-STEP RULE's step (2) on top of the pin: per candidate,
the HARD FLOOR (straight rotten reviews until YES on "above T" can lose) and
the HARD CEILING (straight fresh reviews until NO can lose). It assumes YES
iff the displayed score is greater than T, and an exact .5 counts against
whichever side holds — the conservative reading for both directions.
"""

import sys

BOUNDARY = "[.5 boundary — rounding side unverified]"


def candidates(pct: int, count: int) -> list[tuple[int, bool]]:
    """Fresh counts whose exact rate rounds to pct; True marks an exact .5.

    100*f/count is within half a point of pct iff |200*f - 2*pct*count| is
    at most count — integer arithmetic, no float equality at the boundary.
    """
    out = []
    for fresh in range(count + 1):
        gap = abs(200 * fresh - 2 * pct * count)
        if gap <= count:
            out.append((fresh, gap == count))
    return out


def floor(fresh: int, count: int, threshold: int) -> int:
    """Straight rotten reviews until the display can be <= threshold.

    fresh/(count+k) can display <= T iff 200*fresh <= (2T+1)*(count+k) —
    the exact .5 included, since its rounding side is unverified.
    """
    need = 200 * fresh - (2 * threshold + 1) * count
    return max(0, -(-need // (2 * threshold + 1)))


def ceiling(fresh: int, count: int, threshold: int) -> int | None:
    """Straight fresh reviews until the display can be > threshold.

    (fresh+k)/(count+k) can display > T iff 200*(fresh+k) >= (2T+1)*(count+k),
    exact .5 included. None when T >= 100: no display exceeds it.
    """
    if threshold >= 100:
        return None
    need = (2 * threshold + 1) * count - 200 * fresh
    return max(0, -(-need // (199 - 2 * threshold)))


def _rate(fresh: int, count: int) -> str:
    return f"{fresh}/{count} = {100 * fresh / count:.3f}%"


def _floor_lines(fresh: int, count: int, t: int) -> list[str]:
    k = floor(fresh, count, t)
    if k == 0:
        yes = f"YES >{t}: already losing ({_rate(fresh, count)} can show <={t})"
    else:
        yes = (f"YES >{t}: {k} straight rotten -> {_rate(fresh, count + k)} "
               f"(can show <={t})")
    k = ceiling(fresh, count, t)
    if k is None:
        no = f"NO >{t}: safe — no display exceeds {t}"
    elif k == 0:
        no = f"NO >{t}: already losing ({_rate(fresh, count)} can show >{t})"
    else:
        no = (f"NO >{t}: {k} straight fresh -> {_rate(fresh + k, count + k)} "
              f"(can show >{t})")
    return [f"  {yes}", f"  {no}"]


def _summary(label: str, ks: list[int | None], unit: str) -> str:
    known = [k for k in ks if k is not None]
    if not known:
        return f"# conservative {label}: safe on every pin"
    k = min(known)
    return (f"# conservative {label}: "
            + ("already losing" if k == 0 else f"{k} straight {unit}"))


def main_floor(argv: list[str]):
    prev, opts = None, argv[3:]
    while opts:
        if opts[:1] == ["--prev"] and len(opts) > 1 and "/" in opts[1]:
            prev, opts = opts[1], opts[2:]
        else:
            sys.exit(__doc__)
    try:
        pct, count, t = int(argv[0]), int(argv[1]), int(argv[2])
        assert 0 <= pct <= 100 and count >= 1 and 0 <= t <= 100
        if prev:
            prev_fresh, prev_count = map(int, prev.split("/"))
            assert 0 <= prev_fresh <= prev_count
    except (ValueError, AssertionError):
        sys.exit(__doc__)

    pins = [fresh for fresh, _ in candidates(pct, count)]
    if not pins:
        print(f"rt: no integer split shows {pct}% on {count} reviews — "
              "re-read the page", file=sys.stderr)
        sys.exit(2)
    if prev is not None and prev_count <= count:
        kept = [f for f in pins
                if prev_fresh <= f <= prev_fresh + count - prev_count]
        if kept:
            pins = kept
        else:
            print(f"# no pin consistent with --prev {prev} — showing all")

    print(f"# assumes YES iff the displayed score > {t} (read the rules); "
          "an exact .5 counts against the holder")
    for fresh in pins:
        print(_rate(fresh, count))
        for line in _floor_lines(fresh, count, t):
            print(line)
    if len(pins) > 1:
        print(_summary(f"YES >{t} floor",
                       [floor(f, count, t) for f in pins], "rotten"))
        print(_summary(f"NO >{t} ceiling",
                       [ceiling(f, count, t) for f in pins], "fresh"))


def main(argv: list[str]):
    if argv[:1] == ["floor"] and len(argv) >= 4:
        return main_floor(argv[1:])
    if argv[:1] != ["pin"] or len(argv) < 3:
        sys.exit(__doc__)
    prev, opts = None, argv[3:]
    while opts:
        if opts[:1] == ["--prev"] and len(opts) > 1 and "/" in opts[1]:
            prev, opts = opts[1], opts[2:]
        else:
            sys.exit(__doc__)
    try:
        pct, count = int(argv[1]), int(argv[2])
        assert 0 <= pct <= 100 and count >= 1
        if prev:
            prev_fresh, prev_count = map(int, prev.split("/"))
            assert 0 <= prev_fresh <= prev_count
    except (ValueError, AssertionError):
        sys.exit(__doc__)

    cands = candidates(pct, count)
    if not cands:
        print(f"rt: no integer split shows {pct}% on {count} reviews — "
              "re-read the page", file=sys.stderr)
        sys.exit(2)

    filtering = prev is not None and prev_count <= count
    consistent = []
    for fresh, edge in cands:
        line = f"{fresh}/{count} = {100 * fresh / count:.3f}%"
        if edge:
            line += f"  {BOUNDARY}"
        if filtering:
            arrivals = count - prev_count
            if prev_fresh <= fresh <= prev_fresh + arrivals:
                consistent.append(fresh)
                line += (f"  consistent with --prev (+{fresh - prev_fresh} "
                         f"fresh of +{arrivals} reviews)")
            else:
                line += "  inconsistent with --prev"
        print(line)

    if len(cands) == 1:
        (fresh, _), = cands
        print(f"# unique pin: {fresh}/{count} fresh "
              f"({100 * fresh / count:.3f}%)")
    else:
        print(f"# {len(cands)} candidates for {pct}% on {count} — "
              "disambiguate from yesterday's pin + arrivals, else take the "
              "CONSERVATIVE count for the direction traded")
        if filtering and len(consistent) == 1:
            print(f"# unique after --prev: {consistent[0]}/{count}")
    if prev is not None and prev_count > count:
        print(f"# --prev has more reviews than today (review count fell "
              f"{prev_count} -> {count}) — not filtering; RT dropped reviews")


if __name__ == "__main__":
    main(sys.argv[1:])
