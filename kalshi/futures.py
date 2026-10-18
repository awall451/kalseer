"""Dated daily futures closes for the judgment step. Stdlib only, no key.

The gas and diesel boards (KXAAAGASD/W/M, KXDIESELW) reprice on wholesale
moves the retail print only catches up to days later. WebSearch for dated
RBOB/ULSD settlements came back thin (10/12, 10/13) and eia.gov's daily
spot lags; freightwaves.com (item #23) quotes ULSD only in articles. Yahoo's
v8 chart endpoint serves dated daily bars for the NYMEX front months as
public JSON. This prints them so a board move can be checked against the
futures path instead of recorded as "driver unverified".

  python3 kalshi/futures.py closes rbob           # RB=F, RBOB gasoline $/gal
  python3 kalshi/futures.py closes ulsd           # HO=F, NY Harbor ULSD $/gal
  python3 kalshi/futures.py closes wti            # CL=F, WTI crude $/bbl
  python3 kalshi/futures.py closes brent          # BZ=F, Brent crude $/bbl
  python3 kalshi/futures.py closes RBX26.NYM --days 20   # one contract month
  python3 kalshi/futures.py archive               # pipeline step: journal
  python3 kalshi/futures.py first ulsd [--since YYYY-MM-DD]   # offline read

`archive` journals every SETTLED day (dated before the exchange's today) of
rbob and ulsd to $DATA/futures/<alias>.jsonl the first time it is seen, and
again with revised_from whenever Yahoo later serves a different close for
that day. `first` reads it back: first-seen vs latest close per day, so
"re-read and cross-check" (10/17) is a lookup, not a memory.

Newest first, one row per trading day with the day-over-day change. Rows are
dated by the exchange's trading day. 'latest' marks the newest bar, and
before the ~14:30 ET settle that bar's close is the live price, not a
settlement; the footer's last-trade time tells which. The front month rolls
mid-month, so a jump across a roll is a contract switch, not a move.
Yahoo's close is its own feed, not the CME settlement file: cross-check one
day against a quoted settle (FreightWaves: ULSD 4.9344 on 10/13) before
leaning on the levels. An error body or an unexpected shape is a loud exit.
"""

import datetime
import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HOSTS = ("query1.finance.yahoo.com", "query2.finance.yahoo.com")

ALIASES = {
    "rbob": "RB=F",   # NYMEX RBOB gasoline, front month, $/gal
    "ulsd": "HO=F",   # NYMEX NY Harbor ULSD (heating oil), front month, $/gal
    "ho": "HO=F",
    "wti": "CL=F",    # NYMEX WTI crude, front month, $/bbl
    "brent": "BZ=F",  # ICE Brent crude (NYMEX look-alike), front month, $/bbl
}

DATA = pathlib.Path(os.environ.get("KALSEER_DATA_DIR",
                                   pathlib.Path(__file__).parents[1] / "data"))
ARCHIVE = ("rbob", "ulsd")  # the gas and diesel boards' wholesale drivers


def _fetch(symbol: str) -> object:
    path = (f"/v8/finance/chart/{urllib.parse.quote(symbol)}"
            "?range=3mo&interval=1d")
    for i, host in enumerate(HOSTS):
        req = urllib.request.Request(
            f"https://{host}{path}",
            headers={"User-Agent": "Mozilla/5.0 (paper-research/0.1)"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError:
            if i == len(HOSTS) - 1:
                raise


def _fail(msg: str):
    print(f"futures: {msg}", file=sys.stderr)
    sys.exit(2)


def _now() -> float:
    return time.time()


def _journal(name: str) -> pathlib.Path:
    return DATA / "futures" / f"{name}.jsonl"


def _read(name: str) -> list[dict]:
    path = _journal(name)
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def archive(name: str) -> tuple[int, int]:
    """Journal new settled days and revisions; returns (new, revised)."""
    meta, bars = _series(_fetch(ALIASES[name]))
    today = datetime.datetime.fromtimestamp(
        _now() + int(meta.get("gmtoffset", 0)), datetime.UTC).date().isoformat()
    latest = {r["date"]: r["close"] for r in _read(name)}
    seen_at = datetime.datetime.fromtimestamp(_now(), datetime.UTC).isoformat(
        timespec="seconds")
    out, new, revised = [], 0, 0
    for day, close in sorted(bars):
        if day >= today:
            continue  # live until the ~14:30 ET settle
        close = round(close, 4)
        if day not in latest:
            out.append({"date": day, "close": close, "seen_at": seen_at})
            new += 1
        elif abs(latest[day] - close) >= 0.00005:
            out.append({"date": day, "close": close, "seen_at": seen_at,
                        "revised_from": latest[day]})
            revised += 1
    if out:
        path = _journal(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as f:
            f.writelines(json.dumps(r) + "\n" for r in out)
    return new, revised


def print_first(name: str, since: str | None):
    rows = _read(name)
    if not rows:
        print(f"# no journal for {name} at {_journal(name)}")
        return
    first, latest = {}, {}
    for r in rows:
        first.setdefault(r["date"], r["close"])
        latest[r["date"]] = r["close"]
    days = sorted((d for d in first if not since or d >= since), reverse=True)
    for d in days:
        line = f"{d}  first {first[d]:.4f}  latest {latest[d]:.4f}"
        if abs(latest[d] - first[d]) >= 0.00005:
            line += f"  ({latest[d] - first[d]:+.4f})"
        print(line)
    revised = sum(abs(latest[d] - first[d]) >= 0.00005 for d in days)
    print(f"# {revised} of {len(days)} days revised since first seen "
          f"({name} = {ALIASES[name]}, settled days only)")


def _main_archive(argv: list[str]):
    if argv[:1] == ["archive"] and len(argv) == 1:
        failed = []
        for name in ARCHIVE:
            try:
                new, revised = archive(name)
            except (Exception, SystemExit) as e:
                print(f"futures archive: {name}: failed: {e}")
                failed.append(name)
                continue
            print(f"futures archive: {name}: {new} new days, {revised} revised")
        if len(failed) == len(ARCHIVE):
            sys.exit(1)
        return
    if argv[:1] == ["first"] and len(argv) >= 2 and argv[1] in ALIASES:
        since = None
        if argv[2:3] == ["--since"] and len(argv) == 4:
            since = argv[3]
        elif argv[2:]:
            sys.exit(__doc__)
        print_first(argv[1], since)
        return
    sys.exit(__doc__)


def _series(body: object) -> tuple[dict, list[tuple[str, float]]]:
    """(meta, [(trading day, close)]) newest first; null closes dropped."""
    try:
        chart = body["chart"]
        if chart.get("error"):
            err = chart["error"]
            _fail(f"{err.get('code')}: {err.get('description')}")
        (result,) = chart["result"]
        meta = result["meta"]
        stamps = result["timestamp"]
        closes = result["indicators"]["quote"][0]["close"]
        offset = int(meta.get("gmtoffset", 0))
        assert len(stamps) == len(closes)
    except (KeyError, TypeError, ValueError, IndexError, AssertionError):
        _fail(f"unexpected response shape: {str(body)[:200]}")
    bars = []
    for stamp, close in zip(stamps, closes):
        if close is None:
            continue
        # +6h: a bar stamped at Globex open (18:00 the evening before) and
        # one stamped at local midnight both land on their trading day
        day = datetime.datetime.fromtimestamp(stamp + offset + 6 * 3600,
                                              datetime.UTC).date()
        bars.append((day.isoformat(), float(close)))
    return meta, sorted(bars, reverse=True)


def _last_trade(meta: dict) -> str | None:
    if "regularMarketTime" not in meta or "regularMarketPrice" not in meta:
        return None
    when = datetime.datetime.fromtimestamp(
        meta["regularMarketTime"] + int(meta.get("gmtoffset", 0)),
        datetime.UTC)
    tz = meta.get("exchangeTimezoneName", "exchange time")
    return (f"last trade {meta['regularMarketPrice']:.4f} at "
            f"{when:%Y-%m-%d %H:%M} {tz}")


def main(argv: list[str]):
    if argv[:1] in (["archive"], ["first"]):
        return _main_archive(argv)
    if argv[:1] != ["closes"] or len(argv) < 2 or argv[1].startswith("--"):
        sys.exit(__doc__)
    name, days, opts = argv[1], 15, argv[2:]
    while opts:
        if opts[:1] == ["--days"] and len(opts) > 1:
            days, opts = int(opts[1]), opts[2:]
        else:
            sys.exit(__doc__)
    symbol = ALIASES.get(name, name)
    meta, bars = _series(_fetch(symbol))
    if not bars:
        print(f"# no bars for {symbol}")
        return
    for i, (day, close) in enumerate(bars[:days]):
        parts = [day, f"{close:.4f}"]
        if i + 1 < len(bars):
            parts.append(f"d/d {close - bars[i + 1][1]:+.4f}")
        if i == 0:
            parts.append("latest")
        print("  ".join(parts))
    label = f"{name} = {symbol}" if name in ALIASES else symbol
    footer = [f"# {label}: {len(bars)} daily bars, "
              f"latest {bars[0][0]} = {bars[0][1]:.4f}", _last_trade(meta)]
    print("; ".join(p for p in footer if p))


if __name__ == "__main__":
    main(sys.argv[1:])
