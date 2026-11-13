"""watchlist.py `replace`: correct a wrong sentence in a thesis in place.

The 11/12 judgment run wrote diesel "MISSED LOW" the 11/11 test band when
the 6.0977 print was inside 6.095-6.110. The patch format only offered
"append" or a full "thesis" rewrite (which must restate the whole journal),
so the run appended "[11/12 correction to the line above: ignore 'MISSED
LOW' ...]" and the wrong claim stays in the journal next to its correction.
A "replace" list of [old, new] pairs fixes the sentence where it sits; each
old text must occur exactly once, so a fix can't land in the wrong place.
"""

import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parents[1]))
import watchlist
from test_watchlist import data, items, patch  # noqa: F401  (fixtures)


THESIS = "11/11 test band 6.095-6.110. 11/12: diesel MISSED LOW. Gas ok."


@pytest.fixture
def wl(data):  # noqa: F811
    watchlist.main(["apply", patch(data, {"update": {"gas": {
        "thesis": THESIS, "shrink": True}}})])
    return data


def test_replace_rewrites_one_exact_passage(wl, capsys):
    watchlist.main(["apply", patch(wl, {"update": {"gas": {"replace": [
        ["diesel MISSED LOW.", "diesel 6.0977 inside the band."]]}}})])
    assert items(wl)["gas"]["thesis"] == (
        "11/11 test band 6.095-6.110. 11/12: diesel 6.0977 inside the band. "
        "Gas ok.")
    assert "updated gas" in capsys.readouterr().out


def test_replace_pairs_apply_in_order_then_append(wl):
    watchlist.main(["apply", patch(wl, {"update": {"gas": {
        "replace": [["MISSED LOW", "inside"], ["Gas ok.", "Gas fine."]],
        "append": "11/13: new."}}})])
    assert items(wl)["gas"]["thesis"] == (
        "11/11 test band 6.095-6.110. 11/12: diesel inside. Gas fine. "
        "11/13: new.")


def test_replace_can_shorten_without_shrink(wl):
    watchlist.main(["apply", patch(wl, {"update": {"gas": {"replace": [
        [" 11/12: diesel MISSED LOW.", ""]]}}})])
    assert items(wl)["gas"]["thesis"] == "11/11 test band 6.095-6.110. Gas ok."


@pytest.mark.parametrize("old,why", [
    ("MISSED HIGH", "not found"),
    ("6.", "occurs 2 times"),
    ("", "empty"),
])
def test_replace_old_text_must_occur_exactly_once(wl, capsys, old, why):
    before = (wl / "watchlist.json").read_text()
    with pytest.raises(SystemExit):
        watchlist.main(["apply", patch(wl, {"update": {"gas": {
            "replace": [[old, "x"]]}}})])
    assert why in capsys.readouterr().err
    assert (wl / "watchlist.json").read_text() == before


def test_a_bad_pair_after_a_good_one_writes_nothing(wl):
    before = (wl / "watchlist.json").read_text()
    with pytest.raises(SystemExit):
        watchlist.main(["apply", patch(wl, {"update": {"gas": {"replace": [
            ["MISSED LOW", "inside"], ["MISSED LOW", "again"]]}}})])
    assert (wl / "watchlist.json").read_text() == before


@pytest.mark.parametrize("bad", [
    "MISSED LOW", [["MISSED LOW"]], [["MISSED LOW", 3]], [{"old": "x"}]])
def test_replace_must_be_a_list_of_string_pairs(wl, capsys, bad):
    with pytest.raises(SystemExit):
        watchlist.main(["apply", patch(wl, {"update": {"gas": {
            "replace": bad}}})])
    assert "[old, new]" in capsys.readouterr().err


def test_replace_and_a_full_thesis_rewrite_are_exclusive(wl, capsys):
    with pytest.raises(SystemExit):
        watchlist.main(["apply", patch(wl, {"update": {"gas": {
            "replace": [["MISSED LOW", "inside"]], "thesis": THESIS + " x"}}})])
    assert "not both" in capsys.readouterr().err


def test_usage_and_prompt_document_replace():
    assert '"replace"' in watchlist.__doc__
    prompt = (pathlib.Path(__file__).parents[2] / "bin" / "daily-prompt.md")
    assert '"replace"' in prompt.read_text()
