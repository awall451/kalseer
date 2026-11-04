"""futures.py archive: an expired month Yahoo stopped serving isn't 'failed'.

The 11/2 and 11/3 runs logged `rbob-X26 (RBX26.NYM): failed: HTTP Error
404: Not Found` (ulsd-X26 too). The EXPIRED_DAYS lookback kept
fetching both after Yahoo dropped them, though their final 10/30 settles
were journaled on 10/31. Those lines read like a broken source every day
until the lookback ends. So a 404 on an already-expired month now names
the expiry and the journal's final day. It still says loudly if the final
settle never landed, the one case that IS lost data.
"""

import json
import pathlib
import sys
import urllib.error

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parents[1]))
import futures
from test_futures import body, ts

DAYS = [26, 27, 28, 29, 30]
LIVE = {"HO=F", "HOZ26.NYM", "HOF27.NYM", "RB=F", "RBZ26.NYM", "RBF27.NYM"}


@pytest.fixture
def gone(tmp_path, monkeypatch):
    """Yahoo serves the live months; the expired X26 months 404."""
    def fake_fetch(symbol):
        if symbol not in LIVE:
            raise urllib.error.HTTPError(symbol, 404, "Not Found", {}, None)
        return body(symbol, [ts(x) for x in DAYS], [4.0 + x / 1000
                                                     for x in DAYS])
    monkeypatch.setattr(futures, "_fetch", fake_fetch)
    monkeypatch.setattr(futures, "DATA", tmp_path)
    monkeypatch.setattr(futures, "_now", lambda: ts(34, 8))  # Tue 11/3
    return tmp_path


def seed(root, name, last_day):
    path = root / "futures" / f"{name}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"date": last_day, "close": 4.8,
                                "seen_at": "x"}) + "\n")


def test_expired_404_after_the_final_settle_is_not_a_failure(gone, capsys):
    seed(gone, "ulsd-X26", "2026-10-30")
    seed(gone, "rbob-X26", "2026-10-30")
    futures.main(["archive"])
    out = capsys.readouterr().out
    assert "X26.NYM): failed" not in out
    assert ("futures archive: ulsd-X26 (HOX26.NYM): expired 2026-10-30, "
            "no longer served; final journaled day 2026-10-30") in out
    assert "rbob-X26 (RBX26.NYM): expired 2026-10-30" in out


def test_expired_404_without_the_final_settle_says_it_was_missed(gone,
                                                                 capsys):
    seed(gone, "ulsd-X26", "2026-10-29")
    futures.main(["archive"])
    out = capsys.readouterr().out
    assert ("ulsd-X26 (HOX26.NYM): expired 2026-10-30, no longer served; "
            "final journaled day 2026-10-29 (FINAL SETTLE MISSED)") in out
    assert ("rbob-X26 (RBX26.NYM): expired 2026-10-30, no longer served; "
            "no journaled days (FINAL SETTLE MISSED)") in out


def test_a_404_on_a_live_month_is_still_a_failure(gone, monkeypatch, capsys):
    LIVE.discard("HOZ26.NYM")
    try:
        futures.main(["archive"])
    finally:
        LIVE.add("HOZ26.NYM")
    assert ("ulsd-Z26 (HOZ26.NYM): failed: HTTP Error 404"
            in capsys.readouterr().out)


def test_other_errors_on_an_expired_month_are_still_failures(
        gone, monkeypatch, capsys):
    def fake_fetch(symbol):
        if symbol not in LIVE:
            raise OSError("timed out")
        return body(symbol, [ts(x) for x in DAYS], [4.0] * len(DAYS))
    monkeypatch.setattr(futures, "_fetch", fake_fetch)
    futures.main(["archive"])
    assert ("ulsd-X26 (HOX26.NYM): failed: timed out"
            in capsys.readouterr().out)
