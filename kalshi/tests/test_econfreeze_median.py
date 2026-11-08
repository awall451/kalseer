"""econfreeze moves: the board's implied median at every freeze.

Brief 11/7 retired the discretionary NFP anchor: "from November, MINE = the
board's T-1 median unless a published consensus gives a written reason to
differ". It scored October by hand-read medians (T-1 ~67k, T-0 ~75k). The
ladders are 'greater' strikes, so the median is where the survival mids
cross 0.5, linearly interpolated between the two floors that bracket it.
`moves` adds one `# board median` line per event, with T-n -> median for
each freeze, so the pre-reg value is a tool line rather than a hand read.
"""

import datetime as dt
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from test_econfreeze import board, econfreeze, market  # noqa: F401


def _ladder(*pairs):
    return [market(f"KXPAYROLLS-26OCT-T{f}", f, bid, ask)
            for f, bid, ask in pairs]


def _median_line(capsys):
    econfreeze.main(["moves", "KXPAYROLLS"])
    (line,) = [l for l in capsys.readouterr().out.splitlines()
               if l.startswith("# board median")]
    return line


def test_median_interpolates_where_the_mids_cross_half(board, capsys):
    # 11/6 T-0 KXPAYROLLS-26OCT: T70000 0.575, T80000 0.46 -> ~76522
    board["markets"]["KXPAYROLLS-26OCT"] = _ladder(
        (60000, "0.5900", "0.6800"), (70000, "0.5600", "0.5900"),
        (80000, "0.4300", "0.4900"), (90000, "0.3400", "0.4000"))
    econfreeze.freeze()
    capsys.readouterr()
    assert _median_line(capsys) == "# board median: T-7 76522"


def test_median_line_follows_the_t_minus_path(board, capsys):
    econfreeze.freeze()   # T-7: T0 0.86, T50000 0.42 -> 40909
    board["today"] = dt.date(2026, 11, 5)
    board["markets"]["KXPAYROLLS-26OCT"] = _ladder(
        (0, "0.9000", "0.9200"), (50000, "0.5500", "0.5900"),
        (100000, "0.1000", "0.1200"))
    econfreeze.freeze()   # T-1: T50000 0.57, T100000 0.11 -> 57609
    capsys.readouterr()
    assert _median_line(capsys) == "# board median: T-7 40909  T-1 57609"


def test_unpriced_strikes_are_skipped_not_read_as_zero(board, capsys):
    board["markets"]["KXPAYROLLS-26OCT"] = _ladder(
        (0, "0.7900", "0.8100"), (50000, "0.0000", "0.0000"),
        (100000, "0.1900", "0.2100"))
    econfreeze.freeze()
    capsys.readouterr()
    # the empty T50000 book drops out; T0 0.80 -> T100000 0.20 brackets it
    assert _median_line(capsys) == "# board median: T-7 50000"


def test_a_median_off_the_ladder_says_which_end(board, capsys):
    board["markets"]["KXPAYROLLS-26OCT"] = _ladder(
        (0, "0.9000", "0.9200"), (50000, "0.7000", "0.7200"))
    econfreeze.freeze()
    board["today"] = dt.date(2026, 10, 31)
    board["markets"]["KXPAYROLLS-26OCT"] = _ladder(
        (0, "0.3000", "0.3200"), (50000, "0.1000", "0.1200"))
    econfreeze.freeze()
    board["today"] = dt.date(2026, 11, 1)
    board["markets"]["KXPAYROLLS-26OCT"] = _ladder(
        (0, "0.0000", "0.0000"))
    econfreeze.freeze()
    capsys.readouterr()
    assert _median_line(capsys) == \
        "# board median: T-7 >50000  T-6 <0  T-5 -"


def test_fractional_ladders_keep_their_decimals(board, capsys):
    board["events"] = {"KXCPI": ["KXCPI-26OCT"]}
    board["markets"]["KXCPI-26OCT"] = [
        market("KXCPI-26OCT-T0.2", 0.2, "0.6000", "0.6200"),
        market("KXCPI-26OCT-T0.3", 0.3, "0.1400", "0.1500")]
    econfreeze.freeze()
    capsys.readouterr()
    econfreeze.main(["moves", "KXCPI"])
    assert "# board median: T-7 0.224" in capsys.readouterr().out
