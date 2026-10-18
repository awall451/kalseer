"""futures.py archive / first: a daily journal of settled futures bars.

Brief 10/17: the 10/16 ULSD bar read 4.8991 while the same tool had shown
4.6550 live the morning before and a last trade of 4.7232; the judgment step
marked the day "UNVERIFIED - re-read futures.py next run and cross-check".
A re-read is only a cross-check if yesterday's read was kept. Like
portwatch.py archive (Hormuz first prints), the pipeline journals each
settled day's close the first time it is seen, and again whenever Yahoo
later serves a different close for that day, so a revised bar is visible
instead of silently replacing the number a board read leaned on.
"""

import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parents[1]))
import futures

EDT = -14400


def ts(day, hour=0):
    """Unix time of 2026-10-<day> <hour>:00 EDT."""
    return 1791849600 + (day - 13) * 86400 + hour * 3600 - EDT


def body(symbol, days, closes):
    return {"chart": {"error": None, "result": [{
        "meta": {"symbol": symbol, "gmtoffset": EDT,
                 "exchangeTimezoneName": "America/New_York"},
        "timestamp": [ts(d) for d in days],
        "indicators": {"quote": [{"close": closes}]}}]}}


@pytest.fixture
def yahoo(tmp_path, monkeypatch):
    state = {"now": ts(17, 8), "fail": set(), "calls": [], "bodies": {
        "RB=F": body("RB=F", [14, 15, 16], [3.2595, 3.1802, 3.2354]),
        "HO=F": body("HO=F", [15, 16, 17], [4.8456, 4.8991, 4.7000]),
    }}

    def fake_fetch(symbol):
        state["calls"].append(symbol)
        if symbol in state["fail"]:
            raise OSError("yahoo down")
        return state["bodies"][symbol]
    monkeypatch.setattr(futures, "_fetch", fake_fetch)
    monkeypatch.setattr(futures, "_now", lambda: state["now"])
    monkeypatch.setattr(futures, "DATA", tmp_path)
    return state


def journal(name):
    path = futures.DATA / "futures" / f"{name}.jsonl"
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def test_archive_journals_settled_days_for_the_board_symbols(yahoo, capsys):
    futures.main(["archive"])
    assert sorted(yahoo["calls"]) == ["HO=F", "RB=F"]
    assert [(r["date"], r["close"]) for r in journal("rbob")] == [
        ("2026-10-14", 3.2595), ("2026-10-15", 3.1802), ("2026-10-16", 3.2354)]
    out = capsys.readouterr().out
    assert "rbob: 3 new days, 0 revised" in out


def test_todays_live_bar_is_not_journaled(yahoo):
    # run at 08:00 ET 10/17: the 10/17 bar is live, not a settle
    futures.main(["archive"])
    assert [r["date"] for r in journal("ulsd")] == ["2026-10-15", "2026-10-16"]


def test_rerun_with_same_closes_adds_nothing(yahoo, capsys):
    futures.main(["archive"])
    futures.main(["archive"])
    assert len(journal("ulsd")) == 2
    assert "ulsd: 0 new days, 0 revised" in capsys.readouterr().out


def test_changed_close_is_journaled_as_a_revision(yahoo, capsys):
    futures.main(["archive"])
    yahoo["now"] = ts(18, 8)
    yahoo["bodies"]["HO=F"] = body("HO=F", [15, 16, 17],
                                   [4.8456, 4.7232, 4.7000])
    futures.main(["archive"])
    rows = journal("ulsd")
    assert rows[-2:] == [
        {"date": "2026-10-16", "close": 4.7232, "seen_at": rows[-2]["seen_at"],
         "revised_from": 4.8991},
        {"date": "2026-10-17", "close": 4.7, "seen_at": rows[-1]["seen_at"]}]
    assert "ulsd: 1 new days, 1 revised" in capsys.readouterr().out


def test_one_symbol_failing_still_journals_the_other(yahoo, capsys):
    yahoo["fail"].add("RB=F")
    futures.main(["archive"])
    assert len(journal("ulsd")) == 2
    out = capsys.readouterr()
    assert "rbob: failed" in out.out + out.err


def test_all_symbols_failing_exits_nonzero(yahoo):
    yahoo["fail"].update({"RB=F", "HO=F"})
    with pytest.raises(SystemExit) as e:
        futures.main(["archive"])
    assert e.value.code == 1


def test_bad_shape_for_one_symbol_does_not_abort_the_archive(yahoo):
    yahoo["bodies"]["RB=F"] = {"finance": {"error": "Too Many Requests"}}
    futures.main(["archive"])
    assert len(journal("ulsd")) == 2


def test_first_prints_first_and_latest_close_with_revisions(yahoo, capsys):
    futures.main(["archive"])
    yahoo["now"] = ts(18, 8)
    yahoo["bodies"]["HO=F"] = body("HO=F", [15, 16, 17],
                                   [4.8456, 4.7232, 4.7000])
    futures.main(["archive"])
    capsys.readouterr()
    futures.main(["first", "ulsd"])
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].startswith("2026-10-17  first 4.7000  latest 4.7000")
    assert lines[1].startswith("2026-10-16  first 4.8991  latest 4.7232")
    assert "(-0.1759)" in lines[1]
    assert "(" not in lines[2]
    assert lines[-1].startswith("# 1 of 3 days revised")


def test_first_without_a_journal_says_so(yahoo, capsys):
    futures.main(["first", "rbob"])
    assert "no journal" in capsys.readouterr().out


def test_first_needs_an_alias(yahoo):
    with pytest.raises(SystemExit) as e:
        futures.main(["first"])
    assert "archive" in str(e.value.code)
