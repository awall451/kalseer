"""portwatch.py archive: a successor's tables, and what a lacking layer has.

11/24 (and 11/10): the old service answered `499 Token Required`, and the
directory read said `PortWatch_chokepoints_database: layer 0
PortWatch_chokepoints_database lacks date, n_total`. That line stops there.
It never says what the layer does carry, so nobody can map a fallback
field. It also only ever read the FeatureServer's `layers`. ArcGIS lists
non-spatial tables (a daily transit series has no geometry) under `tables`,
so a daily table was never even looked at. Hormuz has been journaled only
to 11/15 since then.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from test_portwatch import portwatch  # noqa: F401
from test_portwatch_successor import (  # noqa: F401 (fixture)
    DAILY, NEW, NEW_BASE, NOV2, STATIC, _fields, _journal, _rows, api)


def test_a_successor_table_with_our_fields_is_archived_from(api, tmp_path,
                                                            capsys):
    api["pages"] = {NEW_BASE + "?f=json": {
                        "layers": [{"id": 0, "name": "Chokepoints"}],
                        "tables": [{"id": 1, "name": "Daily transits"}]},
                    NEW_BASE + "/0?f=json": STATIC,
                    NEW_BASE + "/1?f=json": DAILY}
    api["bodies"] = [_rows((NOV2, 21))]
    portwatch.main(["archive"])
    out = capsys.readouterr().out
    assert any(u.startswith(NEW_BASE + "/1/query?") for u in api["urls"])
    assert f"from successor {NEW}/FeatureServer/1" in out
    assert "table 1 Daily transits has date, portname, n_total" in out
    assert [r["date"] for r in _journal(tmp_path)][1:] == ["2026-11-02"]


def test_a_lacking_layer_names_the_fields_it_has(api, capsys):
    api["pages"] = {NEW_BASE + "?f=json": {"layers": [
                        {"id": 0, "name": "Chokepoints"}]},
                    NEW_BASE + "/0?f=json": STATIC}
    portwatch.main(["archive"])
    out = capsys.readouterr().out
    assert ("layer 0 Chokepoints lacks date, n_total "
            "(has ObjectId, portname, lat, lon)") in out


def test_a_long_field_list_is_capped(api, capsys):
    many = _fields(*[f"f{i}" for i in range(20)])
    api["pages"] = {NEW_BASE + "?f=json": {"layers": [
                        {"id": 0, "name": "Wide"}]},
                    NEW_BASE + "/0?f=json": many}
    portwatch.main(["archive"])
    out = capsys.readouterr().out
    shown = ", ".join(f"f{i}" for i in range(portwatch.MAX_FIELDS))
    assert f"(has {shown}, +{20 - portwatch.MAX_FIELDS} more)" in out


def test_layers_and_tables_share_the_read_cap(api, capsys):
    api["pages"] = {NEW_BASE + "?f=json": {
        "layers": [{"id": i, "name": f"L{i}"} for i in range(2)],
        "tables": [{"id": 10 + i, "name": f"T{i}"} for i in range(4)]}}
    for i in (0, 1, 10, 11, 12, 13):
        api["pages"][f"{NEW_BASE}/{i}?f=json"] = STATIC
    portwatch.main(["archive"])
    reads = [u for u in api["urls"] if u.startswith(NEW_BASE + "/")]
    assert len(reads) == portwatch.MAX_LAYERS
    assert reads[-1] == f"{NEW_BASE}/10?f=json"  # layers first, then tables
