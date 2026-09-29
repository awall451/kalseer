"""IMF PortWatch chokepoint reads for the judgment step. Stdlib only, no auth.

The Hormuz weekly markets settle on PortWatch daily transit calls, and that
source has been dark since 9/3 behind harness fetch rules (item #17: the
WebFetch 'Invalid URL' regression, then the curl fallback's quoted-URL
mismatch). urllib from the judgment host is the proven path, so this CLI
queries the ArcGIS FeatureServer directly — the exact query the watchlist
verified working 8/9–8/24:

  python3 kalshi/portwatch.py calls                       # Hormuz, last 45 days
  python3 kalshi/portwatch.py calls --since 2026-09-01
  python3 kalshi/portwatch.py calls --port Suez

Source hazards this tool respects (watchlist, econ-data-source-hazards):
HAZARD 1b — the endpoint sits behind a SHARED public per-minute quota; an
ArcGIS error arrives as an HTTP-200 JSON body and is a final answer for the
attempt, never retried inside a run. HAZARD 1c — PortWatch revises upward
and Kalshi settles on the FIRST print: n_total prints verbatim; record the
values you saw. Zero rows is a publication answer (the mostly-published
window rule gates on lag), not a fetch failure.
"""

import datetime
import json
import sys
import time
import urllib.parse
import urllib.request

QUERY_URL = ("https://services9.arcgis.com/weJ1QsnbMYJlCHdG/arcgis/rest/"
             "services/Daily_Chokepoints_Data/FeatureServer/0/query")


def _query(params: dict, tries: int = 2) -> dict:
    req = urllib.request.Request(
        QUERY_URL + "?" + urllib.parse.urlencode(params),
        headers={"User-Agent": "paper-research/0.1"})
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                body = json.loads(r.read())
            break
        except Exception:
            if attempt == tries - 1:
                raise
            time.sleep(2 ** attempt)
    if "error" in body:
        # quota exhaustion lands here (HTTP 200); retrying inside the same
        # minute only deepens the hole — report and stop
        msg = body["error"].get("message", str(body["error"]))
        print(f"portwatch: arcgis error: {msg}", file=sys.stderr)
        sys.exit(2)
    return body


def _day(value) -> str:
    """ArcGIS serves `date` as epoch ms or an ISO string (item #19: the
    field type changed under us on 9/28), sometimes with a time part."""
    if isinstance(value, str):
        return datetime.date.fromisoformat(value[:10]).isoformat()
    return datetime.datetime.fromtimestamp(
        value / 1000, tz=datetime.timezone.utc).date().isoformat()


def fetch_calls(port: str, since: str) -> list[tuple[str, object]]:
    """Daily (date, n_total) rows for a chokepoint, newest first."""
    body = _query({
        "where": (f"portname LIKE '%{port}%' AND "
                  f"date >= TIMESTAMP '{since}'"),
        "outFields": "date,n_total",
        "orderByFields": "date DESC",
        "f": "json",
    })
    rows = []
    for feature in body.get("features", []):
        attrs = feature["attributes"]
        rows.append((_day(attrs["date"]), attrs["n_total"]))
    return sorted(rows, reverse=True)


def main(argv: list[str]):
    if argv[:1] != ["calls"]:
        sys.exit(__doc__)
    port, since, opts = "Hormuz", None, argv[1:]
    while opts:
        if opts[:1] == ["--port"] and len(opts) > 1:
            port, opts = opts[1], opts[2:]
        elif opts[:1] == ["--since"] and len(opts) > 1:
            since, opts = opts[1], opts[2:]
        else:
            sys.exit(__doc__)
    if since is None:
        since = (datetime.datetime.now(tz=datetime.timezone.utc).date()
                 - datetime.timedelta(days=45)).isoformat()
    rows = fetch_calls(port, since)
    if not rows:
        print(f"# no published days for {port} since {since}")
        return
    for day, n_total in rows:
        print(f"{day}  {n_total}")
    newest = rows[0][0]
    lag = (datetime.datetime.now(tz=datetime.timezone.utc).date()
           - datetime.date.fromisoformat(newest)).days
    print(f"# newest published day: {newest} (lag {lag}d)")


if __name__ == "__main__":
    main(sys.argv[1:])
