"""portwatch.py archive --late: query again when a weekly batch is due.

PortWatch publishes weekly, on Tuesdays (10/20 first saw 10/13-10/19; the
10/28 run caught 10/19-10/25 only because 10/27 skipped). On Tue 11/3 the
~12:00Z archive answered `0 new days` at lag 9d and stamped today, so the
late step said `late retry not needed` and the 10/26-11/1 batch waited a day.
The batch can land after 12Z, and a day's wait risks journaling a revised
value where Kalshi settles on the first print (HAZARD 1c). So when the
journal is old enough that a batch is due (lag >= DUE_DAYS), the late step
spends its second query even after a clean morning. A fresh journal still
costs one query a day (HAZARD 1b).
"""

import datetime
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from test_portwatch import ROWS, portwatch  # noqa: F401
from test_portwatch_retry import server  # noqa: F401

NEWER = {"features": [{"attributes": {"date": "2026-09-17", "n_total": 6}}]}


def _pin_today(monkeypatch, day):
    monkeypatch.setattr(portwatch, "_today",
                        lambda: datetime.date.fromisoformat(day))


def test_due_days_is_a_tuesday_after_a_sunday_ending_week():
    # newest day Sunday, batch on Tuesday: lag 2 at publish, 8 on Monday
    # (normal), 9 on the Tuesday the next batch is due
    assert portwatch.DUE_DAYS == 9
    assert portwatch.DUE_DAYS <= portwatch.STALE_DAYS


def test_late_queries_again_when_a_batch_is_due(server, monkeypatch,
                                                tmp_path, capsys):
    _pin_today(monkeypatch, "2026-09-25")   # newest 9/16, lag 9d
    server["bodies"] = [ROWS, NEWER]
    portwatch.main(["archive"])
    capsys.readouterr()
    portwatch.main(["archive", "--late"])
    assert server["calls"] == 2
    out = capsys.readouterr().out
    assert "1 new days, 0 revised (late retry: weekly batch due)" in out
    assert "newest journaled day 2026-09-17" in out
    rows = (tmp_path / "portwatch" / "hormuz.jsonl").read_text().splitlines()
    assert len(rows) == 3


def test_late_skips_when_the_journal_is_fresh(server, monkeypatch, capsys):
    _pin_today(monkeypatch, "2026-09-24")   # lag 8d: a normal Monday
    server["bodies"] = [ROWS]
    portwatch.main(["archive"])
    capsys.readouterr()
    portwatch.main(["archive", "--late"])
    assert server["calls"] == 1
    assert "late retry not needed" in capsys.readouterr().out


def test_late_due_retry_still_retries_once_and_skips_cleanly(
        server, monkeypatch, tmp_path, capsys):
    from test_portwatch_retry import PARAMS_ERROR
    from test_portwatch import QUOTA_ERROR
    _pin_today(monkeypatch, "2026-09-25")
    server["bodies"] = [ROWS, PARAMS_ERROR, QUOTA_ERROR]
    portwatch.main(["archive"])
    capsys.readouterr()
    portwatch.main(["archive", "--late"])
    assert server["sleeps"] == [portwatch.RETRY_WAIT]
    out = capsys.readouterr().out
    assert "skipped (arcgis error twice" in out
    rows = (tmp_path / "portwatch" / "hormuz.jsonl").read_text().splitlines()
    assert len(rows) == 2


def test_plain_archive_ignores_the_due_rule(server, monkeypatch, capsys):
    _pin_today(monkeypatch, "2026-09-25")
    server["bodies"] = [ROWS, NEWER]
    portwatch.main(["archive"])
    portwatch.main(["archive"])
    assert server["calls"] == 2
    assert "weekly batch due" not in capsys.readouterr().out


@pytest.mark.parametrize("day,due", [("2026-09-24", False),
                                     ("2026-09-25", True)])
def test_batch_due_reads_the_journal_lag(server, monkeypatch, day, due):
    server["bodies"] = [ROWS]
    portwatch.main(["archive"])
    _pin_today(monkeypatch, day)
    assert portwatch.batch_due("Hormuz") is due


def test_batch_due_with_no_journal(server):
    assert portwatch.batch_due("Hormuz") is True
