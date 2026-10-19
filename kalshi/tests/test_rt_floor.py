"""rt.py floor: the THREE-STEP RULE's step (2) as one command.

The rt-method-notes watchlist item: "(1) pin the split; (2) compute the HARD
FLOOR (or hard CEILING for NO-above trades); (3) only then model the incoming
rate", and "only proven edge is same-morning floor math" (2-0: PRI, VIS).
The judgment session does step (2) by hand on the number a trade rides on;
these tests pin the tool to the brief's own worked cases.

Settlement convention (watchlist, Social Reckoning 10/9): ">57 needs display
>=58, i.e. cumulative >=57.5%" — YES on "above T" iff the displayed score
is greater than T.
"""

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parents[1]))
import rt


def out(capsys):
    return capsys.readouterr().out


def test_floor_counts_straight_rotten_reviews_to_lose_yes():
    # 63/70 vs >85: 63/73 = 86.30% still shows 86; 63/74 = 85.14% shows 85.
    assert rt.floor(63, 70, 85) == 4


def test_floor_is_zero_when_yes_is_already_losing():
    assert rt.floor(39, 97, 40) == 0


def test_ceiling_counts_straight_fresh_reviews_to_lose_no():
    # 39/97 vs >40: 40/98 = 40.82% shows 41 — one fresh review flips it.
    assert rt.ceiling(39, 97, 40) == 1
    assert rt.ceiling(63, 70, 85) == 0


def test_ceiling_is_none_when_display_cannot_exceed_threshold():
    assert rt.ceiling(5, 10, 100) is None


def test_exact_half_counts_against_the_holder():
    # 3/8 = 37.5% may display 37 or 38 (rounding side unverified), so for
    # YES >37 the 37.5% point already threatens the floor, and for NO >37 it
    # already threatens the ceiling — conservative for both directions.
    assert rt.floor(3, 7, 37) == 1        # 3/8 = 37.5% (strict: 2)
    assert rt.ceiling(2, 7, 37) == 1      # 3/8 = 37.5% (strict: 2)
    assert rt.ceiling(3, 8, 37) == 0


def test_floor_cli_brief_case_visionquest(capsys):
    # Brief 10/18: "90% on 70 reviews (pin 63/70) ... To fall to 85 or below
    # it would have needed 4 straight rotten reviews".
    rt.main(["floor", "90", "70", "85"])
    text = out(capsys)
    assert "63/70" in text
    assert "YES >85: 4 straight rotten" in text
    assert "63/74 = 85.135%" in text
    assert "NO >85: already losing" in text


def test_floor_cli_knife_edge_street_fighter(capsys):
    # Brief 10/18: "40% on 97 reviews (pin 39/97 = 40.2%) ... knife edge".
    rt.main(["floor", "40", "97", "40"])
    text = out(capsys)
    assert "YES >40: already losing" in text
    assert "NO >40: 1 straight fresh" in text
    assert "40/98 = 40.816%" in text


def test_floor_cli_ambiguous_pin_reports_conservative_per_direction(capsys):
    # 86% on 234 -> 201/202 (method note). Against >84 the 201 pin is the
    # weaker YES floor (4 vs 6); the conservative line must take it.
    assert (rt.floor(201, 234, 84), rt.floor(202, 234, 84)) == (4, 6)
    rt.main(["floor", "86", "234", "84"])
    text = out(capsys)
    assert "201/234" in text and "202/234" in text
    assert "# conservative YES >84 floor: 4 straight rotten" in text
    assert "# conservative NO >84 ceiling: already losing" in text


def test_floor_cli_prev_narrows_the_pin(capsys):
    rt.main(["floor", "45", "128", "44", "--prev", "58/127"])
    text = out(capsys)
    assert "58/128" in text and "57/128" not in text


def test_floor_cli_flags_threshold_math_as_display_based(capsys):
    rt.main(["floor", "90", "70", "85"])
    assert "displayed score > 85" in out(capsys)


def test_floor_cli_impossible_display_fails_loudly(capsys):
    with pytest.raises(SystemExit) as e:
        rt.main(["floor", "99", "3", "90"])
    assert e.value.code != 0
    assert "no integer split" in capsys.readouterr().err


def test_floor_cli_usage_on_bad_args():
    for argv in (["floor"], ["floor", "90", "70"],
                 ["floor", "90", "70", "x"], ["floor", "90", "70", "101"],
                 ["floor", "90", "70", "85", "--prev"]):
        with pytest.raises(SystemExit):
            rt.main(argv)
