"""highfreeze.py score: a closed-but-unsettled event says HELD, not pending.

KXHIGHLAX-26OCT22 closed 10/23 08:00Z and on 10/25 still had no result or
expiration_value. The archived CLILAX for 10/22 printed max 71, then 72
(08:48Z), then 71 again (23:44Z) — exactly the B70.5 (70-71) / T71 (72+)
boundary. `score` printed the day as plain "pending", the same as a day that
hasn't closed yet, so the hold was invisible and the LAX bias ledger silently
lost a day. An event past its close with no result is now tagged HELD with
the close time, so the judgment step knows to wait or investigate.
"""

import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parents[1]))
import highfreeze
from test_highfreeze_bias import buckets, event

DAY = "2026-10-22"


@pytest.fixture
def held(tmp_path, monkeypatch):
    journal = tmp_path / "high-freeze.jsonl"
    journal.write_text(json.dumps(
        {"city": "LAX", "date": DAY, "event": event(DAY), "high": 66,
         "buckets": buckets(DAY)}) + "\n")
    monkeypatch.setattr(highfreeze, "JOURNAL", journal)
    state = {"close": "2026-10-23T08:00:00Z"}

    def get_event(ticker):
        return {"markets": [
            {"ticker": b["ticker"], "status": "closed", "result": "",
             "expiration_value": "", "close_time": state["close"]}
            for b in buckets(DAY)]}
    monkeypatch.setattr(highfreeze.kalshi, "get_event", get_event)
    return state


def row(capsys):
    return [l for l in capsys.readouterr().out.splitlines()
            if l.startswith(DAY)][0]


def test_closed_event_without_a_result_is_tagged_held(held, capsys):
    highfreeze.score()
    line = row(capsys)
    assert "pending" in line and "grid 66" in line
    assert "HELD: closed 2026-10-23T08:00:00Z, Kalshi has not settled" in line


def test_event_not_yet_closed_is_plain_pending(held, capsys):
    held["close"] = "2099-01-01T08:00:00Z"
    highfreeze.score()
    assert "HELD" not in row(capsys)


def test_event_closed_hours_ago_is_still_plain_pending(held, capsys):
    # the normal settle lag: closed 05-08Z, the 12Z run sees it unsettled
    import datetime as dt
    recent = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=6)
    held["close"] = recent.strftime("%Y-%m-%dT%H:%M:%SZ")
    highfreeze.score()
    assert "HELD" not in row(capsys)


def test_lookup_failure_is_plain_pending(held, capsys, monkeypatch):
    def boom(ticker):
        raise OSError("404")
    monkeypatch.setattr(highfreeze.kalshi, "get_event", boom)
    highfreeze.score()
    line = row(capsys)
    assert "pending" in line and "HELD" not in line
