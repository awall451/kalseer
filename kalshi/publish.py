"""Publish ledger data to the dashboard's public data directory.

Reads the data dir (portfolio, closed trades, daily briefs) and writes the
JSON files the static SPA fetches at runtime into <data dir>/public/:

  public/manifest.json          list of brief dates (newest first)
  public/brief-YYYY-MM-DD.json  verbatim copies of each daily brief
  public/aggregates.json        equity curve, calibration, stat tiles

The web server maps <data dir>/public/ to the SPA's ./data/ URL path.
status.json is owned by bin/daily.sh, not this script.
"""

import json
import shutil
import datetime as dt

import kalshi
import paper

PUBLIC = paper.DATA / "public"
SERIES_CACHE = paper.DATA / "series-cache.json"
TITLE_CACHE = paper.DATA / "title-cache.json"


def slugify(title: str) -> str:
    import re
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", title.lower())).strip("-")


def series_slugs(tickers) -> dict:
    """Map series ticker -> URL slug (from series title), cached on disk.

    Feeds kalshi.com deep links: /markets/<series>/<slug>/<event>.
    """
    cache = {}
    if SERIES_CACHE.exists():
        cache = json.loads(SERIES_CACHE.read_text())
    for t in sorted({tk.split("-")[0] for tk in tickers if tk}):
        if t not in cache:
            try:
                cache[t] = slugify(kalshi.get_series(t).get("title", ""))
            except Exception:
                cache[t] = ""
    SERIES_CACHE.write_text(json.dumps(cache, indent=1))
    return cache


def title_map(tickers, hist) -> dict:
    """ticker -> human-readable market title, e.g. KXRT-ICE-25 ->
    "Ice Cream Man Rotten Tomatoes score?".

    A raw ticker means nothing at a glance, so every ticker the dashboard
    shows gets a title. Marks history already carries titles for anything
    we ever held; everything else (e.g. considered-but-passed tickers) is
    fetched once from the API — settled markets stay queryable — and
    cached on disk.
    """
    cache = {}
    if TITLE_CACHE.exists():
        cache = json.loads(TITLE_CACHE.read_text())
    titles = {}
    for t, ms in hist.items():
        for m in reversed(ms):
            if m.get("title"):
                titles[t] = m["title"]
                break
    # single attempt, no backoff: many considered-but-passed tickers are
    # long delisted and 404 — retrying each would stall the daily run
    for t in sorted({tk for tk in tickers if tk}):
        if titles.get(t):
            continue
        if cache.get(t):
            titles[t] = cache[t]
            continue
        if "*" in t or " " in t:  # research notes, not real tickers
            continue
        try:
            titles[t] = (kalshi.get_market(t, tries=1).get("title") or "").replace("*", "")
        except Exception as e:
            print(f"! title {t}: {e}")
    cache.update({t: v for t, v in titles.items() if v})
    TITLE_CACHE.write_text(json.dumps(cache, indent=1))
    return {t: v for t, v in titles.items() if v}


def load_closed():
    if not paper.CLOSED.exists():
        return []
    rows = [json.loads(l) for l in paper.CLOSED.read_text().splitlines() if l.strip()]
    rows.sort(key=lambda r: r.get("settled", ""))
    return rows


def _days(start: str, end: str):
    d = dt.date.fromisoformat(start)
    last = dt.date.fromisoformat(end)
    while d <= last:
        yield d.isoformat()
        d += dt.timedelta(days=1)


def equity_curve(closed, portfolio, hist, today=None):
    """One point per calendar day: cash + open positions marked to market.

    The old version plotted one point per settlement and valued open
    positions at cost. Both were wrong in the same direction — a settle
    backlog collapsed weeks of history into a single vertical cliff, and a
    book that had moved hundreds of dollars showed as a flat line. Here the
    x-axis is real time and open positions are worth what the market says.
    """
    opens = [dict(x, _open=True) for x in portfolio["positions"]]
    everything = opens + [dict(r, _open=False) for r in closed]
    if not everything:
        return []

    now = dt.datetime.now(dt.timezone.utc)
    today = today or now.date().isoformat()
    # the trailing point is "as of now" only when the curve really ends today
    last_t = (now.isoformat(timespec="seconds")
              if today == now.date().isoformat() else f"{today}T23:59:59+00:00")
    first = min(r["opened"][:10] for r in everything)
    marks = {t: {m["date"]: m["mark"] for m in ms} for t, ms in hist.items()}

    def value_on(pos, day):
        """Last mark at or before `day`, falling back to entry price."""
        seen = [d for d in marks.get(pos["ticker"], {}) if d <= day]
        px = marks[pos["ticker"]][max(seen)] if seen else pos["entry_price"]
        return px * pos["contracts"]

    points = [{"t": f"{first}T00:00:00+00:00", "equity": paper.STARTING_BANKROLL,
               "cash": paper.STARTING_BANKROLL, "unrealized": 0.0,
               "realized": 0.0, "open_n": 0, "events": []}]
    for day in _days(first, max(first, today)):
        cash = paper.STARTING_BANKROLL
        realized, held, events = 0.0, [], []
        for r in everything:
            if r["opened"][:10] > day:
                continue
            cash -= paper.position_cost(r)
            settled = None if r["_open"] else r.get("settled", "")[:10]
            if settled and settled <= day:
                cash += r["payout"]
                realized += r["pnl"]
                if settled == day:
                    events.append({"ticker": r["ticker"], "pnl": r["pnl"],
                                   "won": r["won"]})
            else:
                held.append(r)
        unrealized = sum(value_on(r, day) for r in held) - sum(
            paper.position_cost(r) for r in held)
        points.append({
            "t": last_t if day == today else f"{day}T23:59:59+00:00",
            "equity": round(cash + sum(value_on(r, day) for r in held), 2),
            "cash": round(cash, 2),
            "unrealized": round(unrealized, 2),
            "realized": round(realized, 2),
            "open_n": len(held),
            "events": events,
        })

    drift = points[-1]["cash"] - portfolio["bankroll"]
    if abs(drift) > 0.02:
        print(f"! equity curve cash drift ${drift:+.2f} vs portfolio bankroll "
              f"${portfolio['bankroll']:.2f} — ledger and curve disagree")
    return points


def wilson(wins: int, n: int, z: float = 1.96):
    """Wilson score interval — honest error bars at tiny n.

    A bucket with one settled trade reads 0% or 100%; without an interval
    the calibration chart looks like a catastrophe or a triumph when it is
    neither. At n=1 this spans roughly the whole axis, which is the point.
    """
    if not n:
        return 0.0, 1.0
    p = wins / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / denom
    return round(max(0.0, centre - half), 3), round(min(1.0, centre + half), 3)


def calibration(closed):
    buckets = {}
    for r in closed:
        b = min(int(r["fair_value"] * 10), 9)
        buckets.setdefault(b, []).append(r)
    out = []
    for b in sorted(buckets):
        rows = buckets[b]
        wins = sum(1 for r in rows if r["won"])
        lo95, hi95 = wilson(wins, len(rows))
        out.append({
            "lo": round(b / 10, 1), "hi": round(b / 10 + 0.1, 1), "n": len(rows),
            "predicted": round(sum(r["fair_value"] for r in rows) / len(rows), 3),
            "actual": round(wins / len(rows), 3),
            "lo95": lo95, "hi95": hi95,
        })
    return out


def stats(closed, portfolio, hist):
    positions = portfolio["positions"]
    exposure = sum(paper.position_cost(x) for x in positions)
    marked = 0.0
    for x in positions:
        h = hist.get(x["ticker"], [])
        marked += (h[-1]["mark"] if h else x["entry_price"]) * x["contracts"]
    realized = sum(r["pnl"] for r in closed)
    unrealized = marked - exposure
    s = {
        "bankroll": portfolio["bankroll"],
        # marked to market, not held at cost — the headline number should move
        # when the book moves, not only when something settles
        "equity": round(portfolio["bankroll"] + marked, 2),
        "exposure": round(exposure, 2),
        "open_positions": len(positions),
        "settled": len(closed),
        "wins": sum(1 for r in closed if r["won"]),
        "total_pnl": round(realized, 2),
        "unrealized_pnl": round(unrealized, 2),
        "fees_paid": round(sum(r["fee_paid"] for r in closed), 2),
        "starting_bankroll": paper.STARTING_BANKROLL,
    }
    staked = sum(paper.position_cost(r) for r in closed)
    s["staked"] = round(staked, 2)
    s["win_rate"] = round(s["wins"] / len(closed), 3) if closed else None
    # Two different denominators, both wanted, previously conflated under one
    # ambiguous "ROI" tile: return on the capital actually put at risk ...
    s["roi_staked"] = round(realized / staked, 4) if staked else None
    # ... and the fund-level number the hero equity implies.
    s["return_total"] = round((realized + unrealized) / paper.STARTING_BANKROLL, 4)
    s["brier"] = (round(sum((r["fair_value"] - (1.0 if r["won"] else 0.0)) ** 2
                            for r in closed) / len(closed), 4) if closed else None)
    # What a no-skill forecaster scores on the same trades: always predicting
    # the observed base rate. Brier alone reads as a number with no yardstick.
    if closed:
        base = s["wins"] / len(closed)
        s["brier_baseline"] = round(sum((base - (1.0 if r["won"] else 0.0)) ** 2
                                        for r in closed) / len(closed), 4)
    else:
        s["brier_baseline"] = None
    return s


MARKS = paper.DATA / "marks.jsonl"


def yes_price(m) -> float | None:
    """Current P(yes) from the book, or None if the market has no price.

    A market that is about to resolve empties its book and quotes 0.0000 /
    1.0000 — a degenerate spread, not a real mid. Falling back to last_price
    there keeps the mark alive through settlement week instead of freezing
    the sparkline days before the outcome (the interesting part).
    """
    yb = float(m.get("yes_bid_dollars") or 0)
    ya = float(m.get("yes_ask_dollars") or 0)
    if 0 < yb <= ya < 1:
        return (yb + ya) / 2
    last = float(m.get("last_price_dollars") or 0)
    return last if 0 < last < 1 else None


def record_marks(portfolio):
    """Snapshot the current market mark for each open position.

    Appends to marks.jsonl (one line per open position per publish run);
    the dashboard's position tiles read the per-day history from
    aggregates. `mark` is the mid quote converted to OUR side, so
    mark > entry_price always means the position is winning at market.
    """
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    rows = []
    for x in portfolio["positions"]:
        row = {"t": now, "date": now[:10], "ticker": x["ticker"], "side": x["side"],
               "entry_price": x["entry_price"], "fair_value": x["fair_value"]}
        try:
            m = kalshi.get_market(x["ticker"])
            yes = yes_price(m)
            if yes is not None:
                row["mark"] = round(yes if x["side"] == "yes" else 1 - yes, 3)
            row["title"] = (m.get("title") or "").replace("*", "")
            row["close_time"] = paper.market_close_time(m)
        except Exception as e:
            print(f"! mark {x['ticker']}: {e}")
        rows.append(row)
    if rows:
        with MARKS.open("a") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
    return rows


def mark_history():
    """ticker -> [{date, mark, title}] — last mark per day, in date order."""
    if not MARKS.exists():
        return {}
    per_day = {}  # (ticker, date) -> row, last write wins
    for line in MARKS.read_text().splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("mark") is not None:
            per_day[(r["ticker"], r["date"])] = r
    hist = {}
    for (ticker, date), r in sorted(per_day.items(), key=lambda kv: kv[0]):
        hist.setdefault(ticker, []).append(
            {"date": date, "mark": r["mark"], "title": r.get("title", ""),
             "close_time": r.get("close_time")})
    return hist


def main():
    PUBLIC.mkdir(parents=True, exist_ok=True)
    portfolio = paper.load()
    closed = load_closed()
    record_marks(portfolio)
    hist = mark_history()

    briefs = sorted(paper.DATA.glob("brief-*.json"))
    for b in briefs:
        shutil.copy2(b, PUBLIC / b.name)
    dates = sorted((b.stem.replace("brief-", "") for b in briefs), reverse=True)
    (PUBLIC / "manifest.json").write_text(json.dumps({"dates": dates}))

    # series slug map for kalshi.com deep links on trade cards
    tickers = {x["ticker"] for x in portfolio["positions"]}
    tickers.update(r["ticker"] for r in closed)
    for b in briefs:
        d = json.loads(b.read_text())
        for sec in ("trades_opened", "trades_settled", "considered_but_passed"):
            tickers.update(t.get("ticker", "") for t in d.get(sec, []))
    (PUBLIC / "series.json").write_text(json.dumps(series_slugs(tickers)))

    # every ticker anywhere on the dashboard gets a human-readable title
    titles = title_map(tickers, hist)
    (PUBLIC / "titles.json").write_text(json.dumps(titles, indent=1))

    open_positions = []
    for x in portfolio["positions"]:
        h = hist.get(x["ticker"], [])
        open_positions.append({
            "ticker": x["ticker"], "side": x["side"], "entry_price": x["entry_price"],
            "contracts": x["contracts"], "fair_value": x["fair_value"],
            "edge": x["edge_at_entry"], "reasoning": x["reasoning"], "opened": x["opened"],
            "title": titles.get(x["ticker"], ""),
            "closes": next((m["close_time"] for m in reversed(h)
                            if m.get("close_time")), None),
            "mark": h[-1]["mark"] if h else None,
            "mark_prev": h[-2]["mark"] if len(h) > 1 else None,
            "marks": [{"date": m["date"], "mark": m["mark"]} for m in h],
        })

    agg = {
        "generated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "stats": stats(closed, portfolio, hist),
        "equity_curve": equity_curve(closed, portfolio, hist),
        "calibration": calibration(closed),
        "open_positions": open_positions,
        "recent_settled": [dict(r, title=titles.get(r["ticker"], ""))
                           for r in closed[-20:][::-1]],
    }
    for pt in agg["equity_curve"]:
        for e in pt["events"]:
            e["title"] = titles.get(e["ticker"], "")
    (PUBLIC / "aggregates.json").write_text(json.dumps(agg, indent=1))
    print(f"published {len(dates)} briefs + aggregates to {PUBLIC}")


if __name__ == "__main__":
    main()
