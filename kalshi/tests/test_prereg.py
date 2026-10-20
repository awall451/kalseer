"""prereg.py: append-only binding pre-regs, scored against Kalshi's results.

Every calibration ledger the judgment step keeps (RT, Hormuz, LAX heat,
macro) is a "PRE-REG (frozen 10/9 ~12:15Z, binding, log-only)" sentence in
watchlist prose, hand-copied board mids next to it, and a hand Brier sum days
later (rt-method-notes, 10/13: "Brier MINE vs BOARD: >55 0.7225 vs 0.8372;
>57 0.1764 vs 0.5329; ... sum MINE 0.9042 vs BOARD 1.4074 -> MINE wins").
"Binding" is only a promise in prose, and the arithmetic is redone per
family. These tests pin a journal that freezes the probabilities with the
board they were made against, refuses entries the market has already closed
on (or a second entry under the same leg), and a scorer that does the sums.
"""

import json
import pathlib
import sys
from datetime import datetime, timezone

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parents[1]))
import prereg

NOW = datetime(2026, 10, 9, 12, 15, tzinfo=timezone.utc)


def mkt(suffix, bid, ask, close="2026-10-12T14:00:00Z", result="",
        value=None, status="active"):
    return {"ticker": f"KXRT-SOC-{suffix}", "yes_bid_dollars": bid,
            "yes_ask_dollars": ask, "close_time": close, "status": status,
            "result": result, "expiration_value": value}


# Social Reckoning, the board as rt-method-notes froze it by hand on 10/9
SOC = [mkt("55", "0.9100", "0.9200"), mkt("57", "0.7000", "0.7600"),
       mkt("60", "0.1700", "0.2100"), mkt("62", "0.0300", "0.0400")]
EVENTS = {}


@pytest.fixture
def apis(tmp_path, monkeypatch):
    monkeypatch.setattr(prereg, "JOURNAL", tmp_path / "preregs.jsonl")
    calls = []

    def event(ticker):
        calls.append(ticker)
        if ticker not in EVENTS:
            raise OSError("kalshi down")
        return EVENTS[ticker]
    monkeypatch.setattr(prereg.kalshi, "get_event", event)
    EVENTS.clear()
    EVENTS["KXRT-SOC"] = {"markets": [dict(m) for m in SOC]}
    return calls


def journal():
    return [json.loads(l) for l in
            prereg.JOURNAL.read_text().splitlines() if l.strip()]


def settle(value, yes):
    EVENTS["KXRT-SOC"] = {"markets": [
        dict(m, status="finalized", expiration_value=value,
             result="yes" if m["ticker"].split("-")[-1] in yes else "no")
        for m in SOC]}


MINE = {"55": 0.85, "57": 0.42, "60": 0.07, "62": 0.02}


def test_add_freezes_probs_with_the_board(apis):
    prereg.add("KXRT-SOC", "MINE", MINE, now=NOW)
    [r] = journal()
    assert r["event"] == "KXRT-SOC" and r["leg"] == "MINE"
    assert r["at"] == "2026-10-09T12:15:00+00:00"
    assert r["probs"]["KXRT-SOC-57"] == 0.42
    assert r["board"]["KXRT-SOC-57"] == ["0.7000", "0.7600"]
    assert len(r["probs"]) == 4


def test_add_refuses_an_unknown_strike(apis):
    with pytest.raises(SystemExit) as e:
        prereg.add("KXRT-SOC", "MINE", {"58": 0.5}, now=NOW)
    assert "58" in str(e.value) and "57" in str(e.value)
    assert not prereg.JOURNAL.exists()


def test_add_refuses_a_probability_outside_0_1(apis):
    with pytest.raises(SystemExit):
        prereg.add("KXRT-SOC", "MINE", {"57": 42}, now=NOW)
    assert not prereg.JOURNAL.exists()


def test_add_refuses_after_close(apis):
    late = datetime(2026, 10, 12, 14, 0, tzinfo=timezone.utc)
    with pytest.raises(SystemExit) as e:
        prereg.add("KXRT-SOC", "MINE", MINE, now=late)
    assert "closed" in str(e.value)
    assert not prereg.JOURNAL.exists()


def test_add_refuses_a_second_entry_for_the_same_leg(apis):
    prereg.add("KXRT-SOC", "MINE", MINE, now=NOW)
    with pytest.raises(SystemExit) as e:
        prereg.add("KXRT-SOC", "MINE", {"57": 0.6}, now=NOW)
    assert "binding" in str(e.value)
    prereg.add("KXRT-SOC", "MINE2", {"57": 0.6}, now=NOW)
    assert [r["leg"] for r in journal()] == ["MINE", "MINE2"]


def test_cli_parses_strike_equals_p(apis, monkeypatch, capsys):
    monkeypatch.setattr(prereg, "_now", lambda: NOW)
    prereg.main(["add", "KXRT-SOC", "mine", "57=0.42", "60=0.07"])
    [r] = journal()
    assert r["leg"] == "MINE"
    assert r["probs"] == {"KXRT-SOC-57": 0.42, "KXRT-SOC-60": 0.07}
    assert "KXRT-SOC MINE: 2 strikes frozen" in capsys.readouterr().out


def test_score_matches_the_hand_ledger(apis, capsys):
    # rt-method-notes 10/13: "sum MINE 0.9042 vs BOARD 1.4074 -> MINE wins"
    prereg.add("KXRT-SOC", "MINE", MINE, now=NOW)
    settle("55", set())  # ">55" is NO on 55: every frozen strike lost
    prereg.score()
    out = capsys.readouterr().out
    line = [l for l in out.splitlines() if l.startswith("2026-10-09")][0]
    assert "KXRT-SOC" in line and "MINE" in line and "= 55" in line
    # exact board sum 1.40745: the hand ledger truncated it to 1.4074
    assert "MINE 0.9042" in line and "BOARD 1.4075" in line
    assert line.endswith("-> MINE")
    assert "# MINE: n=1 events, Brier sum 0.9042 vs BOARD 1.4075, " \
           "wins 1-0" in out


def test_score_pending_until_every_strike_settles(apis, capsys):
    prereg.add("KXRT-SOC", "MINE", MINE, now=NOW)
    prereg.score()
    assert "pending" in capsys.readouterr().out


def test_score_filters_by_prefix(apis, capsys):
    prereg.add("KXRT-SOC", "MINE", MINE, now=NOW)
    settle("55", set())  # ">55" is NO on 55: every frozen strike lost
    prereg.score(prefix="KXHORMUZ")
    assert "KXRT-SOC" not in capsys.readouterr().out
    assert apis == ["KXRT-SOC"]  # the add's board read; score fetched none


def test_prereg_cli_grant_present():
    settings = pathlib.Path(__file__).parents[2] / ".claude" / "settings.json"
    allow = json.loads(settings.read_text())["permissions"]["allow"]
    assert "Bash(python3 kalshi/prereg.py *)" in allow
