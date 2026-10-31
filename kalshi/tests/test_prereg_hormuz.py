"""prereg.py score: a Hormuz weekly pre-reg scores off the PortWatch journal.

KXHORMUZWEEKLY settles on the sum of PortWatch's daily transit calls over the
week ending on the event's date ("summing daily counts from Oct 26 to Nov 1"),
and "no earlier than Tuesday at 9 AM", after the Tuesday run journals the
first prints. Week 6 was scored by hand on 10/28 from `portwatch.py first`
("Brier 0.0009+0.0324+0.2025+0.0121+0.0001 = 0.248") while prereg.py printed
pending. The journal's first-print sum matched Kalshi on every fully
journaled week (9/20..10/25), so like the AAA fuel ladders, an unsettled
week scores off the journal, tagged, and a settled one off Kalshi.
"""

import json
import pathlib
import sys
from datetime import datetime, timezone

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parents[1]))
import portwatch
import prereg

EVENT = "KXHORMUZWEEKLY-26NOV01"
NOW = datetime(2026, 10, 28, 12, 3, tzinfo=timezone.utc)
# the 10/28 pre-reg, MINE, on five of its strikes
MINE = {"T15": 0.96, "T20": 0.75, "T23": 0.50, "T25": 0.33, "T30": 0.06}
BOARD = {"T15": ("0.9500", "0.9800"), "T20": ("0.7800", "0.8400"),
         "T23": ("0.5900", "0.6200"), "T25": ("0.3700", "0.4000"),
         "T30": ("0.1300", "0.1800")}


def mkt(strike, result="", value=None):
    bid, ask = BOARD[strike]
    return {"ticker": f"{EVENT}-{strike}", "strike_type": "greater",
            "floor_strike": int(strike[1:]), "yes_bid_dollars": bid,
            "yes_ask_dollars": ask, "close_time": "2026-11-03T14:00:00Z",
            "status": "active", "result": result, "expiration_value": value}


def journal_week(tmp_path, counts, start=26, extra=()):
    """First prints 10/26.. (one per count), then any revision rows."""
    path = tmp_path / "portwatch" / "hormuz.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for i, n in enumerate(counts):
        day = datetime(2026, 10, start, tzinfo=timezone.utc).date()
        day = day.fromordinal(day.toordinal() + i).isoformat()
        rows.append({"date": day, "n_total": n,
                     "seen_at": "2026-11-03T13:01:00+00:00"})
    rows.extend(extra)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(prereg, "JOURNAL", tmp_path / "preregs.jsonl")
    monkeypatch.setattr(portwatch, "DATA", tmp_path)
    events = {EVENT: {"markets": [mkt(s) for s in MINE]}}
    monkeypatch.setattr(prereg.kalshi, "get_event", lambda t: events[t])
    prereg.add(EVENT, "MINE", MINE, now=NOW)
    return events


def line(out):
    return [l for l in out.splitlines() if EVENT in l][0]


def test_unsettled_week_scores_off_the_portwatch_first_prints(
        env, tmp_path, capsys):
    # 10/26..11/1 = 24: T15/T20/T23 YES, T25/T30 NO
    journal_week(tmp_path, [4, 3, 3, 4, 4, 3, 3])
    prereg.score()
    out = capsys.readouterr().out
    got = line(out)
    assert "pending" not in got
    assert "= 24" in got and "n5" in got
    # MINE .0016+.0625+.25+.1089+.0036; BOARD mids .965 .81 .605 .385 .155
    assert "MINE 0.4266" in got and "BOARD 0.3656" in got
    assert got.endswith("-> BOARD  (PortWatch journal, Kalshi unsettled)")
    assert "# MINE: n=1 events, Brier sum 0.4266 vs BOARD 0.3656" in out


def test_week_with_an_unpublished_day_stays_pending(env, tmp_path, capsys):
    journal_week(tmp_path, [4, 3, 3, 4, 4, 3])  # 11/1 not yet published
    prereg.score()
    assert line(capsys.readouterr().out).endswith("pending")


def test_no_portwatch_journal_stays_pending(env, capsys):
    prereg.score()
    assert line(capsys.readouterr().out).endswith("pending")


def test_revision_does_not_move_the_first_print_sum(env, tmp_path, capsys):
    # Kalshi settles on the first print (HAZARD 1c); 10/27 later revised 3->9
    journal_week(tmp_path, [4, 3, 3, 4, 4, 3, 3], extra=[
        {"date": "2026-10-27", "n_total": 9, "revised_from": 3,
         "seen_at": "2026-11-04T13:01:00+00:00"}])
    prereg.score()
    assert "= 24" in line(capsys.readouterr().out)


def test_sum_exactly_on_a_strike_waits_for_kalshi(env, tmp_path, capsys):
    journal_week(tmp_path, [4, 3, 3, 4, 3, 3, 3])  # 23: 'above 23' is Kalshi's
    prereg.score()
    assert line(capsys.readouterr().out).endswith("pending")


def test_kalshi_settlement_still_wins_over_the_journal(env, tmp_path, capsys):
    journal_week(tmp_path, [4, 3, 3, 4, 4, 3, 3])  # journal says 24
    env[EVENT] = {"markets": [
        mkt(s, result="yes" if s in ("T15", "T20") else "no", value="22")
        for s in MINE]}
    prereg.score()
    got = line(capsys.readouterr().out)
    assert "= 22" in got and "journal" not in got


def test_other_families_have_no_journal_value(env, tmp_path):
    journal_week(tmp_path, [4, 3, 3, 4, 4, 3, 3])
    assert prereg._journal_value("KXRT-SOC") is None
    assert prereg._journal_value(EVENT) == (24, "PortWatch journal")
