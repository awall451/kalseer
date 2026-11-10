"""Daily board snapshots of the macro release ladders. Stdlib only.

The payrolls/CPI calibration item ("Oct CPI pre-reg ~T-5, record board move
T-5 -> T-1") was a hand-copied board on two chosen days, lost whenever the
run was busy elsewhere. Kalshi's macro boards (KXPAYROLLS, KXU3, KXCPI,
KXCPICORE, KXCPIYOY, KXCPICOREYOY) are 'greater' ladders that settle on the
first BLS print, so the board alone is the calibration datum: freeze it every
morning, read the T-n path back, and score it once Kalshi settles.

  python3 kalshi/econfreeze.py freeze           # pipeline step
  python3 kalshi/econfreeze.py moves [PREFIX]   # offline: board by T-n
  python3 kalshi/econfreeze.py score [PREFIX]   # board Brier by days out

`freeze` appends one row per series to $DATA/econ/econ-freeze.jsonl for its
NEAREST open event (by the ticker's month, e.g. KXCPI-26OCT before 26NOV):
the event's close_time, days_out (close date minus today, UTC), and every
market's exact bid/ask strings. A second freeze of the same event on the
same day is skipped. A series whose listing fails is reported and the rest
still freeze. Exit 1 only if nothing was journaled.

`moves` prints, per event, one line per freeze: T-n, the date, and each
strike's board mid (kalshi.board_mid; '-' for an empty or wide book), then
the move from the first freeze to the newest on strikes priced at both,
then `# board median:` with each freeze's implied median (where the mids
cross 0.5, interpolated; '<'/'>' off the ladder). PREFIX is a series name (KXCPI: that series only, not KXCPICORE/KXCPIYOY)
or, with a dash, an event-ticker prefix (KXCPI-26OCT).

`score` reads each event's settled results from Kalshi and prints the
board's mean per-strike Brier for every freeze (priced strikes only), then
the mean by days out across events. Unsettled events print as pending. Each
settled event also gets `# EVENT settled V; board median miss (settled -
median): T-n M ±miss …` (an off-ladder median is shown, not scored). A label
expiration_value ('Above 0.2%') places each median below / in / above the
bracket the results imply instead.
"""

import datetime as dt
import json
import os
import pathlib
import sys

import kalshi

DATA = pathlib.Path(os.environ.get("KALSEER_DATA_DIR",
                                   pathlib.Path(__file__).parents[1] / "data"))
JOURNAL = DATA / "econ" / "econ-freeze.jsonl"

SERIES = ("KXPAYROLLS", "KXU3", "KXCPI", "KXCPICORE", "KXCPIYOY",
          "KXCPICOREYOY")


def _today() -> dt.date:
    return dt.datetime.now(dt.timezone.utc).date()


def open_events(series: str) -> list[str]:
    body = kalshi._get("/events", series_ticker=series, status="open")
    return [e["event_ticker"] for e in body.get("events", [])]


def _month(event: str) -> dt.date:
    return dt.datetime.strptime(event.rsplit("-", 1)[-1], "%y%b").date()


def nearest(events: list[str]) -> str | None:
    dated = []
    for e in events:
        try:
            dated.append((_month(e), e))
        except ValueError:
            continue
    return min(dated)[1] if dated else None


def _strike(ticker: str) -> str:
    """SERIES-MONTH-STRIKE; a negative strike has its own dash (T-25000)."""
    return ticker.split("-", 2)[-1]


def read() -> list[dict]:
    if not JOURNAL.exists():
        return []
    return [json.loads(l) for l in JOURNAL.read_text().splitlines()
            if l.strip()]


def freeze() -> int:
    """Append a row per series' nearest event; returns rows journaled."""
    today = _today()
    seen = {(r["event"], r["date"]) for r in read()}
    out = []
    for series in SERIES:
        try:
            event = nearest(open_events(series))
            if event is None or (event, today.isoformat()) in seen:
                continue
            markets = kalshi.get_event(event).get("markets") or []
        except Exception as e:
            print(f"econfreeze: {series}: {e}", file=sys.stderr)
            continue
        if not markets:
            continue
        close = max(m.get("close_time") or "" for m in markets) or None
        days_out = None
        if close:
            days_out = (dt.date.fromisoformat(close[:10]) - today).days
        out.append({
            "event": event, "date": today.isoformat(),
            "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(
                timespec="seconds"),
            "close_time": close, "days_out": days_out,
            "markets": [{"ticker": m.get("ticker"),
                         "floor": m.get("floor_strike"),
                         "yes_bid": m.get("yes_bid_dollars"),
                         "yes_ask": m.get("yes_ask_dollars")}
                        for m in markets]})
        side, value = median(out[-1])
        text = "-" if value is None else side + _num(value, _whole(out[-1:]))
        print(f"  {event} T-{days_out} ({len(markets)} strikes)  median {text}")
    if out:
        JOURNAL.parent.mkdir(parents=True, exist_ok=True)
        with JOURNAL.open("a") as f:
            f.writelines(json.dumps(r) + "\n" for r in out)
    return len(out)


def _mids(row: dict) -> dict[str, float | None]:
    return {_strike(m["ticker"]): kalshi.board_mid(m.get("yes_bid"),
                                                   m.get("yes_ask"))
            for m in row["markets"]}


def median(row: dict) -> tuple[str, float | None]:
    """The board's implied median: where the 'greater' survival mids cross
    0.5, linear between the two priced floors that bracket it. ('<', f) or
    ('>', f) when the crossing is off the ladder; ('-', None) unpriced."""
    pts = sorted((m["floor"], p) for m, p in
                 zip(row["markets"], _mids(row).values())
                 if p is not None and m.get("floor") is not None)
    if not pts:
        return "-", None
    if pts[0][1] < 0.5:
        return "<", pts[0][0]
    for (a, pa), (b, pb) in zip(pts, pts[1:]):
        if pa >= 0.5 > pb:
            return "", a + (b - a) * (pa - 0.5) / (pa - pb)
    return ">", pts[-1][0]


def _whole(rs: list[dict]) -> bool:
    return any(abs(m.get("floor") or 0) >= 100
               for r in rs for m in r["markets"])


def _num(value: float, whole: bool, sign: str = "") -> str:
    return f"{value:{sign}.0f}" if whole else f"{value:{sign}.3f}"


def median_line(rs: list[dict]) -> str:
    """'# board median: T-n M  …' for an event's freezes (brief 11/7: the
    NFP pre-reg is the board's T-1 median from November)."""
    whole = _whole(rs)
    cells = []
    for r in rs:
        side, value = median(r)
        text = "-" if value is None else side + _num(value, whole)
        cells.append(f"T-{r['days_out']} {text}")
    return "# board median: " + "  ".join(cells)


def miss_line(event: str, rs: list[dict], markets: list[dict]) -> str:
    """'# EVENT settled V; board median miss …' once Kalshi settles. The
    expiration_value comes as '165000', '4.1%' or a label ('Above 0.2%',
    KXCPICORE-26SEP); a label is placed by the bracket the results imply,
    (highest YES floor, lowest NO floor]."""
    whole = _whole(rs)
    raw = next((m.get("expiration_value") for m in markets
                if m.get("expiration_value") not in (None, "")), None)
    try:
        actual = float(str(raw).rstrip("%"))
    except ValueError:
        actual = None
    cells = []
    if actual is not None:
        for r in rs:
            side, value = median(r)
            text = "-" if value is None else side + _num(value, whole)
            if value is not None and not side:
                text += " " + _num(actual - value, whole, "+")
            cells.append(f"T-{r['days_out']} {text}")
        return (f"# {event} settled {str(raw).rstrip('%')}; board median "
                "miss (settled - median): " + "  ".join(cells))
    yes = [m["floor_strike"] for m in markets if m.get("result") == "yes"
           and m.get("floor_strike") is not None]
    no = [m["floor_strike"] for m in markets if m.get("result") == "no"
          and m.get("floor_strike") is not None]
    lo, hi = max(yes, default=None), min(no, default=None)
    for r in rs:
        side, value = median(r)
        if value is None:
            cells.append(f"T-{r['days_out']} -")
            continue
        # '<f' means the median is under f, '>f' over it
        if side in ("", "<") and lo is not None and value <= lo:
            where = "below"
        elif side in ("", ">") and hi is not None and value >= hi and (
                side or value > hi):
            where = "above"
        else:
            where = "in" if not side else "?"
        cells.append(f"T-{r['days_out']} {side}{_num(value, whole)} {where}")
    bracket = (f"({'-inf' if lo is None else _num(lo, whole)}, "
               f"{'inf' if hi is None else _num(hi, whole)}]")
    return (f"# {event} settled {raw!r} (in {bracket}); board median vs "
            "that bracket: " + "  ".join(cells))


def _matches(event: str, prefix: str) -> bool:
    """A bare series name is that series only: KXCPI is a text prefix of
    KXCPICORE/KXCPIYOY/KXCPICOREYOY (brief 11/6 read the wrong board). With a
    dash (KXCPI-26OCT, KXCPI-26) it is an event-ticker prefix."""
    if "-" in prefix:
        return event.startswith(prefix)
    return event.split("-", 1)[0] == prefix


def _by_event(prefix: str | None) -> dict[str, list[dict]]:
    out = {}
    for r in read():
        if prefix and not _matches(r["event"], prefix):
            continue
        out.setdefault(r["event"], []).append(r)
    return out


def _none(prefix: str | None) -> str:
    return f"# no freezes in {JOURNAL}" + (f" for {prefix}" if prefix else "")


def moves(prefix: str | None = None):
    events = _by_event(prefix)
    if not events:
        print(_none(prefix))
        return
    for event, rs in events.items():
        print(f"# {event} closes {rs[-1]['close_time']}")
        for r in rs:
            cells = [f"{k} {'-' if v is None else f'{v:.2f}'}"
                     for k, v in _mids(r).items()]
            print(f"T-{r['days_out']} {r['date']}  " + "  ".join(cells))
        if len(rs) > 1:
            first, last = _mids(rs[0]), _mids(rs[-1])
            delta = [f"{k} {last[k] - v:+.2f}" for k, v in first.items()
                     if v is not None and last.get(k) is not None]
            print(f"# T-{rs[0]['days_out']} -> T-{rs[-1]['days_out']}: "
                  + "  ".join(delta))
        print(median_line(rs))


def score(prefix: str | None = None):
    events = _by_event(prefix)
    if not events:
        print(_none(prefix))
        return
    by_out = {}
    for event, rs in events.items():
        settled = kalshi.get_event(event).get("markets") or []
        result = {_strike(m.get("ticker") or ""): m.get("result")
                  for m in settled}
        if not any(v in ("yes", "no") for v in result.values()):
            print(f"{event}  pending ({len(rs)} freeze(s), "
                  f"T-{rs[0]['days_out']}..T-{rs[-1]['days_out']})")
            continue
        for r in rs:
            pairs = [(p, result.get(k) == "yes") for k, p in _mids(r).items()
                     if p is not None and result.get(k) in ("yes", "no")]
            if not pairs:
                continue
            brier = sum((p - y) ** 2 for p, y in pairs) / len(pairs)
            by_out.setdefault(r["days_out"], []).append(brier)
            print(f"{event}  T-{r['days_out']}  BOARD B {brier:.4f} "
                  f"({len(pairs)} strikes)")
        print(miss_line(event, rs, settled))
    for k in sorted(by_out, key=lambda x: (x is None, -(x or 0))):
        v = by_out[k]
        print(f"# T-{k}: n={len(v)} mean B {sum(v) / len(v):.4f}")


def main(argv: list[str]):
    if argv[:1] == ["freeze"] and len(argv) == 1:
        n = freeze()
        print(f"econfreeze: {n} board(s) frozen")
        if not n:
            sys.exit(1)
        return
    if argv[:1] in (["moves"], ["score"]) and len(argv) <= 2:
        (moves if argv[0] == "moves" else score)(argv[1] if argv[1:] else None)
        return
    sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
