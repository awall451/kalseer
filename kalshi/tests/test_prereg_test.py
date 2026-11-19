"""prereg.py test: a pass's two-sided falsifier, frozen and scored.

Every pass on a fuel board ends in a test written into watchlist prose
(11/18: "TEST: >= 5.935 -> MINE/MOM right, tight board too low; <= 5.930 ->
board/WKDAY right") and resolved by hand the next run ("11/17 test (>3.755
models / <=3.750 board): print 3.7502 sits 0.02c above 3.750 -> neither
clean"). The same step rewrites that prose daily, so the thresholds can
drift after the print. `test` freezes them like `point` freezes a value:
binding, timestamped, refused once the event closes. `score` resolves each
against the settled value (or the journal print before Kalshi settles).
"""

import json
import pathlib
import sys
from datetime import datetime, timezone

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parents[1]))
import fuelscore
import prereg

NOW = datetime(2026, 11, 18, 13, 5, tzinfo=timezone.utc)
EVENT = "KXDIESELD-26NOV19"


def mkt(strike, result="", value=None, close="2026-11-19T03:59:00Z"):
    return {"ticker": f"{EVENT}-T{strike}", "yes_bid_dollars": "0.3800",
            "yes_ask_dollars": "0.5800", "close_time": close,
            "status": "active", "result": result, "expiration_value": value,
            "strike_type": "greater", "floor_strike": strike}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(prereg, "JOURNAL", tmp_path / "preregs.jsonl")
    prints = tmp_path / "prints.jsonl"
    prints.write_text(json.dumps(
        {"date": "2026-11-18", "prices": {"current": {"diesel": "$5.9594"}}})
        + "\n")
    monkeypatch.setattr(fuelscore, "JOURNAL", prints)
    events = {EVENT: {"markets": [mkt("5.930"), mkt("5.935")]}}
    monkeypatch.setattr(prereg.kalshi, "get_event", lambda t: events[t])
    return events


def journal():
    return [json.loads(l) for l in
            prereg.JOURNAL.read_text().splitlines() if l.strip()]


def freeze(*args):
    prereg.main(["test", EVENT, "test", *args])


def settle(env, value):
    env[EVENT]["markets"] = [mkt(s, result="no", value=value)
                             for s in ("5.930", "5.935")]


def scored(capsys):
    capsys.readouterr()
    prereg.score()
    return capsys.readouterr().out.splitlines()


def test_test_journals_both_sides_and_the_board(env, monkeypatch, capsys):
    monkeypatch.setattr(prereg, "_now", lambda: NOW)
    freeze("5.935=MINE/MOM", "5.930=BOARD/WKDAY")
    row = journal()[0]
    assert row["leg"] == "TEST"
    assert row["test"] == {"above": ["5.935", "MINE/MOM"],
                           "below": ["5.930", "BOARD/WKDAY"]}
    assert row["at"] == "2026-11-18T13:05:00+00:00"
    assert row["board"][f"{EVENT}-T5.935"] == ["0.3800", "0.5800"]
    assert capsys.readouterr().out == (
        f"prereg: {EVENT} TEST: >= 5.935 MINE/MOM, <= 5.930 BOARD/WKDAY "
        "frozen at 2026-11-18T13:05:00+00:00\n")


def test_test_is_binding_and_checks_its_sides(env, monkeypatch):
    monkeypatch.setattr(prereg, "_now", lambda: NOW)
    freeze("5.935=MINE/MOM", "5.930=BOARD")
    with pytest.raises(SystemExit, match="already frozen"):
        freeze("5.940=MINE", "5.930=BOARD")
    with pytest.raises(SystemExit, match="above"):
        prereg.main(["test", EVENT, "TEST2", "5.930=MINE", "5.935=BOARD"])
    with pytest.raises(SystemExit, match="not a number"):
        prereg.main(["test", EVENT, "TEST2", "high=MINE", "5.930=BOARD"])
    with pytest.raises(SystemExit):
        prereg.main(["test", EVENT, "TEST2", "5.935", "5.930=BOARD"])


def test_test_refuses_a_closed_event(env, monkeypatch):
    monkeypatch.setattr(prereg, "_now", lambda: datetime(
        2026, 11, 19, 12, 0, tzinfo=timezone.utc))
    with pytest.raises(SystemExit, match="closed"):
        freeze("5.935=MINE", "5.930=BOARD")


def test_score_resolves_each_side_and_the_dead_zone(env, monkeypatch,
                                                   capsys):
    monkeypatch.setattr(prereg, "_now", lambda: NOW)
    freeze("5.935=MINE/MOM", "5.930=BOARD/WKDAY")
    settle(env, "5.9290")
    assert scored(capsys)[0] == (
        f"2026-11-18  {EVENT}  TEST  = 5.9290  >= 5.935 MINE/MOM | "
        "<= 5.930 BOARD/WKDAY  -> BOARD/WKDAY")
    settle(env, "5.9350")  # a side's own threshold counts for it
    assert scored(capsys)[0].endswith("-> MINE/MOM")
    settle(env, "5.9320")
    assert scored(capsys)[0].endswith("-> neither (between)")


def test_score_uses_the_journal_print_before_kalshi_settles(env, monkeypatch,
                                                           capsys):
    # 11/17's diesel test, resolved by hand on 11/18 off the 5.9594 print
    env["KXDIESELD-26NOV18"] = {"markets": [
        {**mkt("5.960"), "ticker": "KXDIESELD-26NOV18-T5.960",
         "close_time": "2026-11-18T03:59:00Z"}]}
    monkeypatch.setattr(prereg, "_now", lambda: datetime(
        2026, 11, 17, 13, 5, tzinfo=timezone.utc))
    prereg.main(["test", "KXDIESELD-26NOV18", "TEST", "5.970=MOM",
                 "5.960=WKDAY/DRIFT"])
    out = scored(capsys)
    assert out[0] == (
        "2026-11-17  KXDIESELD-26NOV18  TEST  = 5.9594  >= 5.970 MOM | "
        "<= 5.960 WKDAY/DRIFT  -> WKDAY/DRIFT  (AAA journal, Kalshi "
        "unsettled)")


def test_score_pends_and_summarises(env, monkeypatch, capsys):
    monkeypatch.setattr(prereg, "_now", lambda: NOW)
    freeze("5.935=MINE/MOM", "5.930=BOARD/WKDAY")
    out = scored(capsys)
    assert out[0] == f"2026-11-18  {EVENT}  TEST  pending"
    assert out[-1] == "# tests: n=1, resolved 0, between 0, pending 1"
    settle(env, "5.9290")
    assert scored(capsys)[-1] == (
        "# tests: n=1, resolved 1, between 0, pending 0; "
        "BOARD/WKDAY 1")


def test_prompt_names_the_test_verb():
    prompt = (pathlib.Path(__file__).parents[2] / "bin"
              / "daily-prompt.md").read_text()
    assert "prereg.py test EVENT TEST" in prompt
