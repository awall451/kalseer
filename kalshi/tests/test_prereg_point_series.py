"""prereg.py score: point summaries per series, with MINE vs MOM head-to-head.

The '# MINE point' summary was keyed by leg alone, so the unprefixed
`score` the judgment step runs pooled gas and diesel into one MAE (11/5:
"MINE point: n=28") and would add a KXPAYROLLS point's error in jobs to
fuel errors in dollars. Brief 11/5 also opened a diesel retirement watch:
"MOM has beaten my discretionary diesel layer two days running ... if MOM
wins 3 of the next 5, diesel MINE becomes MOM". That is a head-to-head
count, and the '-> best' column (closest of all four models) can't give it:
on 11/3 DRIFT was best, but MINE beat MOM. So each series gets its own
line, and the fuel ones count MINE vs MOM with the last 5 shown newest first.
"""

import json
import pathlib
import sys
from datetime import date, timedelta
from decimal import Decimal

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parents[1]))
import fuelscore
import prereg

# 10/15..10/27; uneven changes so MOM rarely lands exactly
DIESEL = ["6.3250", "6.3240", "6.3220", "6.3190", "6.3180", "6.3160",
          "6.3135", "6.3100", "6.3090", "6.3040", "6.3030", "6.2990",
          "6.2985"]
REGULAR = ["4.2500", "4.2450", "4.2420", "4.2400", "4.2350", "4.2330",
           "4.2300", "4.2280", "4.2210", "4.2200", "4.2150", "4.2120",
           "4.2100"]


def _day(i):
    return (date(2026, 10, 15) + timedelta(days=i)).isoformat()


def _event(series, day):
    d = date.fromisoformat(day)
    return f"{series}-{d:%y}{d:%b}{d:%d}".upper()


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(prereg, "JOURNAL", tmp_path / "preregs.jsonl")
    prints = tmp_path / "prints.jsonl"
    prints.write_text("".join(
        json.dumps({"date": _day(i), "prices": {"current": {
            "diesel": f"${d}", "regular": f"${r}"}}}) + "\n"
        for i, (d, r) in enumerate(zip(DIESEL, REGULAR))))
    monkeypatch.setattr(fuelscore, "JOURNAL", prints)
    # no fuel event settled on Kalshi: those score off the AAA journal
    payrolls = [{"ticker": "KXPAYROLLS-26SEP-T50000", "result": "no",
                 "expiration_value": "29,000"}]
    monkeypatch.setattr(prereg.kalshi, "get_event", lambda t: {
        "markets": payrolls if t.startswith("KXPAYROLLS") else []})
    return tmp_path


def _freeze(rows):
    prereg.JOURNAL.write_text("".join(json.dumps(r) + "\n" for r in rows))


def _point(event, value, at):
    return {"event": event, "leg": "MINE", "at": at, "point": value,
            "board": {}}


def _vs_mom(series, day, how):
    """A MINE point for `day`'s print that beats MOM, loses to it or ties."""
    event = _event(series, day)
    mom = prereg._fuel_models(event)["MOM"]
    actual = prereg._journal_print(event)
    value = {"beat": actual, "tie": mom,
             "lose": mom + (mom - actual) + (Decimal("0.0100") if mom >= actual
                                              else Decimal("-0.0100"))}[how]
    at = (date.fromisoformat(day) - timedelta(days=1)).isoformat()
    return _point(event, f"{value:.4f}", at + "T12:05:00+00:00")


def _summary(capsys):
    return [l for l in capsys.readouterr().out.splitlines()
            if l.startswith("# MINE point")]


def test_points_summarise_per_series(env, capsys):
    _freeze([_vs_mom("KXDIESELD", _day(9), "beat"),
             _vs_mom("KXAAAGASD", _day(9), "lose"),
             _point("KXPAYROLLS-26SEP", "100000",
                    "2026-10-24T12:00:00+00:00")])
    prereg.score()
    lines = _summary(capsys)
    assert len(lines) == 3
    gas = next(l for l in lines if l.startswith("# MINE point KXAAAGASD:"))
    diesel = next(l for l in lines if l.startswith("# MINE point KXDIESELD:"))
    assert "n=1," in gas and "n=1," in diesel
    assert "MINE MAE 0.0000 best 1" in diesel
    assert "MINE MAE 0.0000" not in gas


def test_fuel_series_count_mine_against_mom(env, capsys):
    outcomes = ["beat", "lose", "lose", "tie", "beat", "lose"]
    _freeze([_vs_mom("KXDIESELD", _day(7 + i), how)
             for i, how in enumerate(outcomes)])
    prereg.score()
    (line,) = _summary(capsys)
    assert "MINE vs MOM: MINE closer 2, MOM closer 3, tied 1" in line
    # the last five, newest first: lose beat tie lose lose
    assert line.endswith("last 5 newest first: MOM MINE tie MOM MOM")


def test_fewer_than_five_shows_what_there_is(env, capsys):
    _freeze([_vs_mom("KXDIESELD", _day(8), "lose"),
             _vs_mom("KXDIESELD", _day(9), "beat")])
    prereg.score()
    (line,) = _summary(capsys)
    assert line.endswith("last 2 newest first: MINE MOM")


def test_non_fuel_points_carry_no_head_to_head(env, capsys):
    _freeze([_point("KXPAYROLLS-26SEP", "100000",
                    "2026-10-24T12:00:00+00:00")])
    prereg.score()
    (line,) = _summary(capsys)
    assert line == "# MINE point KXPAYROLLS: n=1, MAE 71000.0000"
