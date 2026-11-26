"""prereg.py score --since DATE: only rows frozen on or after DATE.

The Hormuz revival rule counts from a given week ("MINE beats board on >= 3
of the next 4 scored weeks, counted from week 10"), and the watchlist kept
that counter by hand ("REVIVAL COUNTER ...: 1 of 1 (wk10 MINE, by a hair)")
while `score`'s summary pooled every week ("wins 2-2"). `--since` makes the
counter the summary line itself.
"""

import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parents[1]))
import prereg

# week 9 (MINE loses), week 10 (MINE wins), week 11 (pending)
WEEKS = [("KXHORMUZWEEKLY-26NOV15", "2026-11-12T13:00:00+00:00", 0.9),
         ("KXHORMUZWEEKLY-26NOV22", "2026-11-18T13:00:00+00:00", 0.2),
         ("KXHORMUZWEEKLY-26NOV29", "2026-11-25T13:00:00+00:00", 0.5)]


@pytest.fixture
def env(tmp_path, monkeypatch):
    journal = tmp_path / "preregs.jsonl"
    monkeypatch.setattr(prereg, "JOURNAL", journal)
    rows, events = [], {}
    for event, at, p in WEEKS:
        t = f"{event}-T20"
        rows.append({"event": event, "leg": "MINE", "at": at,
                     "probs": {t: p}, "board": {t: ["0.5000", "0.5200"]}})
        settled = event != WEEKS[-1][0]
        events[event] = {"markets": [{
            "ticker": t, "strike_type": "greater", "floor_strike": 20,
            "result": "no" if settled else "",
            "expiration_value": "16" if settled else ""}]}
    journal.write_text("".join(json.dumps(r) + "\n" for r in rows))
    monkeypatch.setattr(prereg.kalshi, "get_event", lambda t: events[t])
    monkeypatch.setattr(prereg, "_journal_value", lambda e: None)


def summary(out):
    return [l for l in out.splitlines() if l.startswith("# MINE:")][0]


def test_without_since_the_summary_pools_every_week(env, capsys):
    prereg.main(["score", "KXHORMUZWEEKLY"])
    assert "wins 1-1" in summary(capsys.readouterr().out)


def test_since_keeps_only_rows_frozen_on_or_after_the_date(env, capsys):
    prereg.main(["score", "--since", "2026-11-18", "KXHORMUZWEEKLY"])
    out = capsys.readouterr().out
    assert "n=1 events" in summary(out) and "wins 1-0" in summary(out)
    assert "26NOV15" not in out
    assert "26NOV22" in out and "26NOV29  MINE  pending" in out


def test_since_combines_with_days(env, capsys):
    prereg.main(["score", "--days", "30", "--since", "2026-11-12",
                 "KXHORMUZWEEKLY"])
    assert "wins 1-1" in summary(capsys.readouterr().out)


def test_since_after_every_row_says_none(env, capsys):
    prereg.main(["score", "--since", "2026-12-01", "KXHORMUZWEEKLY"])
    out = capsys.readouterr().out
    assert out.startswith("# no pre-regs") and "since 2026-12-01" in out


def test_since_must_be_a_date(env):
    with pytest.raises(SystemExit):
        prereg.main(["score", "--since", "week10"])


def test_prompt_names_score_since():
    prompt = (pathlib.Path(__file__).parents[2] / "bin"
              / "daily-prompt.md").read_text()
    assert ("`python3 kalshi/prereg.py score --since 2026-11-18 "
            "KXHORMUZWEEKLY`") in prompt
