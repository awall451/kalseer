"""The econfreeze step's log line carries the board's implied median.

fuelfreeze's step log prints each event's board centre (#120), but the
econfreeze step printed only 'KXCPI-26OCT T-1 (12 strikes)', so the 11/9
brief read the CPI median by eye ("a median of ~0.227 at T-1"). The NFP
MINE is the board's T-1 median (brief 11/7), so the morning log should
say it. Same rule and precision as `moves`' '# board median:' line.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parents[1]))
import econfreeze
from test_econfreeze import board, market  # noqa: F401 (fixture)


def test_step_line_carries_the_median(board, capsys):
    econfreeze.freeze()
    out = capsys.readouterr().out.splitlines()
    # T0 0.86 -> T50000 0.42: 50000 * 0.36 / 0.44 = 40909
    assert out == ["  KXPAYROLLS-26OCT T-7 (3 strikes)  median 40909"]


def test_step_line_marks_an_off_ladder_or_unpriced_median(board, capsys):
    board["markets"]["KXPAYROLLS-26OCT"] = [
        market("KXCPI-26OCT-T0.2", 0.2, "0.3000", "0.3200"),
        market("KXCPI-26OCT-T0.3", 0.3, "0.1000", "0.1200")]
    econfreeze.freeze()
    assert capsys.readouterr().out.endswith("(2 strikes)  median <0.200\n")


def test_step_line_unpriced_board(board, capsys):
    board["markets"]["KXPAYROLLS-26OCT"] = [
        market("KXPAYROLLS-26OCT-T0", 0, "0.0000", "0.0000")]
    econfreeze.freeze()
    assert capsys.readouterr().out.endswith("(1 strikes)  median -\n")
