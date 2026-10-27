"""fuelscore.py --moves: the journal's own k-print change distribution.

The judgment step keeps rebuilding this by hand before a weekly fuel trade.
10/24 sources: "journal 2-print diesel change distribution (n=29)". 10/26
brief: "Across the AAA journal's 26 seven-day diesel windows, the largest
rise was +5.22c. None beat +7.08c, and only 1 beat +5.08c". That count was
the core of the KXDIESELW-26NOV02 NO. These tests pin the windows (both ends
printed, never across a gap), the --since regime cut and the --need count.
"""

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from test_fuelscore import SERIES, fuelscore, journal, row  # noqa: F401

D = fuelscore.Decimal


def test_moves_are_every_k_day_window_with_both_ends_printed(journal):
    prices = dict(fuelscore.series("regular"))
    got = fuelscore.moves(prices, 2)
    assert [(a, b) for a, b, _ in got][:2] == [("2026-10-09", "2026-10-11"),
                                              ("2026-10-10", "2026-10-12")]
    assert [c * 100 for _, _, c in got] == [D("-0.12"), D("0.14"),
                                           D("-0.73"), D("0.51"), D("1.17")]


def test_moves_never_span_a_missing_print(journal):
    journal([row(d, p) for d, p in SERIES if d != "2026-10-12"])
    prices = dict(fuelscore.series("regular"))
    assert [(a, b) for a, b, _ in fuelscore.moves(prices, 2)] == [
        ("2026-10-09", "2026-10-11"), ("2026-10-11", "2026-10-13"),
        ("2026-10-13", "2026-10-15")]


def test_since_keeps_windows_starting_on_or_after_it(journal):
    prices = dict(fuelscore.series("regular"))
    got = fuelscore.moves(prices, 2, since="2026-10-11")
    assert [a for a, _, _ in got] == ["2026-10-11", "2026-10-12", "2026-10-13"]


def test_moves_cli_prints_the_spread_and_extremes(journal, capsys):
    fuelscore.main(["regular", "--moves", "2"])
    out = capsys.readouterr().out
    assert "regular 2-print moves" in out and "n=5" in out
    assert "min -0.73c" in out and "median +0.14c" in out
    assert "max +1.17c" in out
    assert "+1.17c 2026-10-13->2026-10-15" in out
    assert "-0.73c 2026-10-11->2026-10-13" in out


def test_need_counts_windows_that_reached_the_move(journal, capsys):
    fuelscore.main(["regular", "--moves", "2", "--need", "0.50"])
    out = capsys.readouterr().out
    assert "need +0.50c: 2 of 5 windows" in out
    assert "0.42" in out  # (2 + 0.5) / (5 + 1)


def test_a_negative_need_counts_falls(journal, capsys):
    fuelscore.main(["regular", "--moves", "2", "--need", "-0.50"])
    assert "need -0.50c: 1 of 5 windows" in capsys.readouterr().out


def test_moves_with_too_few_prints_says_so(journal, capsys):
    fuelscore.main(["regular", "--moves", "30"])
    assert "no 30-print windows" in capsys.readouterr().out


def test_moves_rejects_a_bad_k(journal):
    with pytest.raises(SystemExit):
        fuelscore.main(["regular", "--moves", "0"])


def test_the_judgment_prompt_names_moves():
    prompt = (pathlib.Path(fuelscore.__file__).parents[1] / "bin"
              / "daily-prompt.md").read_text()
    assert "--moves" in prompt
