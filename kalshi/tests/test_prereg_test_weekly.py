"""prereg.py test on the weekly and monthly fuel boards.

#139 froze the daily passes' tests, but the weekly/monthly ones stayed
prose carried day to day (watchlist 11/20: "11/23 test unchanged (>=5.86
DRIFT / <=5.82 board)", "11/30 test unchanged (<3.50 DRIFT / >3.60 margin
reversion)", and a new weekly gas "11/23 print <= 3.615 -> models right;
>= 3.630 -> board right" written that day and never frozen). `test` takes
any event, and every AAA series settles on its date's exact print, so these
resolve off the journal like the dailies; the prompt has to say so.
"""

import json
import pathlib
import sys
from datetime import datetime, timezone

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parents[1]))
import fuelscore
import prereg

NOW = datetime(2026, 11, 21, 13, 5, tzinfo=timezone.utc)
MONTHLY = "KXAAAGASM-26NOV30"
WEEKLY = "KXDIESELW-26NOV23"


def mkt(event, strike):
    return {"ticker": f"{event}-{strike}", "yes_bid_dollars": "0.4900",
            "yes_ask_dollars": "0.5000", "close_time": "2026-11-30T14:00:00Z",
            "status": "active", "result": "", "expiration_value": None,
            "strike_type": "greater", "floor_strike": strike.lstrip("T")}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(prereg, "JOURNAL", tmp_path / "preregs.jsonl")
    prints = tmp_path / "prints.jsonl"
    prints.write_text("".join(json.dumps(
        {"date": d, "prices": {"current": {"regular": f"${g}",
                                           "diesel": f"${s}"}}}) + "\n"
        for d, g, s in (("2026-11-23", "3.6012", "5.8133"),
                        ("2026-11-30", "3.4875", "5.7010"))))
    monkeypatch.setattr(fuelscore, "JOURNAL", prints)
    events = {MONTHLY: {"markets": [mkt(MONTHLY, "3.50"),
                                    mkt(MONTHLY, "3.60")]},
              WEEKLY: {"markets": [mkt(WEEKLY, "T5.82"),
                                   mkt(WEEKLY, "T5.86")]}}
    monkeypatch.setattr(prereg.kalshi, "get_event", lambda t: events[t])
    monkeypatch.setattr(prereg, "_now", lambda: NOW)
    return events


def scored(capsys):
    capsys.readouterr()
    prereg.score()
    return capsys.readouterr().out.splitlines()


def test_monthly_and_weekly_tests_resolve_off_the_journal(env, capsys):
    prereg.main(["test", MONTHLY, "TEST", "3.60=MARGIN", "3.50=DRIFT"])
    prereg.main(["test", WEEKLY, "TEST", "5.86=DRIFT", "5.82=BOARD"])
    out = scored(capsys)
    assert (f"2026-11-21  {MONTHLY}  TEST  = 3.4875  >= 3.60 MARGIN | "
            "<= 3.50 DRIFT  -> DRIFT  (AAA journal, Kalshi unsettled)") in out
    assert (f"2026-11-21  {WEEKLY}  TEST  = 5.8133  >= 5.86 DRIFT | "
            "<= 5.82 BOARD  -> BOARD  (AAA journal, Kalshi unsettled)") in out
    assert out[-1] == ("# tests: n=2, resolved 2, between 0, pending 0; "
                       "BOARD 1  DRIFT 1")


def test_prompt_says_weekly_and_carried_tests_freeze_too():
    prompt = (pathlib.Path(__file__).parents[2] / "bin"
              / "daily-prompt.md").read_text()
    assert "weekly and monthly boards (KXDIESELW, KXAAAGASW, KXAAAGASM)" \
        in prompt
    assert "still carried in prose" in prompt
