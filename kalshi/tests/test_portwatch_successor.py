"""portwatch.py archive: follow a successor service that serves our fields.

On 11/10 both Hormuz queries answered `arcgis error 499: Token Required`.
The layer's own metadata answered the same, and #113's directory read said
`Daily_Chokepoints_Data is not in the org's services directory; chokepoint
services listed: PortWatch_chokepoints_database (FeatureServer)`. Week 8 is
due, and the journal is stuck at 11/01. Naming the successor still leaves a
human to read its schema and repoint LAYER_URL. So when the directory lists
a chokepoint FeatureServer, the skip path reads its layers. If a layer has
every field fetch_calls queries (date, portname, n_total), the archive runs
once against that layer. Otherwise the log says what each layer lacks. A
static chokepoint table (no date/n_total) is never queried. LAYER_URL is
left alone, so tomorrow tries the old path first again.
"""

import datetime
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from test_portwatch import FakeResponse, portwatch  # noqa: F401

TOKEN = {"error": {"code": 499, "message": "Token Required"}}
ORG = "https://services9.arcgis.com/weJ1QsnbMYJlCHdG/arcgis/rest/services"
NEW = "PortWatch_chokepoints_database"
OLD_QUERY = f"{ORG}/Daily_Chokepoints_Data/FeatureServer/0/query?"
NEW_BASE = f"{ORG}/{NEW}/FeatureServer"
NOV2 = 1793577600000  # 2026-11-02 00:00 UTC
NOV3 = NOV2 + 86400000


def _fields(*names):
    return {"fields": [{"name": n, "type": "esriFieldTypeString"}
                       for n in names]}


DAILY = _fields("ObjectId", "date", "portname", "n_total", "n_tanker")
STATIC = _fields("ObjectId", "portname", "lat", "lon")


@pytest.fixture
def api(tmp_path, monkeypatch):
    """Old-path queries and metadata answer `old`; the directory lists
    `services`; successor URLs serve `pages[url]`; successor queries pop
    `bodies`."""
    monkeypatch.setattr(portwatch, "DATA", tmp_path)
    monkeypatch.setattr(portwatch, "_today",
                        lambda: datetime.date.fromisoformat("2026-11-11"))
    path = tmp_path / "portwatch" / "hormuz.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"date": "2026-11-01", "n_total": 3,
                                "seen_at": "2026-11-04T12:00:00+00:00"})
                    + "\n")
    state = {"old": TOKEN, "services": [NEW], "pages": {}, "bodies": [],
             "urls": [], "sleeps": []}

    def fake_urlopen(req, timeout=30):
        url = req.full_url
        state["urls"].append(url)
        if url.startswith(OLD_QUERY) or "Daily_Chokepoints_Data" in url:
            return FakeResponse(state["old"])
        if url == ORG + "?f=json":
            return FakeResponse({"services": [
                {"name": n, "type": "FeatureServer"}
                for n in state["services"]]})
        if url.startswith(NEW_BASE) and "/query?" in url:
            return FakeResponse(state["bodies"].pop(0))
        body = state["pages"].get(url)
        if body is None or isinstance(body, Exception):
            raise body or OSError(f"unscripted {url}")
        return FakeResponse(body)
    monkeypatch.setattr(portwatch.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(portwatch.time, "sleep", state["sleeps"].append)
    return state


def _rows(*pairs):
    return {"features": [{"attributes": {"date": d, "n_total": n}}
                         for d, n in pairs]}


def _journal(tmp_path):
    path = tmp_path / "portwatch" / "hormuz.jsonl"
    return [json.loads(l) for l in path.read_text().splitlines()]


def test_a_successor_layer_with_our_fields_is_archived_from(api, tmp_path,
                                                            capsys):
    api["pages"] = {NEW_BASE + "?f=json": {"layers": [
                        {"id": 0, "name": "Chokepoints"},
                        {"id": 1, "name": "Daily transits"}]},
                    NEW_BASE + "/0?f=json": STATIC,
                    NEW_BASE + "/1?f=json": DAILY}
    api["bodies"] = [_rows((NOV2, 21), (NOV3, 24))]
    portwatch.main(["archive"])
    out = capsys.readouterr().out
    rows = _journal(tmp_path)
    assert [(r["date"], r["n_total"]) for r in rows[1:]] == [
        ("2026-11-02", 21), ("2026-11-03", 24)]
    assert any(u.startswith(NEW_BASE + "/1/query?") for u in api["urls"])
    assert not any(u.startswith(NEW_BASE + "/0/query?") for u in api["urls"])
    assert "2 new days, 0 revised" in out
    assert f"from successor {NEW}/FeatureServer/1" in out
    assert "point LAYER_URL at it" in out
    assert "layer 0 Chokepoints lacks date, n_total" in out
    assert "newest journaled day 2026-11-03" in out
    assert (tmp_path / "portwatch" / "hormuz.archived").read_text() \
        == "2026-11-11\n"


def test_no_matching_layer_says_what_each_lacks_and_queries_nothing(
        api, tmp_path, capsys):
    api["pages"] = {NEW_BASE + "?f=json": {"layers": [
                        {"id": 0, "name": "Chokepoints"}]},
                    NEW_BASE + "/0?f=json": STATIC}
    portwatch.main(["archive"])
    out = capsys.readouterr().out
    assert "skipped (arcgis error twice" in out
    assert f"{NEW}: layer 0 Chokepoints lacks date, n_total" in out
    assert not any(u.startswith(NEW_BASE) and "/query?" in u
                   for u in api["urls"])
    assert len(_journal(tmp_path)) == 1
    assert not (tmp_path / "portwatch" / "hormuz.archived").exists()


def test_a_token_walled_successor_is_reported_not_followed(api, capsys):
    api["pages"] = {NEW_BASE + "?f=json": TOKEN}
    portwatch.main(["archive"])
    out = capsys.readouterr().out
    assert f"{NEW} unreadable (arcgis error 499: Token Required)" in out
    assert "skipped (arcgis error twice" in out


def test_a_failing_successor_query_skips_cleanly(api, tmp_path, capsys):
    api["pages"] = {NEW_BASE + "?f=json": {"layers": [
                        {"id": 0, "name": "Daily"}]},
                    NEW_BASE + "/0?f=json": DAILY}
    api["bodies"] = [TOKEN]
    portwatch.main(["archive"])
    out = capsys.readouterr().out
    assert "skipped (arcgis error twice" in out
    assert f"successor {NEW}/FeatureServer/0 errored too" in out
    assert len(_journal(tmp_path)) == 1
    assert len(api["sleeps"]) == 1


def test_following_leaves_layer_url_alone(api, capsys):
    api["pages"] = {NEW_BASE + "?f=json": {"layers": [
                        {"id": 0, "name": "Daily"}]},
                    NEW_BASE + "/0?f=json": DAILY}
    api["bodies"] = [_rows((NOV2, 21))]
    portwatch.main(["archive"])
    assert portwatch.QUERY_URL == OLD_QUERY[:-1]
    assert portwatch.LAYER_URL == f"{ORG}/Daily_Chokepoints_Data/FeatureServer/0"


def test_only_the_first_few_layers_are_read(api, capsys):
    layers = [{"id": i, "name": f"L{i}"} for i in range(8)]
    api["pages"] = {NEW_BASE + "?f=json": {"layers": layers}}
    for i in range(8):
        api["pages"][f"{NEW_BASE}/{i}?f=json"] = STATIC
    portwatch.main(["archive"])
    reads = [u for u in api["urls"] if u.startswith(NEW_BASE + "/")]
    assert len(reads) == portwatch.MAX_LAYERS
