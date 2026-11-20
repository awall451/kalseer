"""prereg.py odds: each forecaster's P(print > strike) on a daily fuel board.

Every daily fuel pass prices the board by hand off a point and a remembered
error: brief 11/18 "MINE (sd ~0.64c from MAE 0.51) puts P(>5.935) ~0.30 vs
ask 0.09"; 11/19 "MINE puts YES T5.900 at ~0.73 vs ask 0.06" and "On MOM
(sd ~0.75c) P(>3.690) ~0.62 vs ask 0.42" - one day sd = 1.25 x MAE, the next
sd = MAE. `odds` does it the same way every time: a normal around each
forecast (the event's frozen points, LEG=VALUE extras, fuelscore's RW / MOM /
DRIFT / WKDAY) with sd = sqrt(pi/2) x that forecaster's MAE over the
series' scored pre-regs in the 30 days before the print, and the edge
against the live book.
"""

import json
import math
import pathlib
import sys
from datetime import date, timedelta
from decimal import Decimal

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parents[1]))
import fuelscore
import prereg

# 11/01..11/19 diesel prints; uneven changes
DIESEL = ["6.0500", "6.0460", "6.0430", "6.0370", "6.0340", "6.0300",
          "6.0250", "6.0220", "6.0160", "6.0110", "6.0080", "6.0010",
          "5.9950", "5.9900", "5.9840", "5.9790", "5.9660", "5.9594",
          "5.9298"]
EVENT = "KXDIESELD-26NOV20"
SD = 0.0040 * math.sqrt(math.pi / 2)  # the history's MAE is 0.40c


def _day(i):
    return (date(2026, 11, 1) + timedelta(days=i)).isoformat()


def _event(day):
    d = date.fromisoformat(day)
    return f"KXDIESELD-{d:%y}{d:%b}{d:%d}".upper()


def _p(strike, centre, sd=SD):
    return 0.5 * (1 - math.erf((strike - centre) / (sd * math.sqrt(2))))


def mkt(strike, bid, ask):
    return {"ticker": f"{EVENT}-T{strike}", "yes_bid_dollars": bid,
            "yes_ask_dollars": ask, "strike_type": "greater",
            "floor_strike": float(strike), "status": "active",
            "close_time": "2026-11-21T03:59:00Z"}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(prereg, "JOURNAL", tmp_path / "preregs.jsonl")
    prints = tmp_path / "prints.jsonl"
    prints.write_text("".join(
        json.dumps({"date": _day(i), "prices": {"current": {
            "diesel": f"${d}"}}}) + "\n" for i, d in enumerate(DIESEL)))
    monkeypatch.setattr(fuelscore, "JOURNAL", prints)
    board = {EVENT: {"markets": [
        mkt("5.900", "0.0400", "0.0600"), mkt("5.890", "0.8600", "0.9000"),
        mkt("5.895", "0.0000", "0.0000")]}}
    monkeypatch.setattr(prereg.kalshi, "get_event", lambda t: board[t])
    return board


def _write(rows):
    prereg.JOURNAL.write_text("".join(json.dumps(r) + "\n" for r in rows))


def _point(event, value, leg="MINE", at="2026-11-19T13:04:00+00:00"):
    return {"event": event, "leg": leg, "at": at, "point": value,
            "board": {}}


def _history(n=6, off="0.0040"):
    """n scored MINE points ending 11/19, each 0.40c off (signs alternate)."""
    out = []
    for i in range(n):
        day = _day(18 - i)
        value = Decimal(DIESEL[18 - i]) + Decimal(off) * (1 if i % 2 else -1)
        out.append(_point(_event(day), f"{value:.4f}",
                          at=f"{day}T00:00:00+00:00"))
    return out


def _run(capsys, *extra):
    capsys.readouterr()
    prereg.main(["odds", EVENT, *extra])
    return capsys.readouterr().out.splitlines()


def _strike(out, strike):
    return next(l for l in out if l.startswith(f"T{strike} "))


def test_odds_sd_is_sqrt_pi_over_2_times_the_scored_mae(env, capsys):
    _write(_history() + [_point(EVENT, "5.9000")])
    out = _run(capsys)
    assert out[0].startswith(f"# odds {EVENT}: P(print > strike)")
    assert f"MINE 5.9000 sd {SD * 100:.2f}c (MAE 0.40c n6)" in out[1]
    # strikes come lowest first, whatever order the board lists them
    assert [l.split()[0] for l in out[2:]] == ["T5.890", "T5.895", "T5.900"]
    assert "MINE 0.50" in _strike(out, "5.900")  # the strike is the centre
    assert f"MINE {_p(5.890, 5.900):.2f}" in _strike(out, "5.890")


def test_odds_prints_the_yes_edge_against_the_ask(env, capsys):
    _write(_history())
    out = _run(capsys, "MINE=5.9036")
    line = _strike(out, "5.900")
    # the 11/19 diesel case: MINE well above a 0.06 ask
    p = _p(5.900, 5.9036)
    assert line.startswith("T5.900  0.0400/0.0600  ")
    assert f"MINE* {p:.2f} YES+{p - 0.06:.2f}" in line


def test_odds_prints_the_no_edge_under_the_bid(env, capsys):
    _write(_history())
    out = _run(capsys, "LOW=5.8800", "MINE=5.8800")
    p = _p(5.890, 5.8800)
    assert f"MINE* {p:.2f} NO+{0.86 - p:.2f}" in _strike(out, "5.890")


def test_odds_an_empty_book_has_no_edge(env, capsys):
    _write(_history())
    line = _strike(_run(capsys, "MINE=5.9036"), "5.895")
    assert line.startswith("T5.895  unpriced  ")
    assert "YES+" not in line and "NO+" not in line


def test_odds_frozen_points_beat_extras_and_extras_are_starred(env, capsys):
    _write(_history() + [_point(EVENT, "5.9036")])
    out = _run(capsys, "MINE=5.9999", "ALT=5.9010")
    assert "MINE 5.9036 sd" in out[1]
    assert "MINE*" not in out[1]
    # ALT has no scored history: shown, but no odds
    assert "ALT* 5.9010 (n0: no odds)" in out[1]
    assert out[1].endswith("(* not frozen)")
    assert "ALT" not in _strike(out, "5.900")


def test_odds_adds_fuelscore_models_with_their_own_mae(env, capsys):
    _write(_history())
    out = _run(capsys)
    prices = dict(fuelscore.series("diesel"))
    mom = fuelscore.forecasts(prices, "2026-11-19", prereg.FUEL_WINDOW)["MOM"]
    errs = [abs(prices[_day(18 - i)] - fuelscore.forecasts(
        prices, _day(17 - i), prereg.FUEL_WINDOW)["MOM"]) for i in range(6)]
    mae = float(sum(errs) / len(errs))
    sd = mae * math.sqrt(math.pi / 2)
    assert (f"MOM {mom:.4f} sd {sd * 100:.2f}c (MAE {mae * 100:.2f}c n6)"
            in out[1])
    assert f"MOM {_p(5.900, float(mom), sd):.2f}" in _strike(out, "5.900")


def test_odds_needs_odds_min_scored_errors(env, capsys):
    _write(_history(n=prereg.ODDS_MIN - 1))
    out = _run(capsys, "MINE=5.9036")
    assert f"MINE* 5.9036 (n{prereg.ODDS_MIN - 1}: no odds)" in out[1]
    assert "MINE" not in _strike(out, "5.900")


def test_odds_window_is_the_days_before_the_print(env, capsys, monkeypatch):
    # a point for the target print itself, a later one and a gas one never count
    _write(_history() + [
        _point(EVENT, "5.9900"),
        _point("KXDIESELD-26NOV21", "5.9900"),
        _point("KXAAAGASD-26NOV19", "3.0000")])
    assert "(MAE 0.40c n6)" in _run(capsys)[1]
    monkeypatch.setattr(prereg, "ODDS_DAYS", 3)  # 11/17..11/19 only
    assert "(MAE 0.40c n3: no odds)" not in _run(capsys)[1]
    assert "(n3: no odds)" in _run(capsys)[1]


def test_odds_refuses_a_non_daily_fuel_event(env):
    with pytest.raises(SystemExit) as e:
        prereg.main(["odds", "KXDIESELW-26NOV23"])
    assert "KXAAAGASD" in str(e.value)


def test_prompt_names_the_odds_verb():
    prompt = (pathlib.Path(__file__).parents[2] / "bin"
              / "daily-prompt.md").read_text()
    assert "prereg.py odds EVENT [MINE=5.9036]" in prompt
