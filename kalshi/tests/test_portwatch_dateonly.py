"""portwatch.py archive: an empty window the journal already covers is our
where clause, not PortWatch; retry it once with a DATE literal.

#117's 11/7 line answered the field question: date, portname and n_total
are all present, but `date` is now esriFieldTypeDateOnly (schema edited
11/6 18:04Z). The same day both queries were answered (no 429) and logged
`0 new days, 0 revised`, which can't tell "45 rows, nothing new" from "zero
rows". Our filter is `date >= TIMESTAMP '…'`, and ArcGIS spells date-only
literals `DATE 'YYYY-MM-DD'`. The 45-day window always overlaps a journal
younger than 45 days, so zero rows there means the clause matched nothing.
That case alone spends one more query with `DATE`, and the line says how
many rows each query answered.
"""

import datetime
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from test_portwatch import portwatch  # noqa: F401
from test_portwatch_layer import _layer, _pin, api  # noqa: F401

SINCE = (datetime.datetime.now(tz=datetime.timezone.utc).date()
         - datetime.timedelta(days=45))


def _day(offset):
    return (SINCE + datetime.timedelta(days=offset)).isoformat()


def _seed_window(tmp_path):
    """Two journaled days inside the archive's 45-day window."""
    path = tmp_path / "portwatch" / "hormuz.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(
        json.dumps({"date": _day(d), "n_total": 3,
                    "seen_at": "2026-10-28T12:00:11+00:00"}) + "\n"
        for d in (5, 6)))


def _rows(*offsets):
    return {"features": [{"attributes": {"date": _day(d), "n_total": 3}}
                         for d in offsets]}


def _wheres(api):
    return [u for u in api["urls"] if "/query?" in u]


def test_empty_window_over_journaled_days_retries_with_a_date_literal(
        api, tmp_path, monkeypatch, capsys):
    _seed_window(tmp_path)
    api["bodies"] = [{"features": []}, _rows(5, 6, 7)]
    assert portwatch.archive("Hormuz") == (1, 0)
    first, second = _wheres(api)
    assert "TIMESTAMP" in first and "TIMESTAMP" not in second
    assert f"date+%3E%3D+DATE+%27{SINCE}%27" in second


def test_the_line_names_the_empty_answer_and_the_retry(api, tmp_path,
                                                        monkeypatch, capsys):
    _seed_window(tmp_path)
    _pin(monkeypatch, _day(7))
    api["bodies"] = [{"features": []}, _rows(5, 6, 7)]
    portwatch.main(["archive"])
    out = capsys.readouterr().out
    assert "1 new days, 0 revised" in out
    assert (f"TIMESTAMP query answered 0 rows though the journal holds 2 "
            f"days since {SINCE}; DATE retry answered 3 rows "
            f"(newest {_day(7)})") in out


def test_both_literals_empty_says_the_clause_matches_nothing(
        api, tmp_path, monkeypatch, capsys):
    _seed_window(tmp_path)
    _pin(monkeypatch, _day(7))
    api["bodies"] = [{"features": []}, {"features": []}]
    portwatch.main(["archive"])
    out = capsys.readouterr().out
    assert "0 new days, 0 revised" in out
    assert "DATE retry answered 0 rows too" in out
    assert len(_wheres(api)) == 2


def test_rows_answered_spend_no_retry(api, tmp_path, monkeypatch, capsys):
    _seed_window(tmp_path)
    _pin(monkeypatch, _day(7))
    api["bodies"] = [_rows(5, 6)]
    portwatch.main(["archive"])
    assert len(_wheres(api)) == 1
    assert "retry" not in capsys.readouterr().out


def test_empty_window_with_no_journaled_days_in_it_is_a_publication_answer(
        api, tmp_path, monkeypatch, capsys):
    _pin(monkeypatch, _day(7))   # lag 7d on an empty journal: batch due
    api["bodies"] = [{"features": []}]
    api["layer"] = _layer("2026-09-17T20:00:00+00:00",
                          "2026-08-01T00:00:00+00:00")
    portwatch.main(["archive"])
    assert len(_wheres(api)) == 1
    assert "DATE retry" not in capsys.readouterr().out


def test_a_due_batch_that_did_not_show_says_how_many_rows_came_back(
        api, tmp_path, monkeypatch, capsys):
    _seed_window(tmp_path)
    _pin(monkeypatch, _day(6 + portwatch.DUE_DAYS))
    api["bodies"] = [_rows(5, 6)]
    api["layer"] = _layer("2026-09-17T20:00:00+00:00",
                          "2026-08-01T00:00:00+00:00")
    portwatch.main(["archive"])
    out = capsys.readouterr().out
    assert f"0 new days, 0 revised; query answered 2 rows (newest {_day(6)})" \
        in out
