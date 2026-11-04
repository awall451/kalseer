"""portwatch.py archive --late: a second chance minutes later in the run.

Even with #103's one retry 65s later, the morning archive skipped on 10/27,
10/29 and 10/31 (`arcgis error 400: Invalid URL` twice, 65s apart), and the
10/30 run only got through on its retry. That's four of the last five runs
erroring at ~12:00Z, after ten clean days. The journal's newest day is still 10/25
(lag 6d), and the Hormuz week-7 score on 11/3 needs 10/26-11/1 journaled.
A failure that outlasts 65s may still clear in the ~6 minutes the
judgment step takes, so daily.sh runs `archive --late` after it. When the
morning archive already succeeded today, the late step makes no query at all, so
a normal day still spends one query (HAZARD 1b).
"""

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from test_portwatch import QUOTA_ERROR, ROWS, portwatch  # noqa: F401
from test_portwatch_retry import PARAMS_ERROR, server  # noqa: F401


def test_successful_archive_stamps_today(server, tmp_path):
    server["bodies"] = [ROWS]
    portwatch.main(["archive"])
    stamp = tmp_path / "portwatch" / "hormuz.archived"
    assert stamp.read_text().strip() == portwatch._today().isoformat()


def test_skipped_archive_leaves_no_stamp(server, tmp_path):
    server["bodies"] = [PARAMS_ERROR, QUOTA_ERROR]
    portwatch.main(["archive"])
    assert not (tmp_path / "portwatch" / "hormuz.archived").exists()


def test_late_makes_no_query_after_a_clean_morning(server, monkeypatch,
                                                   capsys):
    # a fresh journal (newest 9/16, lag 1d); a due batch queries again
    monkeypatch.setattr(portwatch, "_today",
                        lambda: portwatch.datetime.date(2026, 9, 17))
    server["bodies"] = [ROWS]
    portwatch.main(["archive"])
    capsys.readouterr()
    portwatch.main(["archive", "--late"])
    assert server["calls"] == 1
    out = capsys.readouterr().out
    assert "late retry not needed" in out
    assert "newest journaled day" in out


def test_late_archives_after_a_skipped_morning(server, tmp_path, capsys):
    server["bodies"] = [PARAMS_ERROR, QUOTA_ERROR, ROWS]
    portwatch.main(["archive"])
    capsys.readouterr()
    portwatch.main(["archive", "--late"])
    assert server["calls"] == 3
    out = capsys.readouterr().out
    assert "2 new days, 0 revised (late retry)" in out
    rows = (tmp_path / "portwatch" / "hormuz.jsonl").read_text().splitlines()
    assert len(rows) == 2


def test_late_ignores_a_stale_stamp(server, tmp_path, capsys):
    (tmp_path / "portwatch").mkdir()
    (tmp_path / "portwatch" / "hormuz.archived").write_text("2026-10-30\n")
    server["bodies"] = [ROWS]
    portwatch.main(["archive", "--late"])
    assert server["calls"] == 1
    assert "2 new days" in capsys.readouterr().out


def test_late_still_retries_once_and_skips_cleanly(server, tmp_path, capsys):
    server["bodies"] = [PARAMS_ERROR, QUOTA_ERROR]
    portwatch.main(["archive", "--late"])
    assert server["sleeps"] == [portwatch.RETRY_WAIT]
    assert "skipped (arcgis error twice" in capsys.readouterr().out


def test_late_is_archive_only():
    with pytest.raises(SystemExit):
        portwatch.main(["calls", "--late"])


def test_daily_runs_the_late_step_after_the_judgment_step():
    sh = (pathlib.Path(__file__).parents[2] / "bin" / "daily.sh").read_text()
    late = sh.index("run_step portwatch-late python3 kalshi/portwatch.py "
                    "archive --late")
    assert sh.index("run_step portwatch python3") < sh.index(
        "run_step claude ") < late < sh.index("git -C \"$DATA_DIR\" add -A")
