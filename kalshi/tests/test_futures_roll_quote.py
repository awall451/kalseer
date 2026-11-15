"""futures.py: a last trade from the NEXT contract month is a roll, not a conflict.

Brief 11/14: "RBZ26 2.6214 (-4.9c) is flagged unverified because the front
month rolled to F27" (watchlist: "tool WARNING: last trade 2.5891 is F27, roll
not a move -> RBZ26 bar unverified"). The journal shows the bar was fine: RB=F
11/13 2.6214 == rbob-Z26 11/13 2.6214, and 2.5891 == rbob-F27's 11/13 close.
Yahoo's continuous quote had rolled to Jan while its bars were still Dec, and
`_conflict` read the gap between two contracts as a contradiction. When the
last trade belongs to a different contract month than the newest bar, and
that bar equals its own month's close, `closes` now says so instead of
calling the bar unverified. A quote that matches no month still warns.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parents[1]))
import futures
from test_futures import body, ts
from test_futures_contracts import lines, roll  # noqa: F401 (fixture)

# 11/9..11/13 (ts counts October days, so 40 = 11/9)
NOV = [40, 41, 42, 43, 44]
Z26 = [2.6509, 2.6088, 2.6075, 2.6708, 2.6214]
F27 = [2.6083, 2.5707, 2.5738, 2.6332, 2.5891]


def rbob(roll, last=2.5891):
    roll["bodies"]["RB=F"] = body("RB=F", [ts(x) for x in NOV], Z26,
                                  last=(last, ts(44, 16)))
    roll["bodies"]["RBZ26.NYM"] = body("RBZ26.NYM", [ts(x) for x in NOV], Z26,
                                       last=(2.6214, ts(44, 16)))
    roll["bodies"]["RBF27.NYM"] = body("RBF27.NYM", [ts(x) for x in NOV], F27,
                                       last=(2.5891, ts(44, 16)))


def test_a_next_month_last_trade_does_not_mark_the_bar_unverified(roll, capsys):
    rbob(roll)
    futures.main(["closes", "rbob"])
    out = "\n".join(lines(capsys))
    assert "disagrees" not in out
    assert "unverified" not in out


def test_the_roll_is_named_with_both_months(roll, capsys):
    rbob(roll)
    futures.main(["closes", "rbob"])
    note = [l for l in lines(capsys) if "rolled ahead" in l]
    assert len(note) == 1
    assert "last trade 2.5891 is F27's" in note[0]
    assert "2026-11-13 bar 2.6214 is Z26's own close (RBZ26.NYM)" in note[0]
    assert "not a conflict" in note[0]


def test_the_roll_note_sits_before_the_footer(roll, capsys):
    rbob(roll)
    futures.main(["closes", "rbob"])
    out = lines(capsys)
    note = next(i for i, l in enumerate(out) if "rolled ahead" in l)
    footer = next(i for i, l in enumerate(out) if l.startswith("# rbob = RB=F"))
    assert note < footer


def test_the_october_roll_case_is_not_a_conflict_either(roll, capsys):
    # brief 10/24: 10/23 bar is Nov's 4.9842, the last trade Dec's 4.7870
    futures.main(["closes", "ulsd"])
    out = "\n".join(lines(capsys))
    assert "disagrees" not in out
    assert "last trade 4.7870 is Z26's" in out
    assert "2026-10-23 bar 4.9842 is X26's own close (HOX26.NYM)" in out


def test_a_quote_matching_no_month_still_warns(roll, capsys):
    rbob(roll, last=2.5500)
    futures.main(["closes", "rbob"])
    out = "\n".join(lines(capsys))
    assert "last trade 2.5500 disagrees with the 2026-11-13 bar 2.6214" in out
    assert "rolled ahead" not in out


def test_a_quote_from_the_bars_own_month_that_differs_still_warns(roll, capsys):
    # Z26's own quote off its own bar is a real contradiction, not a roll
    rbob(roll, last=2.6000)
    roll["bodies"]["RBZ26.NYM"] = body("RBZ26.NYM", [ts(x) for x in NOV], Z26,
                                       last=(2.6000, ts(44, 16)))
    futures.main(["closes", "rbob"])
    out = "\n".join(lines(capsys))
    assert "disagrees" in out
    assert "rolled ahead" not in out


def test_a_stale_next_month_quote_still_warns(roll, capsys):
    rbob(roll)
    roll["bodies"]["RB=F"] = body("RB=F", [ts(x) for x in NOV], Z26,
                                  last=(2.5891, ts(43, 16)))
    futures.main(["closes", "rbob"])
    out = "\n".join(lines(capsys))
    assert "last trade 2.5891 is dated 2026-11-12, older than" in out


def test_the_prompt_says_a_rolled_quote_leaves_the_bar_verified():
    prompt = (pathlib.Path(__file__).parents[2] / "bin" / "daily-prompt.md")
    text = " ".join(prompt.read_text().split())
    assert ("A `rolled ahead of the bars` line means the last trade is the "
            "next month's and the newest bar is its own month's close: the "
            "bar is not unverified") in text


def test_without_contract_months_the_old_warning_stands(roll, capsys):
    rbob(roll)
    roll["fail"].update({"RBZ26.NYM", "RBF27.NYM"})
    futures.main(["closes", "rbob"])
    out = "\n".join(lines(capsys))
    assert "disagrees" in out
