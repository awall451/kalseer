"""highfreeze.py score: a bucket-label expiration_value doesn't crash score.

KXHIGHLAX-26OCT22, the HELD day (CLILAX revised 71 -> 72 -> 71 across the
B70.5 / T71 edge), finally settled after op-10-27 with every market's
expiration_value set to the winning bucket's label, '70° to 71°', not a
number like the '77.00' on every other day. `score` did float() on it and
died with a ValueError, so on 10/28 the whole KXHIGH ledger went dark
(every city, every day), not just that row. A non-numeric value now prints
verbatim: the day has no grid error (the max isn't known to the degree),
but RAW / MKT / BIAS still score off Kalshi's `result`, which is all
they need.
"""

import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parents[1]))
import highfreeze
from test_highfreeze_bias import buckets, event

DAY, NEXT = "2026-10-22", "2026-10-23"


@pytest.fixture
def labelled(tmp_path, monkeypatch):
    journal = tmp_path / "high-freeze.jsonl"
    journal.write_text("".join(json.dumps(
        {"city": "LAX", "date": d, "event": event(d), "high": 76,
         "buckets": buckets(d)}) + "\n" for d in (DAY, NEXT)))
    monkeypatch.setattr(highfreeze, "JOURNAL", journal)
    monkeypatch.setattr(highfreeze, "EXTRA", {}, raising=False)
    values = {event(DAY): "76° to 77°", event(NEXT): "77.00"}

    def get_event_by_day(ticker):
        day = DAY if ticker == event(DAY) else NEXT
        return {"markets": [
            {"ticker": b["ticker"], "expiration_value": values[ticker],
             "result": "yes" if b["ticker"].endswith("B76.5") else "no"}
            for b in buckets(day)]}
    monkeypatch.setattr(highfreeze.kalshi, "get_event", get_event_by_day)


def lines(capsys):
    return capsys.readouterr().out.splitlines()


def test_label_value_does_not_crash_and_prints_verbatim(labelled, capsys):
    highfreeze.score()
    out = lines(capsys)
    row = next(l for l in out if l.startswith(DAY))
    assert row.startswith(f"{DAY}  LAX  76° to 77°  grid 76 err -  ")
    assert "(bucket label: no grid error)" in row
    assert "RAW p " in row and "MKT p 0.4500" in row


def test_label_day_has_no_grid_error_but_still_scores(labelled, capsys):
    highfreeze.score()
    out = lines(capsys)
    # the numeric day still gets its error (76 vs 77)
    assert any(l.startswith(f"{NEXT}  LAX  77  grid 76 err -1") for l in out)
    assert any(l.startswith("# LAX: n=1 grid bias -1.0F") for l in out)
    summary = next(l for l in out if l.startswith("# n="))
    # one grid error; both days' RAW / MKT Brier are tallied (MKT: 0.4500 on
    # the winner both days, so the mean equals the single-day Brier)
    assert summary.startswith("# n=1 ") and "grid bias -1.0F" in summary
    row = next(l for l in out if l.startswith(NEXT))
    mkt = row.split("MKT p 0.4500 B ")[1].split()[0]
    assert f"MKT B {mkt}" in summary


def test_numeric_values_keep_their_old_shape(labelled, capsys):
    assert highfreeze._settled_max("77.00") == 77.0
    assert highfreeze._settled_max("71") == 71.0
    assert highfreeze._settled_max("70° to 71°") is None
