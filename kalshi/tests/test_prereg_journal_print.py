"""prereg.py score: a daily fuel point scores off the AAA journal before
Kalshi settles it.

The judgment step runs at ~12:05Z, minutes after the aaa step journals the
day's print, but Kalshi settles KXAAAGASD / KXDIESELD hours later. So the
point frozen yesterday always showed "pending" when it was due (10/23 run:
"I scored the diesel forecasts by hand. The scoring tool shows them as
pending until Kalshi settles the diesel daily market."). Both series settle
on that exact AAA print, so the journal row is the settlement value.
"""

import json
import pathlib
import sys
from datetime import datetime, timezone

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parents[1]))
import fuelscore
import prereg
from test_prereg_point import EVENT, NOW, mkt


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(prereg, "JOURNAL", tmp_path / "preregs.jsonl")
    prints = tmp_path / "prints.jsonl"
    # diesel 10/16..10/22; 10/22 is the print EVENT settles on
    days = ["6.3240", "6.3220", "6.3190", "6.3180", "6.3160", "6.3135",
            "6.3172"]
    prints.write_text("".join(
        json.dumps({"date": f"2026-10-{16 + i}",
                    "prices": {"current": {"diesel": f"${p}"}}}) + "\n"
        for i, p in enumerate(days)))
    monkeypatch.setattr(fuelscore, "JOURNAL", prints)
    events = {EVENT: {"markets": [mkt("6.31"), mkt("6.32")]}}
    monkeypatch.setattr(prereg.kalshi, "get_event", lambda t: events[t])
    return events


def test_unsettled_fuel_point_scores_off_the_journal_print(env, capsys):
    prereg.point(EVENT, "MINE", "6.3150", now=NOW)
    prereg.score()
    out = capsys.readouterr().out
    line = [l for l in out.splitlines() if EVENT in l][0]
    assert "pending" not in line
    assert "= 6.3172" in line
    assert "MINE 6.3150 err +0.0022" in line
    # RW = 6.3135 (10/21), so err +0.0037
    assert "RW 6.3135 err +0.0037" in line
    assert "-> MINE" in line
    # says where the value came from, so nobody mistakes it for a final
    assert "AAA journal, Kalshi unsettled" in line
    summary = [l for l in out.splitlines() if l.startswith("# MINE point")][0]
    assert "n=1, MAE 0.0022" in summary


def test_settled_value_still_wins_over_the_journal(env, capsys):
    prereg.point(EVENT, "MINE", "6.3150", now=NOW)
    env[EVENT]["markets"] = [mkt("6.31", result="yes", value="6.316"),
                             mkt("6.32", result="no", value="6.316")]
    prereg.score()
    line = [l for l in capsys.readouterr().out.splitlines()
            if EVENT in l][0]
    assert "= 6.3160" in line
    assert "journal" not in line


def test_non_fuel_point_without_settlement_stays_pending(env, capsys,
                                                         monkeypatch):
    e = "KXPAYROLLS-26OCT"
    markets = [{"ticker": f"{e}-T50000", "result": "",
                "expiration_value": None, "close_time":
                "2026-11-06T12:30:00Z", "status": "active",
                "yes_bid_dollars": "0.3000", "yes_ask_dollars": "0.3200"}]
    monkeypatch.setattr(prereg.kalshi, "get_event",
                        lambda t: {"markets": markets})
    prereg.point(e, "MINE", "100000",
                 now=datetime(2026, 10, 22, tzinfo=timezone.utc))
    prereg.score()
    assert f"{e}  MINE  pending" in capsys.readouterr().out
