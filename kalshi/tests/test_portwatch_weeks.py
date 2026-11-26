"""portwatch.py weeks: first-print sums per Mon-Sun week, the Hormuz base rate.

KXHORMUZWEEKLY-<date> settles on the sum of PortWatch first prints over the
7 days ending on <date>, a Sunday. The watchlist keeps that table by hand
(11/25: "BASE-RATE TABLE n=10: 22, 22, 19, 29, 26, 23, 31, 27, 16, 19; mean
23.4, sd 4.8; last two weeks 16 and 19"), and MINE's centre comes off it
("the mean of weeks 9 and 10"). `weeks` reads it off the journal, offline.
"""

import json
import pathlib
import sys
from datetime import date, timedelta

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parents[1]))
import portwatch


def _journal(tmp_path, start, counts, extra=()):
    path = tmp_path / "portwatch" / "hormuz.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    d = date.fromisoformat(start)
    rows = [{"date": (d + timedelta(days=i)).isoformat(), "n_total": n}
            for i, n in enumerate(counts)]
    rows.extend(extra)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setattr(portwatch, "DATA", tmp_path)
    monkeypatch.setattr(portwatch, "_today", lambda: date(2026, 11, 26))
    return tmp_path


def _out(capsys, *args):
    portwatch.main(["weeks", *args])
    return capsys.readouterr().out.splitlines()


def test_full_weeks_sum_newest_first_with_the_kalshi_event(data, capsys):
    # Mon 11/9 .. Sun 11/22: weeks of 16 and 19
    _journal(data, "2026-11-09", [6, 1, 4, 1, 1, 1, 2, 3, 1, 3, 3, 4, 4, 1])
    lines = _out(capsys)
    assert lines[0] == ("2026-11-22  KXHORMUZWEEKLY-26NOV22  sum 19  "
                        "(3 1 3 3 4 4 1)")
    assert lines[1] == ("2026-11-15  KXHORMUZWEEKLY-26NOV15  sum 16  "
                        "(6 1 4 1 1 1 2)")
    assert "# n=2 full weeks: mean 17.50, sd 2.12, min 16, max 19" in lines


def test_first_prints_count_not_revisions(data, capsys):
    _journal(data, "2026-11-16", [3, 1, 3, 3, 4, 4, 1],
             extra=[{"date": "2026-11-16", "n_total": 9,
                     "revised_from": 3}])
    assert _out(capsys)[0].startswith(
        "2026-11-22  KXHORMUZWEEKLY-26NOV22  sum 19")


def test_partial_weeks_are_shown_but_not_in_the_stats(data, capsys):
    # a leading partial (Sat/Sun 11/14-15) and a trailing one (Mon-Wed)
    _journal(data, "2026-11-14", [1, 2, 3, 1, 3, 3, 4, 4, 1, 5, 5, 5])
    lines = _out(capsys)
    assert lines[0] == ("2026-11-29  KXHORMUZWEEKLY-26NOV29  partial 3 of 7 "
                        "days, 15 so far")
    assert lines[-3] == ("2026-11-15  KXHORMUZWEEKLY-26NOV15  partial 2 of "
                         "7 days, 3 so far")
    assert "# n=1 full weeks: mean 19.00, sd -, min 19, max 19" in lines


def test_since_drops_older_weeks(data, capsys):
    _journal(data, "2026-11-09", [6, 1, 4, 1, 1, 1, 2, 3, 1, 3, 3, 4, 4, 1])
    lines = _out(capsys, "--since", "2026-11-16")
    assert not any("26NOV15" in l for l in lines)
    assert "# n=1 full weeks" in lines[-2]


def test_last_line_is_freshness_and_other_ports_have_no_ticker(data,
                                                               capsys):
    path = data / "portwatch" / "suez.jsonl"
    path.parent.mkdir(parents=True)
    d = date(2026, 11, 16)
    path.write_text("".join(json.dumps(
        {"date": (d + timedelta(days=i)).isoformat(), "n_total": 40})
        + "\n" for i in range(7)))
    lines = _out(capsys, "--port", "Suez")
    assert lines[0] == "2026-11-22  sum 280  (40 40 40 40 40 40 40)"
    assert lines[-1] == "# newest journaled day 2026-11-22 (lag 4d)"


def test_a_week_first_read_long_after_it_ended_is_tagged(data, capsys):
    # the journal began with a 10/17 backfill of 9/2.., so those "first
    # prints" are our first read, not necessarily PortWatch's first print
    path = data / "portwatch" / "hormuz.jsonl"
    path.parent.mkdir(parents=True)
    rows = []
    for i in range(14):
        d = date(2026, 9, 7) + timedelta(days=i)
        seen = "2026-10-17T12:00:59+00:00" if i < 7 else (
            (d + timedelta(days=3)).isoformat() + "T12:00:00+00:00")
        rows.append({"date": d.isoformat(), "n_total": 2, "seen_at": seen})
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    lines = _out(capsys)
    assert lines[0] == ("2026-09-20  KXHORMUZWEEKLY-26SEP20  sum 14  "
                        "(2 2 2 2 2 2 2)")
    assert lines[1] == ("2026-09-13  KXHORMUZWEEKLY-26SEP13  sum 14  "
                        "(2 2 2 2 2 2 2)  first read 2026-10-17, 34d after "
                        "the week ended")


def test_no_journal(data, capsys):
    assert _out(capsys)[0].startswith("# no archive for Hormuz")


def test_prompt_names_weeks():
    prompt = (pathlib.Path(__file__).parents[2] / "bin"
              / "daily-prompt.md").read_text()
    assert "`python3 kalshi/portwatch.py weeks [--since D]`" in prompt
