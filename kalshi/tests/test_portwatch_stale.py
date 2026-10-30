"""portwatch.py: say what an ArcGIS error means, and how stale the journal is.

10/27 (a Tuesday, PortWatch's weekly publish day) the pipeline's archive got
`portwatch: arcgis error: Invalid URL` and skipped, and the judgment step's
own `calls --port Hormuz` got the same answer minutes later. The brief put it
down to "probably my port-name argument" and didn't retry. It wasn't: an
unknown port is a LIKE filter that returns zero rows ("# no published
days"). An error body is the server's answer to the query itself (quota, or
the hosted layer unavailable/republishing). Also, nothing in the log or in
`first` said that the newest journaled day (10/18) was now 9 days old, so a
source that keeps failing would go unnoticed until a settlement read came up
empty. PortWatch publishes weekly, so the newest day is normally <= ~10 days
old. Past STALE_DAYS, both commands flag it.
"""

import datetime
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from test_portwatch import FakeResponse, QUOTA_ERROR, api, portwatch  # noqa: F401

INVALID_URL = {"error": {"code": 400, "message": "Invalid URL",
                         "details": ["Invalid URL"]}}


@pytest.fixture
def journal(tmp_path, monkeypatch):
    monkeypatch.setattr(portwatch, "DATA", tmp_path)
    path = tmp_path / "portwatch" / "hormuz.jsonl"
    path.parent.mkdir()
    path.write_text("".join(json.dumps(
        {"date": d, "n_total": 4, "seen_at": "2026-10-20T12:00:11+00:00"})
        + "\n" for d in ("2026-10-17", "2026-10-18")))
    state = {"today": datetime.date(2026, 10, 27)}
    monkeypatch.setattr(portwatch, "_today", lambda: state["today"])
    return state


def error_reply(monkeypatch, body):
    monkeypatch.setattr(portwatch.urllib.request, "urlopen",
                        lambda req, timeout=30: FakeResponse(body))
    monkeypatch.setattr(portwatch.time, "sleep", lambda s: None)


def test_error_names_the_server_not_the_arguments(monkeypatch, capsys):
    error_reply(monkeypatch, INVALID_URL)
    with pytest.raises(SystemExit) as e:
        portwatch.main(["calls", "--port", "Hormuz"])
    assert e.value.code == 2
    err = capsys.readouterr().err
    assert "arcgis error 400: Invalid URL" in err
    # an unknown --port is zero rows, so this can't be the caller's spelling
    assert "not a bad --port" in err


def test_quota_error_keeps_its_server_message(monkeypatch, capsys):
    error_reply(monkeypatch, QUOTA_ERROR)
    with pytest.raises(SystemExit):
        portwatch.main(["calls"])
    assert "arcgis error 429: API calls quota exceeded" in (
        capsys.readouterr().err)


def test_skipped_archive_reports_the_journal_age(monkeypatch, journal,
                                                 capsys):
    error_reply(monkeypatch, INVALID_URL)
    portwatch.main(["archive"])  # still exit 0: one bad morning isn't a page
    out = capsys.readouterr().out
    assert "skipped" in out
    assert "newest journaled day 2026-10-18 (lag 9d)" in out
    assert "STALE" not in out


def test_archive_flags_a_stale_journal(monkeypatch, journal, capsys):
    journal["today"] = datetime.date(2026, 11, 1)
    error_reply(monkeypatch, INVALID_URL)
    portwatch.main(["archive"])
    out = capsys.readouterr().out
    assert "newest journaled day 2026-10-18 (lag 14d)" in out
    assert f"STALE (>{portwatch.STALE_DAYS}d" in out


def test_successful_archive_reports_the_new_newest_day(api, journal, capsys):
    api["response"] = {"features": [
        {"attributes": {"date": "2026-10-25", "n_total": 3}}]}
    portwatch.main(["archive"])
    out = capsys.readouterr().out
    assert "1 new days, 0 revised" in out
    assert "newest journaled day 2026-10-25 (lag 2d)" in out


def test_first_reports_the_journal_age_offline(journal, capsys):
    journal["today"] = datetime.date(2026, 11, 2)
    portwatch.main(["first"])
    out = capsys.readouterr().out.splitlines()
    assert "# newest journaled day 2026-10-18 (lag 15d)" in " ".join(out)
    assert any("STALE" in l for l in out if l.startswith("#"))


def test_first_with_since_still_reports_the_true_newest_day(journal, capsys):
    portwatch.main(["first", "--since", "2026-10-18"])
    out = capsys.readouterr().out
    assert "newest journaled day 2026-10-18 (lag 9d)" in out
