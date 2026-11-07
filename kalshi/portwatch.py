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
  python3 kalshi/portwatch.py archive --late   # again, only if today's skipped
  python3 kalshi/portwatch.py first [--since D] [--port NAME]  # offline

Source hazards this tool respects (watchlist, econ-data-source-hazards):
HAZARD 1b — the endpoint sits behind a SHARED public per-minute quota; an
ArcGIS error arrives as an HTTP-200 JSON body and is a final answer for the
attempt, never retried inside the same minute (`archive`, unattended,
retries once after RETRY_WAIT; `calls` never sleeps). HAZARD 1c — PortWatch revises upward
and Kalshi settles on the FIRST print: n_total prints verbatim; record the
values you saw. Zero rows is a publication answer (the mostly-published
window rule gates on lag), not a fetch failure.

`archive` runs daily in bin/daily.sh — ONE query, last 45 days — and
appends to $DATA/portwatch/<port>.jsonl every day it hasn't seen (the first
print, i.e. the settlement value) and every later change to a seen day
(`revised_from`). `first` reads that journal back with no network and no
quota: first and latest n_total per day, newest first. A successful archive
stamps today's UTC date in $DATA/portwatch/<port>.archived; `archive --late`
(daily.sh, after the judgment step) queries only when today has no stamp,
a second chance minutes after a morning that skipped on arcgis errors
(10/27, 10/29, 10/31), or when the journal's lag says a weekly batch is
due (DUE_DAYS) and may land after the morning query (Tue 11/3). When an
archive skips, or answers no new days while a batch is due, it reads the
layer's metadata once and logs the last data/schema edit against the
journal: no edit since means unpublished at the source; an edit since
means our query missed it (week 7 never landed, 10/31-11/4). If the layer
can't answer even that (Invalid URL, 11/4-11/5), the org's services
directory says whether the service was renamed and lists its successors.
"""

import datetime
import json
import os
import pathlib
import sys
import time
import urllib.parse
import urllib.request

SERVICES_URL = ("https://services9.arcgis.com/weJ1QsnbMYJlCHdG/arcgis/rest/"
                "services")
SERVICE = "Daily_Chokepoints_Data"
LAYER_URL = f"{SERVICES_URL}/{SERVICE}/FeatureServer/0"
QUERY_URL = LAYER_URL + "/query"

DATA = pathlib.Path(os.environ.get("KALSEER_DATA_DIR",
                                   pathlib.Path(__file__).parents[1] / "data"))
# Weekly publication leaves the newest day <= ~10 days old (10/19: 10/11,
# lag 8d); past this the journal is missing at least one weekly batch.
STALE_DAYS = 12
# Batches end on a Sunday and land on Tuesday (lag 2d), so lag 9d means the
# next one is due today; 11/3 saw none at ~12Z and the late step skipped.
DUE_DAYS = 9
# The archive's one retry after an arcgis error waits out the shared quota
# minute (HAZARD 1b); 10/27 and 10/29 skipped on errors 10/28 didn't repeat.
RETRY_WAIT = 65


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
        code = body["error"].get("code", "?")
        # 10/27: 'Invalid URL' read as a bad --port, but an unknown port is
        # a LIKE filter answering zero rows; an error body is the server's
        print(f"portwatch: arcgis error {code}: {msg} (the server's answer "
              f"to this query, not a bad --port, which returns zero rows; "
              f"final for this attempt; the daily archive retries once "
              f"{RETRY_WAIT}s later, then tomorrow)", file=sys.stderr)
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


def _today() -> datetime.date:
    return datetime.datetime.now(tz=datetime.timezone.utc).date()


def freshness(port: str) -> str:
    """'newest journaled day D (lag Nd)', flagged STALE past STALE_DAYS."""
    days = [r["date"] for r in _read(port)]
    if not days:
        return "no journaled days"
    newest = max(days)
    lag = (_today() - datetime.date.fromisoformat(newest)).days
    text = f"newest journaled day {newest} (lag {lag}d)"
    if lag > STALE_DAYS:
        text += (f" STALE (>{STALE_DAYS}d; PortWatch publishes weekly, so "
                 f"a first print is overdue)")
    return text


def batch_due(port: str) -> bool:
    """True when the journal is old enough that a weekly batch is due."""
    days = [r["date"] for r in _read(port)]
    if not days:
        return True
    lag = (_today() - datetime.date.fromisoformat(max(days))).days
    return lag >= DUE_DAYS


def _utc(ms) -> datetime.datetime:
    return datetime.datetime.fromtimestamp(ms / 1000, tz=datetime.timezone.utc)


def _get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "paper-research/0.1"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def _arcgis_error(body) -> str:
    """' (arcgis error CODE: MESSAGE)' for an error body, else ''."""
    if not isinstance(body, dict) or not isinstance(body.get("error"), dict):
        return ""
    err = body["error"]
    return f" (arcgis error {err.get('code', '?')}: {err.get('message', '?')})"


def service_note() -> str:
    """Whether SERVICE is still in the org's services directory, and which
    chokepoint services it lists: a layer answering Invalid URL to its own
    metadata (11/4-11/5) is gone from that path. One request, never fatal."""
    try:
        services = _get_json(SERVICES_URL + "?f=json")["services"]
        listed = [(s["name"].rsplit("/", 1)[-1], s["type"]) for s in services]
    except Exception:
        return "org services directory unreadable too (host or org outage)"
    if (SERVICE, "FeatureServer") in listed:
        return (f"{SERVICE} is still listed in the org's services directory, "
                f"so the layer or its id moved inside it")
    text = f"{SERVICE} is not in the org's services directory"
    choke = [f"{n} ({t})" for n, t in listed if "chokepoint" in n.lower()]
    if not choke:
        return text + f"; no chokepoint service listed ({len(listed)} services)"
    return (text + f"; chokepoint services listed: {', '.join(choke)}; "
            f"point LAYER_URL at the new one")


def layer_note(port: str) -> str:
    """The hosted layer's last data/schema edit against the journal's newest
    seen_at: tells an unpublished batch from a query that no longer sees one
    (week 7, 10/31-11/4). One request, never fatal; if the metadata is
    unreadable, one more asks the org directory whether the service moved."""
    body = None
    try:
        body = _get_json(LAYER_URL + "?f=json")
        info = body["editingInfo"]
        data = _utc(info.get("dataLastEditDate") or info["lastEditDate"])
        schema = _utc(info["schemaLastEditDate"])
    except Exception:
        return (f"layer metadata unreadable{_arcgis_error(body)}; "
                f"{service_note()}")
    text = (f"layer data last edited {data:%Y-%m-%d %H:%MZ}, "
            f"schema {schema:%Y-%m-%d %H:%MZ}")
    seen = [r["seen_at"] for r in _read(port) if r.get("seen_at")]
    if not seen:
        return text
    last = datetime.datetime.fromisoformat(max(seen))
    if data <= last:
        return (text + ": no data edit since the journal last changed, so "
                "the batch is unpublished at the source, not lost to our query")
    text += (f": data edited {data:%Y-%m-%d} after the journal last changed, "
             f"so an empty or failing query is ours to check")
    if schema > last:
        text += " (schema too: fields may have moved, cf. item #19)"
        text += field_note(body.get("fields"))
    return text


# every field fetch_calls names in where/outFields/orderByFields
QUERIED = ("date", "portname", "n_total")


def field_note(fields) -> str:
    """'; queried fields … present' or the missing ones, from the metadata in
    hand: the 11/3 republish edited the schema and no query has been answered
    since (op-11-06 asked a human to check these names by hand)."""
    if not isinstance(fields, list):
        return ""
    types = {f.get("name"): f.get("type") for f in fields}
    missing = [q for q in QUERIED if q not in types]
    if not missing:
        return (f"; queried fields {', '.join(QUERIED)} all present "
                f"(date is {types['date']})")
    # attributes come back under the layer's own spelling, so a case-only
    # rename still breaks attrs["n_total"]
    names = [str(n) for n in types]
    out = []
    for q in missing:
        near = [n for n in names if n.lower() == q]
        out.append(f"{q} (layer has {near[0]})" if near else q)
    text = f"; queried field missing: {', '.join(out)}"
    if "date" in types:
        text += f" (date is {types['date']})"
    return text + f"; layer fields: {', '.join(names)}"


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
    print(f"# {freshness(port)}")


def _stamp(port: str) -> pathlib.Path:
    """Holds the UTC date of the last archive that got an answer."""
    return _journal(port).with_suffix(".archived")


def main(argv: list[str]):
    if argv[:1] not in (["calls"], ["archive"], ["first"]):
        sys.exit(__doc__)
    port, since, late, opts = "Hormuz", None, False, argv[1:]
    while opts:
        if opts[:1] == ["--port"] and len(opts) > 1:
            port, opts = opts[1], opts[2:]
        elif opts[:1] == ["--since"] and len(opts) > 1:
            since, opts = opts[1], opts[2:]
        elif opts[:1] == ["--late"] and argv[0] == "archive":
            late, opts = True, opts[1:]
        else:
            sys.exit(__doc__)
    if argv[0] == "archive":
        today = _today().isoformat()
        stamp = _stamp(port)
        retried = " (late retry)" if late else ""
        if late and stamp.exists() and stamp.read_text().strip() == today:
            if not batch_due(port):
                # the morning archive got its answer; spend no second query
                print(f"portwatch archive: {port}: late retry not needed "
                      f"(archived earlier today); {freshness(port)}")
                return
            # answered, but a weekly batch is due and may land after 12Z
            retried = " (late retry: weekly batch due)"
        # unattended, so it can sleep out the quota minute once; `calls`
        # (the judgment step's) never does
        for attempt in range(2):
            try:
                new, revised = archive(port)
                break
            except SystemExit as e:
                if e.code != 2:
                    raise
                if attempt:
                    print(f"portwatch archive: {port}: skipped (arcgis error "
                          f"twice, {RETRY_WAIT}s apart; final for this run);"
                          f" {freshness(port)}; {layer_note(port)}")
                    return
                time.sleep(RETRY_WAIT)
                retried += " (after one retry)"
        stamp.parent.mkdir(parents=True, exist_ok=True)
        stamp.write_text(today + "\n")
        note = ""
        if not new and batch_due(port):
            # a due batch didn't show: say whether PortWatch edited at all
            note = f"; {layer_note(port)}"
        print(f"portwatch archive: {port}: {new} new days, {revised} revised"
              f"{retried}; {freshness(port)}{note}")
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
