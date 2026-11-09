"""econfreeze score: the settled print against each freeze's board median.

The NFP pre-reg is the board's T-1 median from November (brief 11/7), and
op-11-08 asked for "the T-11..T-0 board-median path" once CPI settles 11/10.
`score` printed only per-strike Brier, so how far the median missed the
print (Oct NFP: 165000 settled vs T-1 66818) was a hand subtraction. Kalshi's
expiration_value comes as '165000', '4.1%', '0.6' or a label ('Above 0.2%',
KXCPICORE-26SEP). A label falls back to the bracket the results imply.
"""

import datetime as dt
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from test_econfreeze import board, econfreeze, market  # noqa: F401


def _ladder(*pairs):
    return [market(f"KXPAYROLLS-26OCT-T{f}", f, bid, ask)
            for f, bid, ask in pairs]


def _settle(board, value, results):
    ms = []
    for f, y in results:
        m = market(f"KXPAYROLLS-26OCT-T{f}", f, "", "", y)
        m["expiration_value"] = value
        ms.append(m)
    board["markets"]["KXPAYROLLS-26OCT"] = ms


def _miss_line(capsys):
    capsys.readouterr()
    econfreeze.main(["score"])
    (line,) = [l for l in capsys.readouterr().out.splitlines()
               if l.startswith("# KXPAYROLLS-26OCT settled")]
    return line


def test_score_prints_each_freezes_median_miss(board, capsys):
    board["markets"]["KXPAYROLLS-26OCT"] = _ladder(
        (0, "0.9000", "0.9200"), (50000, "0.5500", "0.5900"),
        (100000, "0.1000", "0.1200"))
    econfreeze.freeze()   # T-7: T50000 0.57, T100000 0.11 -> 57609
    board["today"] = dt.date(2026, 11, 6)
    board["markets"]["KXPAYROLLS-26OCT"] = _ladder(
        (0, "0.9000", "0.9200"), (50000, "0.2000", "0.2200"))
    econfreeze.freeze()   # T-0: T0 0.91, T50000 0.21 -> 29286
    _settle(board, "165000", [(0, "yes"), (50000, "yes"), (100000, "yes")])
    assert _miss_line(capsys) == (
        "# KXPAYROLLS-26OCT settled 165000; board median miss (settled - "
        "median): T-7 57609 +107391  T-0 29286 +135714")


def test_percent_values_parse_and_off_ladder_medians_do_not_score(board,
                                                                  capsys):
    board["events"] = {"KXU3": ["KXU3-26OCT"]}
    board["markets"]["KXU3-26OCT"] = [
        market("KXU3-26OCT-T4.0", 4.0, "0.7000", "0.7200"),
        market("KXU3-26OCT-T4.2", 4.2, "0.6000", "0.6200")]
    econfreeze.freeze()   # never crosses 0.5: '>4.200'
    board["today"] = dt.date(2026, 11, 6)
    board["markets"]["KXU3-26OCT"] = [
        market("KXU3-26OCT-T4.0", 4.0, "0.7000", "0.7200"),
        market("KXU3-26OCT-T4.2", 4.2, "0.2000", "0.2200")]
    econfreeze.freeze()   # 4.0 + 0.2 * 0.21 / 0.5 = 4.084
    settled = [market("KXU3-26OCT-T4.0", 4.0, "", "", "yes"),
               market("KXU3-26OCT-T4.2", 4.2, "", "", "no")]
    for m in settled:
        m["expiration_value"] = "4.1%"
    board["markets"]["KXU3-26OCT"] = settled
    capsys.readouterr()
    econfreeze.main(["score"])
    out = capsys.readouterr().out.splitlines()
    assert ("# KXU3-26OCT settled 4.1; board median miss (settled - "
            "median): T-7 >4.200  T-0 4.084 +0.016") in out


def test_a_label_value_falls_back_to_the_results_bracket(board, capsys):
    board["markets"]["KXPAYROLLS-26OCT"] = _ladder(
        (0, "0.9000", "0.9200"), (50000, "0.5500", "0.5900"),
        (100000, "0.1000", "0.1200"))
    econfreeze.freeze()   # 57609
    board["today"] = dt.date(2026, 11, 6)
    board["markets"]["KXPAYROLLS-26OCT"] = _ladder(
        (0, "0.4000", "0.4200"), (50000, "0.1000", "0.1200"))
    econfreeze.freeze()   # '<0'
    _settle(board, "Above 50000", [(0, "yes"), (50000, "yes"),
                                   (100000, "no")])
    assert _miss_line(capsys) == (
        "# KXPAYROLLS-26OCT settled 'Above 50000' (in (50000, 100000]); "
        "board median vs that bracket: T-7 57609 in  T-0 <0 below")
