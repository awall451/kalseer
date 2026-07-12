"""Kalshi public API client + fee math. Stdlib only, no auth (read-only endpoints)."""

import json
import math
import time
import urllib.parse
import urllib.request

BASE = "https://api.elections.kalshi.com/trade-api/v2"


def _get(path: str, **params) -> dict:
    qs = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    url = f"{BASE}{path}" + (f"?{qs}" if qs else "")
    req = urllib.request.Request(url, headers={"User-Agent": "paper-research/0.1"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except Exception:
            if attempt == 3:
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


def get_market(ticker: str) -> dict:
    return _get(f"/markets/{ticker}")["market"]


def get_event(event_ticker: str) -> dict:
    return _get(f"/events/{event_ticker}", with_nested_markets=True)["event"]


def get_series(series_ticker: str) -> dict:
    return _get(f"/series/{series_ticker}")["series"]


def get_orderbook(ticker: str, depth: int = 8) -> dict:
    return _get(f"/markets/{ticker}/orderbook", depth=depth)["orderbook"]


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
