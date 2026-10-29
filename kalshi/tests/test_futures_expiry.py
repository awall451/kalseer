"""futures.py archive: an expiring contract's final settle is journaled.

Watchlist 10/28: "HOX26 expires 10/30 -> compare like months (Z26)". The
archive step runs ~12Z, hours before that day's ~14:30 ET settle, so on
expiry day (Fri 10/30) HOX26's last bar is still live and skipped. From
Sat 10/31 on, the front month is Z26 and `archive` only fetched the front
and next months (Z26/F27), so `ulsd-X26` / `rbob-X26` would never get the
expiring contract's final settlement. `archive` now also journals any
month that was front within the last EXPIRED_DAYS, so the next run, or one
after a short gap, picks up that final day.
"""

import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parents[1]))
import futures
from test_futures import body, ts

DAYS = [26, 27, 28, 29, 30]


@pytest.fixture
def expired(tmp_path, monkeypatch):
    calls = []
    bodies = {}
    for sym, base in (("HO=F", 4.70), ("HOX26.NYM", 4.80), ("HOZ26.NYM", 4.70),
                      ("HOF27.NYM", 4.60), ("RB=F", 3.10),
                      ("RBX26.NYM", 3.20), ("RBZ26.NYM", 3.10),
                      ("RBF27.NYM", 3.00)):
        bodies[sym] = body(sym, [ts(x) for x in DAYS],
                           [round(base + x / 1000, 4) for x in DAYS])

    def fake_fetch(symbol):
        calls.append(symbol)
        if symbol not in bodies:
            raise OSError(f"no {symbol}")
        return bodies[symbol]
    monkeypatch.setattr(futures, "_fetch", fake_fetch)
    monkeypatch.setattr(futures, "DATA", tmp_path)
    return calls


def journal(name):
    path = futures.DATA / "futures" / f"{name}.jsonl"
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def test_day_after_expiry_journals_the_expired_months_final_settle(
        expired, monkeypatch, capsys):
    monkeypatch.setattr(futures, "_now", lambda: ts(31, 8))  # Sat 10/31
    futures.main(["archive"])
    assert journal("ulsd-X26")[-1] == {
        "date": "2026-10-30", "close": 4.83,
        "seen_at": journal("ulsd-X26")[-1]["seen_at"]}
    assert journal("rbob-X26")[-1]["date"] == "2026-10-30"
    assert journal("ulsd-Z26")[-1]["date"] == "2026-10-30"
    assert journal("ulsd-F27")[-1]["date"] == "2026-10-30"
    out = capsys.readouterr().out
    assert "futures archive: ulsd-X26 (HOX26.NYM): 5 new days" in out
    assert "futures archive: ulsd-F27 (HOF27.NYM): 5 new days" in out


def test_expiry_day_itself_still_fetches_only_front_and_next(
        expired, monkeypatch):
    monkeypatch.setattr(futures, "_now", lambda: ts(30, 8))  # Fri 10/30 12Z
    futures.main(["archive"])
    assert "HOF27.NYM" not in expired
    assert expired.count("HOX26.NYM") == 1


def test_expired_month_drops_out_after_the_lookback(expired, monkeypatch):
    monkeypatch.setattr(futures, "_now",
                        lambda: ts(31 + futures.EXPIRED_DAYS, 8))
    futures.main(["archive"])
    assert "HOX26.NYM" not in expired
    assert "RBX26.NYM" not in expired
    assert "HOZ26.NYM" in expired and "HOF27.NYM" in expired


def test_lookback_survives_a_dead_weekend_run(expired, monkeypatch):
    monkeypatch.setattr(futures, "_now", lambda: ts(33, 8))  # Mon 11/2
    futures.main(["archive"])
    assert journal("ulsd-X26")[-1]["date"] == "2026-10-30"
