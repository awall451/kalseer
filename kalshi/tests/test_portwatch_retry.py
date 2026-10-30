"""portwatch.py archive: one retry, a fresh quota minute later.

The pipeline archive skipped on 10/27 (`arcgis error: Invalid URL`) and again
on 10/29 (`arcgis error 400: Cannot perform query. Invalid query
parameters.`). The 10/28 run, with the same query, journaled 7 new days, so
both errors were the server's passing state (quota, or the hosted layer
republishing). Each skip then waits a full day for the next run, and a
skip on a publish day costs the first print that Kalshi settles on. HAZARD
1b forbids retrying inside the same quota minute and forbids sleeping out
the window in the judgment step. The unattended archive step can afford one
wait past the window (RETRY_WAIT > 60s) and one more query. `calls` keeps
the no-sleep rule.
"""

import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from test_portwatch import FakeResponse, QUOTA_ERROR, ROWS, portwatch  # noqa: F401

PARAMS_ERROR = {"error": {"code": 400, "message": "Cannot perform query. "
                          "Invalid query parameters.", "details": []}}


@pytest.fixture
def server(tmp_path, monkeypatch):
    """Serve a scripted sequence of bodies; record any sleeps."""
    monkeypatch.setattr(portwatch, "DATA", tmp_path)
    state = {"bodies": [], "calls": 0, "sleeps": []}

    def fake_urlopen(req, timeout=30):
        state["calls"] += 1
        return FakeResponse(state["bodies"].pop(0))
    monkeypatch.setattr(portwatch.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(portwatch.time, "sleep", state["sleeps"].append)
    return state


def test_retry_wait_clears_the_quota_minute():
    assert portwatch.RETRY_WAIT > 60


def test_archive_retries_once_after_the_wait_and_journals(server, tmp_path,
                                                          capsys):
    server["bodies"] = [PARAMS_ERROR, ROWS]
    portwatch.main(["archive"])
    assert server["calls"] == 2
    assert server["sleeps"] == [portwatch.RETRY_WAIT]
    out = capsys.readouterr().out
    assert "2 new days, 0 revised" in out
    assert "after one retry" in out
    rows = (tmp_path / "portwatch" / "hormuz.jsonl").read_text().splitlines()
    assert len(rows) == 2


def test_archive_skips_when_the_retry_errors_too(server, tmp_path, capsys):
    server["bodies"] = [PARAMS_ERROR, QUOTA_ERROR]
    portwatch.main(["archive"])  # exit 0: still not a page
    assert server["calls"] == 2
    out = capsys.readouterr().out
    assert "skipped (arcgis error twice" in out
    assert not (tmp_path / "portwatch").exists()


def test_clean_archive_neither_sleeps_nor_says_retry(server, capsys):
    server["bodies"] = [ROWS]
    portwatch.main(["archive"])
    assert server["calls"] == 1
    assert server["sleeps"] == []
    assert "retry" not in capsys.readouterr().out


def test_calls_still_never_sleeps_out_the_window(server):
    server["bodies"] = [QUOTA_ERROR]
    with pytest.raises(SystemExit) as e:
        portwatch.main(["calls"])
    assert e.value.code == 2
    assert server["calls"] == 1
    assert server["sleeps"] == []
