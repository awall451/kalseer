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
  python3 kalshi/portwatch.py archive [--port NAME]       # pipeline step
  python3 kalshi/portwatch.py first [--since D] [--port NAME]  # offline

Source hazards this tool respects (watchlist, econ-data-source-hazards):
HAZARD 1b — the endpoint sits behind a SHARED public per-minute quota; an
ArcGIS error arrives as an HTTP-200 JSON body and is a final answer for the
attempt, never retried inside a run. HAZARD 1c — PortWatch revises upward
and Kalshi settles on the FIRST print: n_total prints verbatim; record the
values you saw. Zero rows is a publication answer (the mostly-published
window rule gates on lag), not a fetch failure.

`archive` runs daily in bin/daily.sh — ONE query, last 45 days — and
appends to $DATA/portwatch/<port>.jsonl every day it hasn't seen (the first
print, i.e. the settlement value) and every later change to a seen day
(`revised_from`). `first` reads that journal back with no network and no
quota: first and latest n_total per day, newest first.
"""

import datetime
import json
import os
import pathlib
import sys
import time
import urllib.parse
import urllib.request

QUERY_URL = ("https://services9.arcgis.com/weJ1QsnbMYJlCHdG/arcgis/rest/"
             "services/Daily_Chokepoints_Data/FeatureServer/0/query")

DATA = pathlib.Path(os.environ.get("KALSEER_DATA_DIR",
                                   pathlib.Path(__file__).parents[1] / "data"))


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


def _journal(port: str) -> pathlib.Path:
    return DATA / "portwatch" / f"{port.lower()}.jsonl"


def _read(port: str) -> list[dict]:
    path = _journal(port)
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def archive(port: str) -> tuple[int, int]:
    """Journal new days and revisions; returns (new days, revised days)."""
    latest = {}
    for r in _read(port):
        latest[r["date"]] = r["n_total"]
    since = (datetime.datetime.now(tz=datetime.timezone.utc).date()
             - datetime.timedelta(days=45)).isoformat()
    seen_at = datetime.datetime.now(tz=datetime.timezone.utc).isoformat(
        timespec="seconds")
    out, new, revised = [], 0, 0
    for day, n_total in sorted(fetch_calls(port, since)):
        if day not in latest:
            out.append({"date": day, "n_total": n_total, "seen_at": seen_at})
            new += 1
        elif latest[day] != n_total:
            out.append({"date": day, "n_total": n_total, "seen_at": seen_at,
                        "revised_from": latest[day]})
            revised += 1
    if out:
        path = _journal(port)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as f:
            f.writelines(json.dumps(r) + "\n" for r in out)
    return new, revised


def print_first(port: str, since: str | None):
    rows = _read(port)
    if not rows:
        print(f"# no archive for {port} at {_journal(port)}")
        return
    first, latest = {}, {}
    for r in rows:
        first.setdefault(r["date"], r["n_total"])
        latest[r["date"]] = r["n_total"]
    days = sorted((d for d in first if not since or d >= since), reverse=True)
    for d in days:
        line = f"{d}  first {first[d]}  latest {latest[d]}"
        if latest[d] != first[d]:
            line += f"  ({latest[d] - first[d]:+d})"
        print(line)
    revised = sum(latest[d] != first[d] for d in days)
    print(f"# {revised} of {len(days)} days revised since first print "
          f"(Kalshi settles on the first)")


def main(argv: list[str]):
    if argv[:1] not in (["calls"], ["archive"], ["first"]):
        sys.exit(__doc__)
    port, since, opts = "Hormuz", None, argv[1:]
    while opts:
        if opts[:1] == ["--port"] and len(opts) > 1:
            port, opts = opts[1], opts[2:]
        elif opts[:1] == ["--since"] and len(opts) > 1:
            since, opts = opts[1], opts[2:]
        else:
            sys.exit(__doc__)
    if argv[0] == "archive":
        try:
            new, revised = archive(port)
        except SystemExit as e:
            if e.code != 2:
                raise
            print(f"portwatch archive: {port}: skipped (arcgis error, "
                  f"final for this run)")
            return
        print(f"portwatch archive: {port}: {new} new days, {revised} revised")
        return
    if argv[0] == "first":
        print_first(port, since)
        return
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
