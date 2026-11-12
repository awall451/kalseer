"""portwatch.py news: tell the judgment step a Hormuz week just completed.

11/11: the morning `portwatch` step journaled 7 new days (11/02..11/08,
newest 2026-11-08, lag 3d), completing week 8 (sum 27, KXHORMUZWEEKLY-
26NOV08). Minutes later the judgment session wrote "Week 8 unpublished
(expect ~11/15)" and "Hormuz stand-down holds (week 8 unpublished, no new
work)": it trusted its own watchlist note from 11/10, and the frozen MINE
pre-reg (which `prereg.py score` grades off the journal) went unscored in
the brief. The step's log line said it, but the judgment session starts
cold and only reads its prompt. bin/daily.sh now prepends `news`, like
gap.py's notice: one line per Mon-Sun week whose last first print landed
today or yesterday (the late step journals after the judgment run), and
nothing otherwise.
"""

import json
import os
import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parents[1]))
import portwatch  # noqa: E402

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from test_gap import run_claude_step_prompt  # noqa: E402

REPO = pathlib.Path(__file__).parents[2]
WEEK8 = {"2026-11-02": 2, "2026-11-03": 4, "2026-11-04": 5,
         "2026-11-05": 5, "2026-11-06": 6, "2026-11-07": 2,
         "2026-11-08": 3}


def journal(data: pathlib.Path, days: dict, seen: str, extra=()):
    path = data / "portwatch" / "hormuz.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [{"date": "2026-11-01", "n_total": 1,
             "seen_at": "2026-11-08T13:00:11+00:00"}]
    rows += [{"date": d, "n_total": n, "seen_at": seen}
             for d, n in days.items()]
    rows += list(extra)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return data


def test_week_completed_today_names_event_and_first_print_sum(tmp_path):
    data = journal(tmp_path, WEEK8, "2026-11-11T13:00:11+00:00")
    note = portwatch.news(data, "2026-11-11")
    assert "KXHORMUZWEEKLY-26NOV08" in note
    assert "2026-11-02..2026-11-08" in note
    assert "sum 27" in note
    assert "prereg.py score KXHORMUZWEEKLY" in note
    assert "unpublished" in note  # tells it to correct the stale note


def test_week_completed_yesterday_still_shows(tmp_path):
    # the late step can journal after the judgment run; next day must hear it
    data = journal(tmp_path, WEEK8, "2026-11-11T19:00:11+00:00")
    assert "KXHORMUZWEEKLY-26NOV08" in portwatch.news(data, "2026-11-12")


def test_older_completion_is_silent(tmp_path):
    data = journal(tmp_path, WEEK8, "2026-11-11T13:00:11+00:00")
    assert portwatch.news(data, "2026-11-13") == ""


def test_a_replayed_day_ignores_later_prints(tmp_path):
    # --today 11/10 must not announce a week first printed on 11/11
    data = journal(tmp_path, WEEK8, "2026-11-11T13:00:11+00:00")
    assert portwatch.news(data, "2026-11-10") == ""


def test_incomplete_week_is_silent(tmp_path):
    partial = {d: n for d, n in WEEK8.items() if d != "2026-11-08"}
    data = journal(tmp_path, partial, "2026-11-11T13:00:11+00:00")
    assert portwatch.news(data, "2026-11-11") == ""


def test_sum_uses_first_prints_not_revisions(tmp_path):
    revision = {"date": "2026-11-05", "n_total": 9, "revised_from": 5,
                "seen_at": "2026-11-11T13:00:11+00:00"}
    data = journal(tmp_path, WEEK8, "2026-11-11T13:00:11+00:00",
                   extra=[revision])
    assert "sum 27" in portwatch.news(data, "2026-11-11")


def test_revision_alone_does_not_announce_an_old_week(tmp_path):
    # week 8 first-printed 11/11; a revision on 11/18 isn't news
    revision = {"date": "2026-11-05", "n_total": 9, "revised_from": 5,
                "seen_at": "2026-11-18T13:00:11+00:00"}
    data = journal(tmp_path, WEEK8, "2026-11-11T13:00:11+00:00",
                   extra=[revision])
    assert portwatch.news(data, "2026-11-18") == ""


def test_missing_journal_is_silent(tmp_path):
    assert portwatch.news(tmp_path / "missing", "2026-11-11") == ""


def test_cli_prints_the_notice(tmp_path):
    data = journal(tmp_path, WEEK8, "2026-11-11T13:00:11+00:00")
    r = subprocess.run(
        [sys.executable, str(REPO / "kalshi" / "portwatch.py"), "news",
         str(data), "--today", "2026-11-11"],
        capture_output=True, text=True, timeout=30,
        env=dict(os.environ, KALSEER_DATA_DIR=str(tmp_path / "elsewhere")))
    assert r.returncode == 0, r.stderr
    assert "KXHORMUZWEEKLY-26NOV08" in r.stdout


def test_daily_prompt_carries_the_week_notice(tmp_path):
    data = journal(tmp_path / "data", WEEK8, "2026-11-11T13:00:11+00:00")
    # claude_step runs `news` against today's real date; journal it today
    today = portwatch._today().isoformat()
    path = data / "portwatch" / "hormuz.jsonl"
    path.write_text(path.read_text().replace("2026-11-11T", today + "T"))
    prompt = run_claude_step_prompt(tmp_path, data)
    assert prompt.startswith(f"Data directory: {data}\n")  # contract kept
    assert "KXHORMUZWEEKLY-26NOV08" in prompt
    assert (prompt.index("KXHORMUZWEEKLY-26NOV08")
            < prompt.index("# Kalshi daily judgment step"))
