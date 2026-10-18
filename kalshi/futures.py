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

Newest first, one row per trading day with the day-over-day change. Rows are
dated by the exchange's trading day. 'latest' marks the newest bar, and
before the ~14:30 ET settle that bar's close is the live price, not a
settlement; the footer's last-trade time tells which. A '# WARNING' line
means the last-trade quote contradicts the bars (a different price for the
same day, a quote older than the newest bar, or a price equal to an older
day's close, as on 10/17); neither number is verified. The front month rolls
mid-month, so a jump across a roll is a contract switch, not a move.
Yahoo's close is its own feed, not the CME settlement file: cross-check one
day against a quoted settle (FreightWaves: ULSD 4.9344 on 10/13) before
leaning on the levels. An error body or an unexpected shape is a loud exit.
"""

import datetime
import json
import sys
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


def _conflict(meta: dict, bars: list[tuple[str, float]]) -> str | None:
    """A warning when the last-trade quote contradicts the daily bars."""
    if "regularMarketTime" not in meta or "regularMarketPrice" not in meta:
        return None
    price = float(meta["regularMarketPrice"])
    # same trading-day rule as the bars: the evening session counts forward
    day = datetime.datetime.fromtimestamp(
        meta["regularMarketTime"] + int(meta.get("gmtoffset", 0)) + 6 * 3600,
        datetime.UTC).date().isoformat()
    newest, close = bars[0]
    if day < newest:
        return (f"# WARNING: last trade {price:.4f} is dated {day}, older "
                f"than the newest bar {newest} = {close:.4f}; the quote is "
                "stale, cross-check a quoted settle")
    if day > newest or abs(price - close) < 0.00005:
        return None
    msg = (f"# WARNING: last trade {price:.4f} disagrees with the {newest} "
           f"bar {close:.4f}")
    older = [d for d, c in bars[1:] if abs(price - c) < 0.00005]
    if older:
        msg += f"; it equals the {older[0]} close (a stale quote?)"
    return msg + f" -> treat {newest} as unverified until a quoted settle"


def main(argv: list[str]):
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
    warning = _conflict(meta, bars)
    if warning:
        print(warning)


if __name__ == "__main__":
    main(sys.argv[1:])
