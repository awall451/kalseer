"""fuelfreeze.py score: `--days N` counts back from today, not the month end.

The window used to count back from the newest frozen settlement day. Once
the month-end KXAAAGASM is frozen, that day is weeks out (11/10: 11/30). So
the default 14 days started at 11/16, and every settled daily fell outside
it. The 11/10 brief: "`fuelfreeze.py score` with no `--days` shows only
pending rows. Pass `--days 30` to see journal-scored events." The window
now ends at the newest frozen day that isn't in the future. Events after
it still print (as pending) because they are past `since`.
"""

import datetime as dt
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parents[1]))
import fuelfreeze


def rec(event, day):
    return {"event": event, "series": event.split("-")[0], "grade": "regular",
            "date": day, "k": 1,
            "strikes": [{"ticker": f"{event}-T3.95", "floor": 3.95,
                         "yes_bid": "0.4000", "yes_ask": "0.5000",
                         "p": {"RW": 1.0, "MOM": 1.0, "DRIFT": 1.0,
                               "EMP": None}}]}


def run(tmp_path, monkeypatch, capsys, recs, today, settled, days=None):
    journal = tmp_path / "fuel-freeze.jsonl"
    journal.write_text("".join(json.dumps(r) + "\n" for r in recs))
    monkeypatch.setattr(fuelfreeze, "JOURNAL", journal)
    monkeypatch.setattr(fuelfreeze, "_today",
                        lambda: dt.date.fromisoformat(today))
    monkeypatch.setattr(fuelfreeze, "_journal_print", lambda j, r: None)
    monkeypatch.setattr(fuelfreeze.kalshi, "get_event", lambda t: {
        "markets": [{"ticker": f"{t}-T3.95", "result": "yes",
                     "expiration_value": "3.9788"}] if t in settled else []})
    if days is None:
        fuelfreeze.score()
    else:
        fuelfreeze.score(days)
    return capsys.readouterr().out


RECS = [rec("KXAAAGASD-26NOV10", "2026-11-10"),
        rec("KXAAAGASD-26NOV11", "2026-11-11"),
        rec("KXAAAGASW-26NOV16", "2026-11-16"),
        rec("KXAAAGASM-26NOV30", "2026-11-30")]


def test_default_window_scores_settled_dailies_despite_a_month_end_freeze(
        tmp_path, monkeypatch, capsys):
    out = run(tmp_path, monkeypatch, capsys, RECS, "2026-11-11",
              {"KXAAAGASD-26NOV10"})
    assert "2026-11-10  KXAAAGASD-26NOV10  3.9788  k1" in out
    assert "# n=1 settled events (last 14d)" in out
    # later events are past `since`, so they still show as pending
    assert "2026-11-30  KXAAAGASM-26NOV30  k1  pending" in out
    assert "2026-11-16  KXAAAGASW-26NOV16  k1  pending" in out


def test_window_counts_back_from_today(tmp_path, monkeypatch, capsys):
    old = rec("KXAAAGASD-26OCT20", "2026-10-20")
    out = run(tmp_path, monkeypatch, capsys, [old] + RECS, "2026-11-11",
              {"KXAAAGASD-26NOV10", "KXAAAGASD-26OCT20"}, days=14)
    assert "KXAAAGASD-26OCT20" not in out
    out = run(tmp_path, monkeypatch, capsys, [old] + RECS, "2026-11-11",
              {"KXAAAGASD-26NOV10", "KXAAAGASD-26OCT20"}, days=30)
    assert "2026-10-20  KXAAAGASD-26OCT20  3.9788" in out
    assert "# n=2 settled events (last 30d)" in out


def test_an_old_journal_still_anchors_on_its_newest_event(tmp_path,
                                                          monkeypatch, capsys):
    """A journal whose events are all long past (a replay, a test fixture)
    keeps anchoring on its own newest event, not on an empty window."""
    recs = [rec("KXAAAGASD-26OCT10", "2026-10-10"),
            rec("KXAAAGASD-26OCT21", "2026-10-21")]
    out = run(tmp_path, monkeypatch, capsys, recs, "2027-03-01",
              {"KXAAAGASD-26OCT10", "KXAAAGASD-26OCT21"})
    assert "# n=2 settled events (last 14d)" in out


def test_a_journal_of_only_future_events_still_lists_them(tmp_path,
                                                          monkeypatch, capsys):
    out = run(tmp_path, monkeypatch, capsys, RECS[2:], "2026-11-11", set())
    assert "KXAAAGASW-26NOV16  k1  pending" in out
    assert "KXAAAGASM-26NOV30  k1  pending" in out
