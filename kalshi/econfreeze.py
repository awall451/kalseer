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
the move from the first freeze to the newest on strikes priced at both.

`score` reads each event's settled results from Kalshi and prints the
board's mean per-strike Brier for every freeze (priced strikes only), then
the mean by days out across events. Unsettled events print as pending.
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
        print(f"  {event} T-{days_out} ({len(markets)} strikes)")
    if out:
        JOURNAL.parent.mkdir(parents=True, exist_ok=True)
        with JOURNAL.open("a") as f:
            f.writelines(json.dumps(r) + "\n" for r in out)
    return len(out)


def _mids(row: dict) -> dict[str, float | None]:
    return {_strike(m["ticker"]): kalshi.board_mid(m.get("yes_bid"),
                                                   m.get("yes_ask"))
            for m in row["markets"]}


def _by_event(prefix: str | None) -> dict[str, list[dict]]:
    out = {}
    for r in read():
        if prefix and not r["event"].startswith(prefix):
            continue
        out.setdefault(r["event"], []).append(r)
    return out


def moves(prefix: str | None = None):
    events = _by_event(prefix)
    if not events:
        print(f"# no freezes in {JOURNAL}")
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


def score(prefix: str | None = None):
    events = _by_event(prefix)
    if not events:
        print(f"# no freezes in {JOURNAL}")
        return
    by_out = {}
    for event, rs in events.items():
        result = {_strike(m.get("ticker") or ""): m.get("result")
                  for m in kalshi.get_event(event).get("markets") or []}
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
