"""prereg.py point: binding point forecasts, scored against Kalshi's value.

The judgment step pre-registers a daily fuel point forecast every run
(brief 10/21: "Pre-regs for 10/22 are logged: gas MINE 4.2530, diesel MINE
6.315") and scores it by hand the next day against RW / MOM / DRIFT ("Diesel:
MINE 6.317 won with a 0.04c error ... MINE is now 5-1 on the diesel daily").
The forecast lives only in watchlist prose, which the same step rewrites
daily. `point` journals it like `add` does probabilities; `score` does the
error and, for the daily fuel series, the race against fuelscore's models.
"""

import json
import pathlib
import sys
from datetime import datetime, timezone

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parents[1]))
import fuelscore
import prereg

NOW = datetime(2026, 10, 21, 12, 10, tzinfo=timezone.utc)
EVENT = "KXDIESELD-26OCT22"


def mkt(strike, bid="0.4000", ask="0.5000", result="", value=None,
        close="2026-10-22T03:59:00Z"):
    return {"ticker": f"{EVENT}-T{strike}", "yes_bid_dollars": bid,
            "yes_ask_dollars": ask, "close_time": close, "status": "active",
            "result": result, "expiration_value": value}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(prereg, "JOURNAL", tmp_path / "preregs.jsonl")
    prints = tmp_path / "prints.jsonl"
    # diesel 10/15..10/21: changes -0.10, -0.20, -0.30, -0.10, -0.20, -0.25c
    days = ["6.3250", "6.3240", "6.3220", "6.3190", "6.3180", "6.3160",
            "6.3135"]
    prints.write_text("".join(
        json.dumps({"date": f"2026-10-{15 + i}",
                    "prices": {"current": {"diesel": f"${p}"}}}) + "\n"
        for i, p in enumerate(days)))
    monkeypatch.setattr(fuelscore, "JOURNAL", prints)
    events = {EVENT: {"markets": [mkt("6.31"), mkt("6.32")]}}
    monkeypatch.setattr(prereg.kalshi, "get_event", lambda t: events[t])
    return events


def journal():
    return [json.loads(l) for l in
            prereg.JOURNAL.read_text().splitlines() if l.strip()]


def test_point_journals_the_exact_value_and_board(env):
    rec = prereg.point(EVENT, "mine", "6.3150", now=NOW)
    assert rec["leg"] == "MINE" and rec["point"] == "6.3150"
    row = journal()[0]
    assert row["point"] == "6.3150"
    assert row["board"][f"{EVENT}-T6.31"] == ["0.4000", "0.5000"]
    assert row["at"] == "2026-10-21T12:10:00+00:00"


def test_point_is_binding_and_refuses_closed_events_and_non_numbers(env):
    prereg.point(EVENT, "MINE", "6.3150", now=NOW)
    with pytest.raises(SystemExit, match="already frozen"):
        prereg.point(EVENT, "MINE", "6.3100", now=NOW)
    with pytest.raises(SystemExit, match="not a number"):
        prereg.point(EVENT, "MINE2", "six", now=NOW)
    late = datetime(2026, 10, 22, 4, 0, tzinfo=timezone.utc)
    with pytest.raises(SystemExit, match="has closed"):
        prereg.point(EVENT, "MINE2", "6.3100", now=late)
    assert len(journal()) == 1


def test_score_races_a_fuel_point_against_fuelscore(env, capsys):
    prereg.point(EVENT, "MINE", "6.3110", now=NOW)
    env[EVENT]["markets"] = [mkt("6.31", result="yes", value="6.311"),
                             mkt("6.32", result="no", value="6.311")]
    prereg.score()
    out = capsys.readouterr().out
    line = [l for l in out.splitlines() if EVENT in l][0]
    # API drops the trailing zero; AAA's 4 places come back
    assert "= 6.3110" in line
    assert "MINE 6.3110 err +0.0000" in line
    # RW = 6.3135; MOM = 6.3135 - 0.0025; DRIFT = 6.3135 + mean(last 5)
    assert "RW 6.3135 err -0.0025" in line
    assert "MOM 6.3110 err +0.0000" in line
    assert "DRIFT 6.3114 err -0.0004" in line
    assert line.endswith("-> MINE MOM")
    summary = [l for l in out.splitlines() if l.startswith("# MINE point")][0]
    assert "n=1, MAE 0.0000" in summary
    assert "MINE MAE 0.0000 best 1" in summary
    assert "RW MAE 0.0025 best 0" in summary
    assert "MOM MAE 0.0000 best 1" in summary


def test_score_keeps_a_point_pending_until_settled(env, capsys):
    prereg.point(EVENT, "MINE", "6.3150", now=NOW)
    prereg.score()
    assert f"{EVENT}  MINE  pending" in capsys.readouterr().out


def test_non_fuel_point_scores_the_plain_error(env, capsys, monkeypatch):
    e = "KXPAYROLLS-26SEP"
    markets = [{"ticker": f"{e}-T50000", "result": "no",
                "expiration_value": "29,000", "close_time":
                "2026-10-03T12:30:00Z", "status": "active",
                "yes_bid_dollars": "0.3000", "yes_ask_dollars": "0.3200"}]
    monkeypatch.setattr(prereg.kalshi, "get_event",
                        lambda t: {"markets": markets})
    prereg.point(e, "MINE", "100000",
                 now=datetime(2026, 10, 1, tzinfo=timezone.utc))
    prereg.score()
    out = capsys.readouterr().out
    assert "= 29000  MINE 100000 err -71000" in out
    assert "->" not in out
    assert "# MINE point: n=1, MAE 71000.0000" in out
