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


def load_closed():
    if not paper.CLOSED.exists():
        return []
    rows = [json.loads(l) for l in paper.CLOSED.read_text().splitlines() if l.strip()]
    rows.sort(key=lambda r: r.get("settled", ""))
    return rows


def equity_curve(closed, portfolio):
    points = [{"t": None, "equity": paper.STARTING_BANKROLL, "label": "start"}]
    equity = paper.STARTING_BANKROLL
    for r in closed:
        equity += r["pnl"]
        points.append({"t": r.get("settled"), "equity": round(equity, 2),
                       "label": r["ticker"], "pnl": r["pnl"]})
    exposure = sum(paper.position_cost(x) for x in portfolio["positions"])
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    points.append({"t": now, "equity": round(portfolio["bankroll"] + exposure, 2),
                   "label": "now (open positions at cost)"})
    if points[0]["t"] is None:
        points[0]["t"] = points[1]["t"] if len(points) > 1 else now
    return points


def calibration(closed):
    buckets = {}
    for r in closed:
        b = min(int(r["fair_value"] * 10), 9)
        buckets.setdefault(b, []).append(r)
    out = []
    for b in sorted(buckets):
        rows = buckets[b]
        out.append({
            "lo": b / 10, "hi": b / 10 + 0.1, "n": len(rows),
            "predicted": round(sum(r["fair_value"] for r in rows) / len(rows), 3),
            "actual": round(sum(1 for r in rows if r["won"]) / len(rows), 3),
        })
    return out


def stats(closed, portfolio):
    exposure = sum(paper.position_cost(x) for x in portfolio["positions"])
    s = {
        "bankroll": portfolio["bankroll"],
        "equity": round(portfolio["bankroll"] + exposure, 2),
        "exposure": round(exposure, 2),
        "open_positions": len(portfolio["positions"]),
        "settled": len(closed),
        "wins": sum(1 for r in closed if r["won"]),
        "total_pnl": round(sum(r["pnl"] for r in closed), 2),
        "fees_paid": round(sum(r["fee_paid"] for r in closed), 2),
        "starting_bankroll": paper.STARTING_BANKROLL,
    }
    staked = sum(paper.position_cost(r) for r in closed)
    s["win_rate"] = round(s["wins"] / len(closed), 3) if closed else None
    s["roi"] = round(s["total_pnl"] / staked, 4) if staked else None
    s["brier"] = (round(sum((r["fair_value"] - (1.0 if r["won"] else 0.0)) ** 2
                            for r in closed) / len(closed), 4) if closed else None)
    return s


def main():
    PUBLIC.mkdir(parents=True, exist_ok=True)
    portfolio = paper.load()
    closed = load_closed()

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

    open_positions = [{
        "ticker": x["ticker"], "side": x["side"], "entry_price": x["entry_price"],
        "contracts": x["contracts"], "fair_value": x["fair_value"],
        "edge": x["edge_at_entry"], "reasoning": x["reasoning"], "opened": x["opened"],
    } for x in portfolio["positions"]]

    agg = {
        "generated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "stats": stats(closed, portfolio),
        "equity_curve": equity_curve(closed, portfolio),
        "calibration": calibration(closed),
        "open_positions": open_positions,
        "recent_settled": closed[-20:][::-1],
    }
    (PUBLIC / "aggregates.json").write_text(json.dumps(agg, indent=1))
    print(f"published {len(dates)} briefs + aggregates to {PUBLIC}")


if __name__ == "__main__":
    main()
