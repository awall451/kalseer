"""portwatch.py archive: after a schema edit, check the fields we query.

The layer was republished 2026-11-03 14:13Z (data and schema both edited,
per #112's line). The 12Z query that morning was the last one answered;
since then 11/4-11/5 skipped on Invalid URL and 11/6 on 429 twice, morning
and late. #112 says "schema too: fields may have moved, cf. item #19" and
op-11-06 asked a human to confirm portname/date/n_total by hand. The layer
metadata already in hand lists `fields`, so the line answers it at no extra
request: names a queried field that is gone (with a case-only near miss,
since attributes come back under the layer's own spelling) and the date
field's type (item #19 was a date type change).
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from test_portwatch import QUOTA_ERROR, portwatch  # noqa: F401
from test_portwatch_layer import _layer, _pin, _seed, api  # noqa: F401

FIELDS = [{"name": "ObjectId", "type": "esriFieldTypeOID"},
          {"name": "date", "type": "esriFieldTypeDate"},
          {"name": "portname", "type": "esriFieldTypeString"},
          {"name": "n_total", "type": "esriFieldTypeInteger"}]


def _run(api, tmp_path, monkeypatch, capsys, fields, schema="2026-11-03"):
    _seed(tmp_path, seen_at="2026-10-28T12:00:11+00:00")
    _pin(monkeypatch, "2026-11-06")
    api["bodies"] = [QUOTA_ERROR, QUOTA_ERROR]
    api["layer"] = _layer("2026-11-03T14:13:00+00:00",
                          f"{schema}T14:13:00+00:00")
    if fields is not None:
        api["layer"]["fields"] = fields
    portwatch.main(["archive"])
    return capsys.readouterr().out


def test_schema_edit_with_our_fields_intact_says_so(api, tmp_path,
                                                    monkeypatch, capsys):
    out = _run(api, tmp_path, monkeypatch, capsys, FIELDS)
    assert "schema too" in out
    assert ("queried fields date, portname, n_total all present "
            "(date is esriFieldTypeDate)") in out
    assert sum("/query?" not in u for u in api["urls"]) == 1


def test_a_missing_field_is_named_with_its_case_near_miss(api, tmp_path,
                                                          monkeypatch,
                                                          capsys):
    fields = [f for f in FIELDS if f["name"] != "n_total"] + [
        {"name": "N_TOTAL", "type": "esriFieldTypeInteger"}]
    out = _run(api, tmp_path, monkeypatch, capsys, fields)
    assert "queried field missing: n_total (layer has N_TOTAL)" in out


def test_a_field_gone_outright_lists_what_the_layer_has(api, tmp_path,
                                                        monkeypatch, capsys):
    fields = [f for f in FIELDS if f["name"] != "portname"] + [
        {"name": "portid", "type": "esriFieldTypeString"}]
    out = _run(api, tmp_path, monkeypatch, capsys, fields)
    assert "queried field missing: portname" in out
    assert "layer fields: ObjectId, date, n_total, portid" in out


def test_a_date_type_change_is_visible(api, tmp_path, monkeypatch, capsys):
    fields = [dict(f, type="esriFieldTypeDateOnly") if f["name"] == "date"
              else f for f in FIELDS]
    out = _run(api, tmp_path, monkeypatch, capsys, fields)
    assert "(date is esriFieldTypeDateOnly)" in out


def test_no_schema_edit_adds_no_field_line(api, tmp_path, monkeypatch,
                                           capsys):
    out = _run(api, tmp_path, monkeypatch, capsys, FIELDS,
               schema="2026-08-01")
    assert "queried field" not in out


def test_metadata_without_fields_adds_no_field_line(api, tmp_path,
                                                    monkeypatch, capsys):
    out = _run(api, tmp_path, monkeypatch, capsys, None)
    assert "schema too" in out
    assert "queried field" not in out
