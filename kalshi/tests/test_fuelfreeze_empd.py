"""fuelfreeze.py: EMPD, the EMP distribution centred on DRIFT.

daily-2026-10-21.log, the first EMP freeze: gas had fallen 9 straight prints
(brief 10/21: "last-10 mean -0.94c/day"), yet EMP put KXAAAGASW-26OCT26 >4.28
at 0.40 against a 0.03 board. The 90-day k-print changes carry September's
run-up as their own drift. A board-EMP loss can't tell "fat tails are wrong"
from "the history's drift is wrong". EMPD keeps EMP's tails and swaps the
history's mean for DRIFT's k-print move.
"""

import json
import pathlib
import sys
from decimal import Decimal

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parents[1]))
import fuelfreeze
from test_fuelfreeze_emp import apis, frozen_week  # noqa: F401


def test_empd_shifts_the_changes_by_drift_less_their_mean():
    changes = [Decimal("0.0100")] * 9 + [Decimal("0.1100")]  # mean 2c
    base = Decimal("4.0000")
    # no shift: base - 2c + change; > 4.0050 only for the 11c change
    assert fuelfreeze._p_empd(4.005, base, changes, Decimal("0")) \
        == pytest.approx(1.5 / 11)
    # a +2c DRIFT move restores the raw EMP placement
    assert fuelfreeze._p_empd(4.005, base, changes, Decimal("0.0200")) \
        == pytest.approx(fuelfreeze._p_emp(4.005, base, changes))
    assert fuelfreeze._p_empd(4.005, base, changes, None) is None
    assert fuelfreeze._p_empd(4.005, base, changes[:5], Decimal("0")) is None


def test_freeze_journals_empd_next_to_emp(apis):
    fuelfreeze.freeze()
    r = frozen_week()
    lo, hi = r["strikes"]
    # 29 two-print changes, mean 0.95c/29; DRIFT's 2-print move is 2 x 0.8c.
    # > base + 1.5c needs change > 1.5 - 1.6 + 3.276c: only the two 21c jumps
    assert lo["p"]["EMPD"] == pytest.approx(2.5 / 30)
    assert lo["p"]["EMP"] == pytest.approx(28.5 / 30)
    assert hi["p"]["EMPD"] == pytest.approx(2.5 / 30)


def test_empd_enters_the_divergences_and_the_tally(apis, monkeypatch,
                                                   capsys):
    fuelfreeze.freeze()
    rec = frozen_week()
    lines = fuelfreeze.divergences(rec)
    # board 0.45 at > base + 1.5c: EMPD 0.08 is >= 0.25 away
    assert any("EMPD 0.08" in l for l in lines)
    monkeypatch.setattr(fuelfreeze.kalshi, "get_event", lambda t: {
        "markets": [{"ticker": s["ticker"], "result": "no",
                     "expiration_value": "6.3000"} for s in rec["strikes"]]})
    fuelfreeze.score()
    out = capsys.readouterr().out
    assert "EMPD " in [l for l in out.splitlines()
                       if "KXDIESELW-26OCT22" in l][0]
    # both strikes: board 0.45 vs EMPD 0.08, both settled NO -> EMPD twice
    assert "board-EMPD 0-2" in out
