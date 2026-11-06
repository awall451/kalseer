"""portwatch.py archive: when the layer itself is gone, ask the org directory.

Since 11/4 every Hormuz query, morning and late, has answered `arcgis error
400: Invalid URL`, and #112's metadata read of the same layer
(FeatureServer/0?f=json) came back `layer metadata unreadable`. A
FeatureServer that answers Invalid URL to both its query and its own
metadata no longer exists at that path. The likely cause is that PortWatch
republished or renamed `Daily_Chokepoints_Data`, and no fix on our side can
recover week 7 until LAYER_URL points at the new service. The org's
services directory (.../arcgis/rest/services?f=json) lists every public
service. So when the metadata is unreadable, layer_note says why (the
arcgis error) and reads that directory once to answer: is our service
still listed, and which chokepoint services does the org serve now. Never
fatal.
"""

import datetime
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from test_portwatch import FakeResponse, QUOTA_ERROR, portwatch  # noqa: F401

INVALID_URL = {"error": {"code": 400, "message": "Invalid URL",
                         "details": ["Invalid URL"]}}
ORG = "https://services9.arcgis.com/weJ1QsnbMYJlCHdG/arcgis/rest/services"


def _service(name, kind="FeatureServer"):
    return {"name": name, "type": kind, "url": f"{ORG}/{name}/{kind}"}


@pytest.fixture
def api(tmp_path, monkeypatch):
    """Queries pop `bodies`; layer metadata serves `layer`; the org
    services directory serves `directory`."""
    monkeypatch.setattr(portwatch, "DATA", tmp_path)
    monkeypatch.setattr(portwatch, "_today",
                        lambda: datetime.date.fromisoformat("2026-11-05"))
    path = tmp_path / "portwatch" / "hormuz.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"date": "2026-10-25", "n_total": 3,
                                "seen_at": "2026-10-28T12:00:00+00:00"})
                    + "\n")
    state = {"bodies": [], "layer": INVALID_URL, "directory": None,
             "urls": [], "sleeps": []}

    def fake_urlopen(req, timeout=30):
        url = req.full_url
        state["urls"].append(url)
        if "/query?" in url:
            return FakeResponse(state["bodies"].pop(0))
        body = state["directory"] if url == ORG + "?f=json" else state["layer"]
        if isinstance(body, Exception):
            raise body
        return FakeResponse(body)
    monkeypatch.setattr(portwatch.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(portwatch.time, "sleep", state["sleeps"].append)
    return state


def _skip(api, capsys):
    api["bodies"] = [INVALID_URL, INVALID_URL]
    portwatch.main(["archive"])
    out = capsys.readouterr().out
    assert "skipped (arcgis error twice" in out
    return out


def test_services_url_is_the_layers_org_directory():
    assert portwatch.SERVICES_URL == ORG
    assert portwatch.LAYER_URL.startswith(
        portwatch.SERVICES_URL + "/" + portwatch.SERVICE + "/FeatureServer")


def test_unreadable_metadata_says_why(api, capsys):
    api["directory"] = {"services": [_service("Daily_Chokepoints_Data")]}
    out = _skip(api, capsys)
    assert "layer metadata unreadable (arcgis error 400: Invalid URL)" in out


def test_a_service_gone_from_the_directory_names_its_replacements(api,
                                                                  capsys):
    api["directory"] = {"services": [
        _service("Daily_Ports_Data"),
        _service("Daily_Chokepoints_Data_v2"),
        _service("Chokepoints_Weekly", "MapServer"),
    ]}
    out = _skip(api, capsys)
    assert "Daily_Chokepoints_Data is not in the org's services directory" in out
    assert "chokepoint services listed: Daily_Chokepoints_Data_v2 " \
           "(FeatureServer), Chokepoints_Weekly (MapServer)" in out
    assert "point LAYER_URL at the new one" in out
    assert "Daily_Ports_Data" not in out


def test_a_gone_service_with_no_replacement_says_so(api, capsys):
    api["directory"] = {"services": [_service("Daily_Ports_Data")]}
    out = _skip(api, capsys)
    assert "Daily_Chokepoints_Data is not in the org's services directory" in out
    assert "no chokepoint service listed (1 services)" in out


def test_a_still_listed_service_points_at_the_layer(api, capsys):
    api["directory"] = {"services": [_service("Daily_Chokepoints_Data")]}
    out = _skip(api, capsys)
    assert "Daily_Chokepoints_Data is still listed in the org's services " \
           "directory" in out


@pytest.mark.parametrize("directory", [OSError("timed out"), INVALID_URL,
                                       {"currentVersion": 11}])
def test_an_unreadable_directory_never_fails_the_step(api, capsys,
                                                      directory):
    api["directory"] = directory
    out = _skip(api, capsys)
    assert "org services directory unreadable too" in out


def test_readable_metadata_spends_no_directory_request(api, capsys):
    ms = int(datetime.datetime(2026, 10, 27, tzinfo=datetime.timezone.utc)
             .timestamp() * 1000)
    api["layer"] = {"editingInfo": {"lastEditDate": ms,
                                    "schemaLastEditDate": ms}}
    out = _skip(api, capsys)
    assert "no data edit since" in out
    assert ORG + "?f=json" not in api["urls"]


def test_a_quota_error_on_metadata_is_reported_too(api, capsys):
    api["layer"] = QUOTA_ERROR
    api["directory"] = {"services": [_service("Daily_Chokepoints_Data")]}
    out = _skip(api, capsys)
    assert "layer metadata unreadable (arcgis error 429:" in out


def test_the_metadata_and_directory_cost_one_request_each(api, capsys):
    api["directory"] = {"services": []}
    _skip(api, capsys)
    assert sum("/query?" not in u for u in api["urls"]) == 2
