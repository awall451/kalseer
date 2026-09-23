"""Kalshi public API client + fee math. Stdlib only, no auth (read-only endpoints).

Also a small CLI for the judgment step, so precise board/rules/settlement
reads don't need a hand-written fetch script every run:

  python3 kalshi/kalshi.py market TICKER [TICKER ...]   # full detail + rules
  python3 kalshi/kalshi.py event EVENT_TICKER           # board of all strikes
  python3 kalshi/kalshi.py series SERIES_TICKER [STATUS] # markets in a series
                                                         # (STATUS default: open)

Prices and settlement values print as the API's exact strings — settlement
sources are display-precision hazards, never round them through float.
"""

import json
import math
import sys
import time
import urllib.parse
import urllib.request

BASE = "https://api.elections.kalshi.com/trade-api/v2"


def _get(path: str, tries: int = 4, **params) -> dict:
    qs = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    url = f"{BASE}{path}" + (f"?{qs}" if qs else "")
    req = urllib.request.Request(url, headers={"User-Agent": "paper-research/0.1"})
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except Exception:
            if attempt == tries - 1:
                raise
            time.sleep(2 ** attempt)


def iter_markets(status: str = "open", max_pages: int = 200,
                 min_close_ts: int | None = None, max_close_ts: int | None = None):
    """Yield all markets with the given status, paginating."""
    cursor = None
    for _ in range(max_pages):
        d = _get("/markets", limit=1000, status=status, cursor=cursor,
                 min_close_ts=min_close_ts, max_close_ts=max_close_ts)
        yield from d.get("markets", [])
        cursor = d.get("cursor")
        if not cursor:
            return


def get_market(ticker: str, tries: int = 4) -> dict:
    return _get(f"/markets/{ticker}", tries=tries)["market"]


def get_event(event_ticker: str) -> dict:
    return _get(f"/events/{event_ticker}", with_nested_markets=True)["event"]


def get_series(series_ticker: str) -> dict:
    return _get(f"/series/{series_ticker}")["series"]


def get_orderbook(ticker: str, depth: int = 8) -> dict:
    return _get(f"/markets/{ticker}/orderbook", depth=depth)["orderbook"]


def get_markets(**params) -> list[dict]:
    """One page of /markets filtered by e.g. series_ticker=, status=."""
    return _get("/markets", limit=1000, **params).get("markets", [])


def taker_fee(price: float, contracts: int = 1, rate: float = 0.07) -> float:
    """Kalshi taker fee in dollars: ceil-to-cent of rate * C * P * (1-P).

    General rate is 0.07; some index series are lower. We use 0.07 everywhere
    (conservative for paper-trading purposes).
    """
    raw = rate * contracts * price * (1.0 - price)
    # round before ceil so float epsilon (1.7500000000002) doesn't overcharge
    return math.ceil(round(raw * 100, 6)) / 100


def round_trip_cost(price: float) -> float:
    """Fee per contract if we take liquidity on entry and hold to settlement.

    Settlement itself has no fee; exiting early would incur a second taker fee.
    We model entry fee only (hold-to-settle) — matches the paper strategy.
    """
    return taker_fee(price, 1)


# --- CLI ---------------------------------------------------------------------

def _s(m, key) -> str:
    """Field as the API's exact string; '-' when absent."""
    v = m.get(key)
    return "-" if v in (None, "") else str(v)


def fmt_market(m: dict) -> str:
    """Full detail for one market, rules included (read the settlement date
    in the rules FIRST — it is not always the ticker's date)."""
    sub = m.get("yes_sub_title") or m.get("subtitle") or ""
    title = " | ".join(x for x in (m.get("title"), sub) if x)
    lines = [f"{_s(m, 'ticker')}  [{_s(m, 'status')}]"]
    if title:
        lines.append(f"  {title}")
    lines.append(f"  yes bid/ask {_s(m, 'yes_bid_dollars')}/{_s(m, 'yes_ask_dollars')}"
                 f"  vol24h {_s(m, 'volume_24h_fp')}  oi {_s(m, 'open_interest_fp')}")
    lines.append(f"  close_time {_s(m, 'close_time')}")
    if m.get("result"):
        lines.append(f"  result {m['result']}  "
                     f"expiration_value {_s(m, 'expiration_value')}")
    rules = (m.get("rules_primary") or "").strip()
    if rules:
        lines.append(f"  rules: {rules}")
    return "\n".join(lines)


def fmt_board_row(m: dict) -> str:
    """One board line: exact price strings, result once settled."""
    sub = m.get("yes_sub_title") or m.get("subtitle") or ""
    outcome = m.get("result") or _s(m, "status")
    return (f"{_s(m, 'ticker'):<42} {_s(m, 'yes_bid_dollars'):>6}"
            f" {_s(m, 'yes_ask_dollars'):>6} {_s(m, 'volume_24h_fp'):>10}"
            f"  {outcome:<10} {sub}")


def main(argv: list[str]):
    if not argv or argv[0] not in ("market", "event", "series"):
        sys.exit(__doc__)
    cmd, args = argv[0], argv[1:]
    if not args:
        sys.exit(__doc__)
    if cmd == "market":
        for t in args:
            print(fmt_market(get_market(t)))
    elif cmd == "event":
        ev = get_event(args[0])
        print(f"{ev.get('event_ticker', args[0])}  {ev.get('title', '')}"
              f"  [{ev.get('category', '')}]")
        for m in ev.get("markets", []):
            print(fmt_board_row(m))
    elif cmd == "series":
        status = args[1] if len(args) > 1 else "open"
        for m in get_markets(series_ticker=args[0], status=status):
            print(fmt_board_row(m))


if __name__ == "__main__":
    main(sys.argv[1:])
