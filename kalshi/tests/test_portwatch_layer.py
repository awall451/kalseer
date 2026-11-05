"""portwatch.py archive: say whether PortWatch edited the layer at all.

Week 7 (10/26-11/1) never landed: 11/1-11/3 answered `0 new days` and
10/31 and 11/4 skipped on `arcgis error 400: Invalid URL` (twice each, morning
and late). Nothing in the log could tell "PortWatch hasn't published" from
"the layer was republished and our query no longer sees it" (item #19, the
9/28 field-type change, was the second kind). The hosted layer's own
metadata (FeatureServer/0?f=json, `editingInfo`) answers that: its last
data edit and last schema edit, compared with the newest seen_at in the
journal. The read costs one request, spent only when the answer matters:
after a skip, or after `0 new days` while a weekly batch is due. It never
fails the step.
"""

import datetime
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from test_portwatch import FakeResponse, QUOTA_ERROR, ROWS, portwatch  # noqa: F401

INVALID_URL = {"error": {"code": 400, "message": "Invalid URL",
                         "details": ["Invalid URL"]}}


def _ms(stamp):
    return int(datetime.datetime.fromisoformat(stamp).timestamp() * 1000)


def _layer(data, schema):
    return {"name": "Daily_Chokepoints_Data",
            "editingInfo": {"lastEditDate": _ms(data),
                            "dataLastEditDate": _ms(data),
                            "schemaLastEditDate": _ms(schema)}}


@pytest.fixture
def api(tmp_path, monkeypatch):
    """Queries pop `bodies`; the layer metadata URL serves `layer`."""
    monkeypatch.setattr(portwatch, "DATA", tmp_path)
    state = {"bodies": [], "layer": None, "urls": [], "sleeps": []}

    def fake_urlopen(req, timeout=30):
        url = req.full_url
        state["urls"].append(url)
        if "/query?" in url:
            return FakeResponse(state["bodies"].pop(0))
        if isinstance(state["layer"], Exception):
            raise state["layer"]
        return FakeResponse(state["layer"])
    monkeypatch.setattr(portwatch.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(portwatch.time, "sleep", state["sleeps"].append)
    return state


def _pin(monkeypatch, day):
    monkeypatch.setattr(portwatch, "_today",
                        lambda: datetime.date.fromisoformat(day))


def _seed(tmp_path, seen_at="2026-09-18T12:00:00+00:00"):
    path = tmp_path / "portwatch" / "hormuz.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"date": "2026-09-16", "n_total": 4,
                    "seen_at": seen_at}) + "\n")


def test_layer_url_is_the_query_layer():
    assert portwatch.LAYER_URL + "/query" == portwatch.QUERY_URL


def test_skip_reports_an_unedited_layer_as_unpublished(api, tmp_path,
                                                       monkeypatch, capsys):
    _seed(tmp_path)
    _pin(monkeypatch, "2026-09-26")
    api["bodies"] = [INVALID_URL, INVALID_URL]
    api["layer"] = _layer("2026-09-17T20:00:00+00:00",
                          "2026-08-01T00:00:00+00:00")
    portwatch.main(["archive"])
    out = capsys.readouterr().out
    assert "skipped (arcgis error twice" in out
    assert ("layer data last edited 2026-09-17 20:00Z, schema 2026-08-01 "
            "00:00Z") in out
    assert "no data edit since the journal last changed" in out
    assert "unpublished at the source" in out
    assert sum("/query?" not in u for u in api["urls"]) == 1


def test_edit_after_the_journal_points_at_our_query(api, tmp_path,
                                                    monkeypatch, capsys):
    _seed(tmp_path)
    _pin(monkeypatch, "2026-09-26")
    api["bodies"] = [{"features": []}]
    api["layer"] = _layer("2026-09-23T14:00:00+00:00",
                          "2026-09-23T14:00:00+00:00")
    portwatch.main(["archive"])
    out = capsys.readouterr().out
    assert "0 new days" in out
    assert "data edited 2026-09-23 after the journal last changed" in out
    assert "schema too" in out


def test_data_edit_alone_does_not_claim_a_schema_change(api, tmp_path,
                                                        monkeypatch, capsys):
    _seed(tmp_path)
    _pin(monkeypatch, "2026-09-26")
    api["bodies"] = [{"features": []}]
    api["layer"] = _layer("2026-09-23T14:00:00+00:00",
                          "2026-08-01T00:00:00+00:00")
    portwatch.main(["archive"])
    out = capsys.readouterr().out
    assert "data edited 2026-09-23 after the journal last changed" in out
    assert "schema too" not in out


def test_new_days_spend_no_metadata_request(api, tmp_path, monkeypatch,
                                            capsys):
    _pin(monkeypatch, "2026-09-26")
    api["bodies"] = [ROWS]
    portwatch.main(["archive"])
    assert all("/query?" in u for u in api["urls"])
    assert "layer" not in capsys.readouterr().out


def test_zero_new_days_on_a_fresh_journal_spend_no_request(api, tmp_path,
                                                           monkeypatch,
                                                           capsys):
    _seed(tmp_path)
    _pin(monkeypatch, "2026-09-20")   # lag 4d: no batch due
    api["bodies"] = [{"features": []}]
    portwatch.main(["archive"])
    assert all("/query?" in u for u in api["urls"])
    assert "layer" not in capsys.readouterr().out


@pytest.mark.parametrize("layer", [OSError("timed out"), INVALID_URL,
                                   {"name": "x"}])
def test_unreadable_metadata_never_fails_the_step(api, tmp_path, monkeypatch,
                                                  capsys, layer):
    _seed(tmp_path)
    _pin(monkeypatch, "2026-09-26")
    api["bodies"] = [QUOTA_ERROR, QUOTA_ERROR]
    api["layer"] = layer
    portwatch.main(["archive"])
    out = capsys.readouterr().out
    assert "skipped (arcgis error twice" in out
    assert "layer metadata unreadable" in out


def test_calls_never_reads_metadata(api, monkeypatch, capsys):
    api["bodies"] = [{"features": []}]
    portwatch.main(["calls"])
    assert all("/query?" in u for u in api["urls"])
