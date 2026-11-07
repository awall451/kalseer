"""econfreeze moves/score PREFIX: a series name selects that series only.

Brief 11/6: `econfreeze.py moves KXCPI` printed the KXCPICOREYOY-26NOV event
rather than KXCPI-26OCT. KXCPI is a text prefix of KXCPICORE, KXCPIYOY and
KXCPICOREYOY, so a bare startswith printed all four CPI boards and the one the
judgment step read was the last. A bare series name now matches its own
events; anything with a dash (KXCPI-26OCT, KXCPI-26) is still an event prefix.
"""

import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parents[1]))
import econfreeze

EVENTS = ["KXCPI-26OCT", "KXCPICORE-26OCT", "KXCPIYOY-26NOV",
          "KXCPICOREYOY-26NOV"]


@pytest.fixture
def journal(tmp_path, monkeypatch):
    path = tmp_path / "econ" / "f.jsonl"
    path.parent.mkdir()
    rows = [{"event": e, "date": "2026-11-06", "days_out": 4,
             "close_time": "2026-11-10T13:29:00Z",
             "markets": [{"ticker": f"{e}-T0.2", "floor": 0.2,
                          "yes_bid": "0.5700", "yes_ask": "0.5900"}]}
            for e in EVENTS]
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    monkeypatch.setattr(econfreeze, "JOURNAL", path)
    asked = []

    def fake_event(ticker):
        asked.append(ticker)
        return {"markets": [{"ticker": f"{ticker}-T0.2", "result": ""}]}
    monkeypatch.setattr(econfreeze.kalshi, "get_event", fake_event)
    return asked


def headers(out):
    return [l.split()[1] for l in out.splitlines() if l.startswith("# KX")]


def test_moves_series_name_prints_that_series_only(journal, capsys):
    econfreeze.main(["moves", "KXCPI"])
    assert headers(capsys.readouterr().out) == ["KXCPI-26OCT"]
    econfreeze.main(["moves", "KXCPIYOY"])
    assert headers(capsys.readouterr().out) == ["KXCPIYOY-26NOV"]


def test_moves_with_a_dash_is_still_an_event_prefix(journal, capsys):
    econfreeze.main(["moves", "KXCPI-26OCT"])
    assert headers(capsys.readouterr().out) == ["KXCPI-26OCT"]
    econfreeze.main(["moves", "KXCPICORE-26"])
    assert headers(capsys.readouterr().out) == ["KXCPICORE-26OCT"]


def test_moves_without_prefix_prints_every_event(journal, capsys):
    econfreeze.main(["moves"])
    assert headers(capsys.readouterr().out) == EVENTS


def test_score_series_name_asks_kalshi_for_that_series_only(journal, capsys):
    econfreeze.main(["score", "KXCPI"])
    assert journal == ["KXCPI-26OCT"]
    assert "KXCPI-26OCT  pending" in capsys.readouterr().out


def test_unknown_series_says_which_prefix_matched_nothing(journal, capsys):
    econfreeze.main(["moves", "KXCP"])
    out = capsys.readouterr().out
    assert headers(out) == []
    assert "KXCP" in out
