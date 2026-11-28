"""prereg.py point/score: a non-fuel point raced against the frozen board.

The RT ledger keeps its RW-vs-board record in prose (11/27: "Pre-reg
(log-only): the board centres 31.1 / 67.5 / 78.0 vs current 31 / 68 / 79 (RW
= current score). Score Mon 11/30 finals vs RW and the board."). `point`
already freezes RW, but `score` only printed its error: the board centre it
was frozen against stayed hand-copied. Now `point` journals the event's
`# board centre` (a 'greater' ladder crossing on the ladder), and `score`
prints BOARD's error beside the leg, the closer one, and a per-series
head-to-head. The daily fuel rows keep fuelscore's race (fuelfreeze scores
their board centre).
"""

import json
import pathlib
import sys
from datetime import datetime, timezone

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parents[1]))
import prereg

NOW = datetime(2026, 11, 27, 13, 10, tzinfo=timezone.utc)


def mkt(event, strike, bid, ask, result="", value=None):
    return {"ticker": f"{event}-{strike}", "strike_type": "greater",
            "floor_strike": strike, "yes_bid_dollars": bid,
            "yes_ask_dollars": ask, "close_time": "2026-11-30T15:00:00Z",
            "status": "active", "result": result, "expiration_value": value}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(prereg, "JOURNAL", tmp_path / "preregs.jsonl")
    # FOC mids 0.99 / 0.755 / 0.025 -> crossing 30 + 5 x 0.255/0.73 = 31.7
    events = {
        "KXRT-FOC": {"markets": [mkt("KXRT-FOC", 25, "0.9900", "1.0000"),
                                 mkt("KXRT-FOC", 30, "0.7400", "0.7700"),
                                 mkt("KXRT-FOC", 35, "0.0200", "0.0300")]},
        # HEX mids 0.80 / 0.20 -> crossing 67.5
        "KXRT-HEX": {"markets": [mkt("KXRT-HEX", 65, "0.7900", "0.8100"),
                                 mkt("KXRT-HEX", 70, "0.1900", "0.2100")]},
    }
    monkeypatch.setattr(prereg.kalshi, "get_event", lambda t: events[t])
    return events


def settle(events, event, value):
    for m in events[event]["markets"]:
        m["result"] = "yes" if value > m["floor_strike"] else "no"
        m["expiration_value"] = str(value)


def journal():
    return [json.loads(l) for l in
            prereg.JOURNAL.read_text().splitlines() if l.strip()]


def test_point_journals_the_board_centre(env):
    rec = prereg.point("KXRT-FOC", "RW", "31", now=NOW)
    assert rec["centre"] == "31.7"
    assert journal()[0]["centre"] == "31.7"


def test_point_skips_a_centre_off_the_ladder(env):
    env["KXRT-FOC"]["markets"] = [mkt("KXRT-FOC", 30, "0.1000", "0.1200")]
    rec = prereg.point("KXRT-FOC", "RW", "31", now=NOW)
    assert "centre" not in rec


def test_point_skips_a_non_ladder_event(env):
    # a KXHIGH bucket event: buckets plus one 'greater' tail is no ladder
    env["KXRT-FOC"]["markets"] = [
        {**mkt("KXRT-FOC", 30, "0.6000", "0.7000"), "strike_type": "between"},
        mkt("KXRT-FOC", 35, "0.2000", "0.3000")]
    rec = prereg.point("KXRT-FOC", "RW", "31", now=NOW)
    assert "centre" not in rec


def test_score_races_a_non_fuel_point_against_the_board(env, capsys):
    prereg.point("KXRT-FOC", "RW", "31", now=NOW)
    prereg.point("KXRT-HEX", "RW", "68", now=NOW)
    settle(env, "KXRT-FOC", 33)
    settle(env, "KXRT-HEX", 67)
    prereg.score()
    out = capsys.readouterr().out.splitlines()
    foc = [l for l in out if "KXRT-FOC" in l][0]
    assert foc.endswith("= 33  RW 31 err +2  BOARD 31.7 err +1.3  -> BOARD")
    hex_ = [l for l in out if "KXRT-HEX" in l][0]
    assert hex_.endswith("= 67  RW 68 err -1  BOARD 67.5 err -0.5  -> BOARD")
    summary = [l for l in out if l.startswith("# RW point KXRT")][0]
    assert summary == ("# RW point KXRT: n=2, MAE 1.5000; vs BOARD on n=2: "
                       "BOARD MAE 0.9000; RW closer 0, BOARD closer 2, "
                       "tied 0")


def test_score_calls_a_tie_and_counts_it(env, capsys):
    prereg.point("KXRT-HEX", "RW", "67.5", now=NOW)
    settle(env, "KXRT-HEX", 68)
    prereg.score()
    out = capsys.readouterr().out
    assert "RW 67.5 err +0.5  BOARD 67.5 err +0.5  -> RW BOARD" in out
    assert "RW closer 0, BOARD closer 0, tied 1" in out


def test_score_keeps_old_rows_without_a_centre_plain(env, capsys):
    prereg.JOURNAL.write_text(json.dumps(
        {"event": "KXRT-FOC", "leg": "RW", "at": NOW.isoformat(),
         "point": "31", "board": {}}) + "\n")
    settle(env, "KXRT-FOC", 33)
    prereg.score()
    out = capsys.readouterr().out
    assert "= 33  RW 31 err +2" in out
    assert "->" not in out and "vs BOARD" not in out
    assert "# RW point KXRT: n=1, MAE 2.0000" in out


def test_prompt_names_the_rt_point_freeze():
    prompt = (pathlib.Path(__file__).parents[2] / "bin"
              / "daily-prompt.md").read_text()
    assert "`python3 kalshi/prereg.py point KXRT-FOC RW 31`" in prompt
    assert "`# RW point KXRT: ... vs BOARD`" in prompt
