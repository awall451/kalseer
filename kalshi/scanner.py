"""Scan open Kalshi markets for research candidates.

Filters out parlays and dead markets, then ranks what's left so Claude can
research the top of the list for mispricings. Writes a dated JSON snapshot to
data/ and prints a human-readable table.

Usage: python3 scanner.py [--days N] [--min-volume V] [--top K]
"""

import argparse
import datetime as dt
import json
import os
import pathlib
import sys

import kalshi

DATA = pathlib.Path(os.environ.get("KALSEER_DATA_DIR",
                                   pathlib.Path(__file__).parents[1] / "data"))

# Categories where careful research plausibly beats casual money. Sports get
# heavy sharp attention; parlays are pure noise.
PREFERRED_CATEGORIES = {
    "Climate and Weather",
    "Economics",
    "Financials",
    "Politics",
    "Elections",
    "Science and Technology",
    "Companies",
    "Health",
    "World",
    "Entertainment",
}


def fnum(m, key):
    try:
        return float(m.get(key) or 0)
    except (TypeError, ValueError):
        return 0.0


def scan(days: int, min_volume: float):
    now = dt.datetime.now(dt.timezone.utc)
    horizon = now + dt.timedelta(days=days)
    events = {}  # event_ticker -> category (lazy cache)
    rows = []
    n_seen = 0
    for m in kalshi.iter_markets("open", max_pages=500,
                                 min_close_ts=int(now.timestamp()),
                                 max_close_ts=int(horizon.timestamp())):
        n_seen += 1
        if m.get("mve_collection_ticker"):  # multivariate parlay
            continue
        close = dt.datetime.fromisoformat(m["close_time"].replace("Z", "+00:00"))
        if close > horizon or close < now:
            continue
        vol24 = fnum(m, "volume_24h_fp")
        if vol24 < min_volume:
            continue
        yes_bid, yes_ask = fnum(m, "yes_bid_dollars"), fnum(m, "yes_ask_dollars")
        if yes_ask <= 0 or yes_ask >= 1:
            continue
        spread = yes_ask - yes_bid
        mid = (yes_bid + yes_ask) / 2
        rows.append({
            "ticker": m["ticker"],
            "event_ticker": m.get("event_ticker", ""),
            "title": m.get("title", ""),
            "subtitle": m.get("yes_sub_title") or m.get("subtitle") or "",
            "close_time": m["close_time"],
            "hours_to_close": round((close - now).total_seconds() / 3600, 1),
            "yes_bid": yes_bid,
            "yes_ask": yes_ask,
            "mid": round(mid, 3),
            "spread": round(spread, 3),
            "volume_24h": vol24,
            "open_interest": fnum(m, "open_interest_fp"),
            "entry_fee_at_mid": kalshi.round_trip_cost(mid or 0.5),
            "rules": (m.get("rules_primary") or "")[:400],
        })
    # attach categories via events (one call per unique event, capped)
    uniq = {r["event_ticker"] for r in rows}
    for et in list(uniq)[:300]:
        try:
            events[et] = kalshi.get_event(et).get("category", "")
        except Exception:
            events[et] = ""
    for r in rows:
        r["category"] = events.get(r["event_ticker"], "")
    return rows, n_seen


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=10)
    ap.add_argument("--min-volume", type=float, default=500)
    ap.add_argument("--top", type=int, default=40)
    ap.add_argument("--all-categories", action="store_true")
    args = ap.parse_args()

    rows, n_seen = scan(args.days, args.min_volume)
    if not args.all_categories:
        rows = [r for r in rows if r["category"] in PREFERRED_CATEGORIES]
    # rank: liquid, closing soonish, price away from extremes (room to be wrong)
    rows.sort(key=lambda r: -r["volume_24h"])
    rows = rows[: args.top]

    DATA.mkdir(parents=True, exist_ok=True)
    stamp = dt.date.today().isoformat()
    out = DATA / f"candidates-{stamp}.json"
    out.write_text(json.dumps(rows, indent=1))

    print(f"scanned {n_seen} open markets -> {len(rows)} candidates "
          f"(<= {args.days}d to close, >= ${args.min_volume:.0f} 24h vol)")
    print(f"wrote {out}\n")
    fmt = "{:<38} {:>5} {:>5} {:>6} {:>9} {:>7}  {}"
    print(fmt.format("TICKER", "BID", "ASK", "SPRD", "VOL24H", "HRS", "TITLE"))
    for r in rows:
        print(fmt.format(
            r["ticker"][:38], f"{r['yes_bid']:.2f}", f"{r['yes_ask']:.2f}",
            f"{r['spread']:.2f}", f"{r['volume_24h']:.0f}",
            f"{r['hours_to_close']:.0f}",
            (r["title"] + " | " + r["subtitle"])[:60],
        ))


if __name__ == "__main__":
    sys.exit(main())
