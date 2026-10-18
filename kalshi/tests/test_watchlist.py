"""watchlist.py: validated, backed-up, atomic edits to $DATA/watchlist.json.

The watchlist is the judgment step's only memory ("you start every run cold").
Every run so far has edited it with a fresh one-off script in $DATA
(wl_update_1013b_tmp.py ... wl_update_1017_tmp.py, 11 left behind) that ends
in json.dump(w, open(P, 'w')): a typo'd id raises KeyError (fine), but
anything that fails mid-dump truncates the file in place. The 10/16 log adds
"running my update scripts directly needed approval". These tests pin one
granted CLI that applies a JSON patch all-or-nothing.
"""

import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parents[1]))
import watchlist


def item(id_, thesis="T0.", **kw):
    return dict({"id": id_, "title": f"{id_} title", "check_from": "2026-10-01",
                 "expires": "2026-10-31", "market": "KX-*", "thesis": thesis},
                **kw)


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setattr(watchlist, "DATA", tmp_path)
    monkeypatch.setattr(watchlist, "_today", lambda: "2026-10-18")
    (tmp_path / "watchlist.json").write_text(json.dumps({"items": [
        item("gas", "Series 4.31.", notes="n0"), item("rt")]}, indent=1))
    return tmp_path


def patch(data, body):
    p = data / "watchlist-patch.json"
    p.write_text(json.dumps(body))
    return str(p)


def items(data):
    return {i["id"]: i for i in
            json.loads((data / "watchlist.json").read_text())["items"]}


def test_update_sets_fields_and_appends_to_thesis(data, capsys):
    watchlist.main(["apply", patch(data, {"update": {"gas": {
        "title": "new title", "append": "*** 10/18: 4.30.", "notes": "n1"}}})])
    gas = items(data)["gas"]
    assert gas["title"] == "new title"
    assert gas["thesis"] == "Series 4.31. *** 10/18: 4.30."
    assert gas["notes"] == "n1"
    assert "updated gas" in capsys.readouterr().out


def test_add_and_remove(data):
    watchlist.main(["apply", patch(data, {
        "add": [item("lax", "Opened 10/18.")], "remove": ["rt"]})])
    assert sorted(items(data)) == ["gas", "lax"]


def test_unknown_id_writes_nothing(data, capsys):
    before = (data / "watchlist.json").read_text()
    with pytest.raises(SystemExit) as e:
        watchlist.main(["apply", patch(data, {
            "update": {"gas": {"append": "ok"}, "gsa": {"append": "typo"}}})])
    assert e.value.code == 2
    assert "gsa" in capsys.readouterr().err
    assert (data / "watchlist.json").read_text() == before


def test_unknown_update_field_is_refused(data):
    with pytest.raises(SystemExit):
        watchlist.main(["apply", patch(data, {"update": {"gas": {
            "thesys": "typo"}}})])
    assert items(data)["gas"]["thesis"] == "Series 4.31."


def test_added_item_needs_the_schema_and_a_fresh_id(data):
    for bad in (item("gas"), {"id": "x", "title": "no dates", "thesis": "t"},
                item("y", expires="10/31/26")):
        with pytest.raises(SystemExit):
            watchlist.main(["apply", patch(data, {"add": [bad]})])
    assert sorted(items(data)) == ["gas", "rt"]


def test_thesis_replacement_that_shrinks_needs_explicit_consent(data):
    with pytest.raises(SystemExit):
        watchlist.main(["apply", patch(data, {"update": {"gas": {
            "thesis": "short"}}})])
    assert items(data)["gas"]["thesis"] == "Series 4.31."
    watchlist.main(["apply", patch(data, {"update": {"gas": {
        "thesis": "short", "shrink": True}}})])
    assert items(data)["gas"]["thesis"] == "short"


def test_first_apply_of_the_day_snapshots_a_backup(data):
    original = (data / "watchlist.json").read_text()
    watchlist.main(["apply", patch(data, {"update": {"gas": {"append": "a"}}})])
    watchlist.main(["apply", patch(data, {"update": {"gas": {"append": "b"}}})])
    # the backup is the morning's file, not the state after the first apply
    assert (data / "watchlist-bak-1018.json").read_text() == original
    assert items(data)["gas"]["thesis"].endswith("a b")


def test_write_is_atomic_on_serialization_failure(data, monkeypatch):
    before = (data / "watchlist.json").read_text()

    def boom(*a, **kw):
        raise TypeError("not JSON serializable")
    monkeypatch.setattr(watchlist.json, "dump", boom)
    with pytest.raises(TypeError):
        watchlist.main(["apply", patch(data, {"update": {"gas": {
            "append": "x"}}})])
    assert (data / "watchlist.json").read_text() == before
    assert [p.name for p in data.iterdir() if p.name.endswith(".tmp")] == []


def test_malformed_patch_is_a_loud_exit(data, capsys):
    p = data / "watchlist-patch.json"
    p.write_text('{"update": ')
    with pytest.raises(SystemExit) as e:
        watchlist.main(["apply", str(p)])
    assert e.value.code == 2


def test_show_lists_ids_windows_and_titles(data, capsys):
    watchlist.main(["show"])
    out = capsys.readouterr().out
    assert "gas  2026-10-01..2026-10-31" in out
    assert "gas title" in out


def test_show_one_item_prints_its_json(data, capsys):
    watchlist.main(["show", "rt"])
    assert json.loads(capsys.readouterr().out)["id"] == "rt"


def test_usage(data):
    with pytest.raises(SystemExit) as e:
        watchlist.main([])
    assert "apply" in str(e.value.code)


def test_judgment_step_is_granted_the_cli():
    # invoked by relative path like every repo CLI; without its own grant the
    # judgment run stops for approval (the 10/16 friction this replaces)
    settings = pathlib.Path(__file__).parents[2] / ".claude" / "settings.json"
    allow = json.loads(settings.read_text())["permissions"]["allow"]
    assert "Bash(python3 kalshi/watchlist.py *)" in allow
