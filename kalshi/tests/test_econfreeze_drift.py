"""econfreeze score: did the board median's in-week drift point at the print?

The Hormuz watchlist keeps a hand ledger of it (11/25: "IN-WEEK DRIFT RECORD:
wk10 down (24.2 -> 14.9 at T-0, settle 19) -> right direction off T-9, but it
overshot. Count it informed-but-overshot: 3-1 in direction"), read off the
`board median miss` cells. That record decides whether the board's drift is
informed (the 11/3 falsifier: "the board's tracker signal is real"). `score`
now prints, per settled event, the first freeze's median against the last's
and the print, and a per-series tally.
"""

import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parents[1]))
import econfreeze


def _row(event, days_out, median):
    """A two-strike ladder whose mids (0.60 / 0.40) cross 0.5 at `median`."""
    return {"event": event, "date": "2026-11-1%d" % (9 - days_out % 10),
            "close_time": "2026-11-23T03:59:00Z", "days_out": days_out,
            "markets": [
                {"ticker": f"{event}-T{median - 1}", "floor": median - 1,
                 "yes_bid": "0.5900", "yes_ask": "0.6100"},
                {"ticker": f"{event}-T{median + 1}", "floor": median + 1,
                 "yes_bid": "0.3900", "yes_ask": "0.4100"}]}


def _settled(event, value):
    return {"markets": [{"ticker": f"{event}-T5", "floor_strike": 5,
                         "result": "yes", "expiration_value": value}]}


@pytest.fixture
def journal(tmp_path, monkeypatch):
    path = tmp_path / "econ" / "f.jsonl"
    path.parent.mkdir()
    monkeypatch.setattr(econfreeze, "JOURNAL", path)
    state = {"rows": [], "settled": {}}

    def write():
        path.write_text("".join(json.dumps(r) + "\n" for r in state["rows"]))
    state["write"] = write
    monkeypatch.setattr(econfreeze.kalshi, "get_event",
                        lambda t: state["settled"].get(t, {"markets": []}))
    return state


def _out(journal, prefix="KXHORMUZWEEKLY"):
    journal["write"]()
    econfreeze.score(prefix)


W10, W9 = "KXHORMUZWEEKLY-26NOV22", "KXHORMUZWEEKLY-26NOV15"


def test_right_direction_but_overshot(journal, capsys):
    # wk10: 24 -> 15 at T-0, settled 19
    journal["rows"] = [_row(W10, 9, 24), _row(W10, 4, 14), _row(W10, 0, 15)]
    journal["settled"][W10] = _settled(W10, "19")
    _out(journal)
    lines = capsys.readouterr().out.splitlines()
    assert (f"# {W10} median drift: T-9 24.000 -> T-0 15.000 (-9.000); "
            "settled 19 (-5.000 from T-9) -> right direction, overshot; "
            "T-0 closer") in lines


def test_wrong_direction_and_the_per_series_tally(journal, capsys):
    # wk10 as above; wk9: 21 -> 22 at T-0, settled 16 (drifted away)
    journal["rows"] = [_row(W9, 2, 21), _row(W9, 0, 22),
                       _row(W10, 9, 24), _row(W10, 0, 15)]
    journal["settled"][W9] = _settled(W9, "16")
    journal["settled"][W10] = _settled(W10, "19")
    _out(journal)
    lines = capsys.readouterr().out.splitlines()
    assert (f"# {W9} median drift: T-2 21.000 -> T-0 22.000 (+1.000); "
            "settled 16 (-5.000 from T-2) -> wrong direction; "
            "T-0 farther") in lines
    assert ("# board median drift KXHORMUZWEEKLY: n=2, right direction 1, "
            "wrong 1, flat 0; overshot 1; last freeze closer than the first "
            "1, farther 1") in lines


def test_right_direction_short_of_the_print(journal, capsys):
    journal["rows"] = [_row(W10, 9, 24), _row(W10, 0, 21)]
    journal["settled"][W10] = _settled(W10, "19")
    _out(journal)
    out = capsys.readouterr().out
    assert "-> right direction; T-0 closer" in out
    assert "overshot 0" in out


def test_no_drift_line_for_one_freeze_pending_or_off_ladder(journal, capsys):
    off = _row(W10, 0, 15)
    off["markets"][0]["yes_bid"], off["markets"][0]["yes_ask"] = \
        "0.3900", "0.4100"   # every mid below 0.5: median '<14'
    journal["rows"] = [_row(W9, 0, 21), _row(W10, 9, 24), off,
                       _row("KXHORMUZWEEKLY-26NOV29", 6, 17),
                       _row("KXHORMUZWEEKLY-26NOV29", 5, 16)]
    journal["settled"][W9] = _settled(W9, "16")
    journal["settled"][W10] = _settled(W10, "19")
    _out(journal)
    out = capsys.readouterr().out
    assert "median drift:" not in out
    assert "# board median drift" not in out


def test_tallies_are_per_series(journal, capsys):
    cpi = "KXCPI-26OCT"
    journal["rows"] = [_row(W10, 9, 24), _row(W10, 0, 15),
                       _row(cpi, 7, 3), _row(cpi, 0, 4)]
    journal["settled"][W10] = _settled(W10, "19")
    journal["settled"][cpi] = _settled(cpi, "4.5%")
    _out(journal, None)
    lines = [l for l in capsys.readouterr().out.splitlines()
             if l.startswith("# board median drift")]
    assert [l.split(":")[0] for l in lines] == [
        "# board median drift KXCPI", "# board median drift KXHORMUZWEEKLY"]


def test_prompt_names_the_drift_lines():
    prompt = (pathlib.Path(__file__).parents[2] / "bin"
              / "daily-prompt.md").read_text()
    assert "`# EVENT median drift:`" in prompt
    assert "`# board median drift SERIES:`" in prompt
