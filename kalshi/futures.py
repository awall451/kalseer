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
settlement; the footer's last-trade time tells which. A '# WARNING' line
means the last-trade quote contradicts the bars (a different price for the
same day, a quote older than the newest bar, or a price equal to an older
day's close, as on 10/17); neither number is verified. A row tagged
'= <day> close' repeats a close from the last 10 sessions to the last digit
(10/16 ULSD 4.7232 == 10/12, brief 10/18) and warns when it is the newest
bar — a recycled number, unverified until a quoted settle. The front month rolls
mid-month, so a jump across a roll is a contract switch, not a move.

For rbob/ulsd, `closes` also reads the explicit front and next months
(e.g. HOX26.NYM / HOZ26.NYM; RB/HO expire on the last weekday of the month
before delivery, holidays not modelled) and tags each bar `month X26` with
the contract whose close it equals (`month ?` = neither). Brief 10/24: the
10/23 bar was Nov's and the last trade Dec's. A '# WARNING: the bars switch
contract month' line means the continuous series hopped months inside the
window. `archive` also journals both months as <alias>-<code> (ulsd-Z26),
readable with `first ulsd-Z26`; a contract failure never fails the step.
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

# Explicit contract months behind the continuous RB=F/HO=F (brief 10/24: the
# 10/23 bars and last trade came from different months around the Nov roll)
ROOTS = {"rbob": "RB", "ulsd": "HO", "ho": "HO"}
MONTHS = "FGHJKMNQUVXZ"


def _expiry(year: int, month: int) -> datetime.date:
    """Last weekday of the month before delivery (NYMEX RB/HO; exchange
    holidays are not modelled)."""
    day = datetime.date(year, month, 1) - datetime.timedelta(days=1)
    while day.weekday() >= 5:
        day -= datetime.timedelta(days=1)
    return day


def _add_month(year: int, month: int, n: int = 1) -> tuple[int, int]:
    i = year * 12 + month - 1 + n
    return i // 12, i % 12 + 1


def front_month(day: datetime.date) -> tuple[int, int]:
    """(year, delivery month) of the contract that is front on `day`."""
    ym = _add_month(day.year, day.month)
    return ym if day <= _expiry(*ym) else _add_month(*ym)


def _code(year: int, month: int) -> str:
    return f"{MONTHS[month - 1]}{year % 100:02d}"


def contract(name: str, year: int, month: int) -> str:
    return f"{ROOTS[name]}{_code(year, month)}.NYM"


def _symbol(name: str) -> str | None:
    """Yahoo symbol of a journal name: an alias or '<alias>-<month code>'."""
    if name in ALIASES:
        return ALIASES[name]
    alias, _, code = name.partition("-")
    if alias in ROOTS and len(code) == 3 and code[0] in MONTHS \
            and code[1:].isdigit():
        return f"{ROOTS[alias]}{code}.NYM"
    return None


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
    meta, bars = _series(_fetch(_symbol(name)))
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
          f"({name} = {_symbol(name)}, settled days only)")


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
        # the front and next months, contract-consistent across the roll;
        # extras, so a failure here never fails the step
        front = front_month(datetime.datetime.fromtimestamp(
            _now(), datetime.UTC).date())
        for name in ARCHIVE:
            for ym in (front, _add_month(*front)):
                month = f"{name}-{_code(*ym)}"
                label = f"{month} ({contract(name, *ym)})"
                try:
                    new, revised = archive(month)
                except (Exception, SystemExit) as e:
                    print(f"futures archive: {label}: failed: {e}")
                    continue
                print(f"futures archive: {label}: {new} new days, "
                      f"{revised} revised")
        if len(failed) == len(ARCHIVE):
            sys.exit(1)
        return
    if argv[:1] == ["first"] and len(argv) >= 2 and _symbol(argv[1]):
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


REPEAT_WINDOW = 10  # sessions back a digit-for-digit repeat is suspicious


def _repeats(bars: list[tuple[str, float]], i: int) -> str | None:
    """The older day within REPEAT_WINDOW sessions whose close bar i repeats
    to the last digit (10/16 ULSD 4.7232 == 10/12, brief 10/18)."""
    close = bars[i][1]
    for day, older in bars[i + 1:i + 1 + REPEAT_WINDOW]:
        if abs(close - older) < 0.00005:
            return day
    return None


def _months(name: str, shown: list[tuple[str, float]]) -> dict | None:
    """{code: (symbol, expiry, meta, {day: close})} for the front and next
    months of every shown day; None if no contract month could be read."""
    yms = []
    for day, _ in reversed(shown):
        front = front_month(datetime.date.fromisoformat(day))
        for ym in (front, _add_month(*front)):
            if ym not in yms:
                yms.append(ym)
    months = {}
    for ym in sorted(yms):
        sym = contract(name, *ym)
        try:
            meta, cbars = _series(_fetch(sym))
        except (Exception, SystemExit):
            continue
        months[_code(*ym)] = (sym, _expiry(*ym), meta, dict(cbars))
    return months or None


def _print_months(name: str, meta: dict, months: dict | None):
    if not months:
        print(f"# {name}: contract months unavailable; bars untagged")
        return
    for code, (sym, expiry, cmeta, by_day) in months.items():
        if by_day:
            newest = max(by_day)
            print(f"# {sym} (expires {expiry}): latest {newest} = "
                  f"{by_day[newest]:.4f}")
    if "regularMarketPrice" in meta:
        price = float(meta["regularMarketPrice"])
        owners = [(code, sym) for code, (sym, _, cmeta, _) in months.items()
                  if abs(float(cmeta.get("regularMarketPrice", -1)) - price)
                  < 0.00005]
        if len(owners) == 1:
            code, sym = owners[0]
            print(f"# last trade {price:.4f} is the {code} contract's ({sym})")


def _switch(shown: list[tuple[str, float]], tags: dict) -> str | None:
    """A warning when consecutive bars come from different contract months."""
    seq = [(day, tags[day][0]) for day, _ in shown if len(tags.get(day, [])) == 1]
    odd = [f"{day} {code}" for (day, code), (_, prev) in zip(seq, seq[1:])
           if code != prev]
    if not odd:
        return None
    return (f"# WARNING: the bars switch contract month ({', '.join(odd)} vs "
            "the next older bar) -> a jump across a switch is a contract "
            "change, not a move; read the month's own row above")


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
    shown = bars[:days]
    months = _months(name, shown) if name in ROOTS else None
    tags = {}
    for i, (day, close) in enumerate(shown):
        parts = [day, f"{close:.4f}"]
        if i + 1 < len(bars):
            parts.append(f"d/d {close - bars[i + 1][1]:+.4f}")
        if i == 0:
            parts.append("latest")
        repeated = _repeats(bars, i)
        if repeated:
            parts.append(f"= {repeated} close")
        if months:
            tags[day] = [code for code, (_, _, _, by_day) in months.items()
                         if abs(by_day.get(day, -1) - close) < 0.00005]
            parts.append(f"month {'/'.join(tags[day]) or '?'}")
        print("  ".join(parts))
    if name in ROOTS:
        _print_months(name, meta, months)
    label = f"{name} = {symbol}" if name in ALIASES else symbol
    footer = [f"# {label}: {len(bars)} daily bars, "
              f"latest {bars[0][0]} = {bars[0][1]:.4f}", _last_trade(meta)]
    print("; ".join(p for p in footer if p))
    warning = _conflict(meta, bars)
    if warning:
        print(warning)
    switch = _switch(shown, tags)
    if switch:
        print(switch)
    repeated = _repeats(bars, 0)
    if repeated:
        print(f"# WARNING: the {bars[0][0]} bar {bars[0][1]:.4f} repeats the "
              f"{repeated} close to the last digit (a stale or recycled bar?) "
              f"-> treat {bars[0][0]} as unverified until a quoted settle")


if __name__ == "__main__":
    main(sys.argv[1:])
