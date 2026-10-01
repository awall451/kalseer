"""rt.py CLI: pin the Rotten Tomatoes fresh/rotten split from the display.

The watchlist's rt-method-notes item (DURABLE METHOD NOTE): "displayed% +
review count usually PINS the fresh/rotten split exactly (the 1pp rounding
band contains ~n/100 integers; for n < 100 almost always exactly one; when
two or more fit, disambiguate from yesterday's pinned split plus arrivals,
else use the CONSERVATIVE count FOR THE DIRECTION TRADED and say so)." The
judgment session re-derives this by hand every RT day on a settlement-
relevant number; these tests pin the tool to the method note's own worked
examples so the tool and the ledger can never disagree.
"""

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parents[1]))
import rt

# Worked examples quoted verbatim from the rt-method-notes watchlist item.
UNIQUE_EXAMPLES = [
    (95, 83, 79), (28, 104, 29), (83, 99, 82), (88, 26, 23), (77, 39, 30),
    (65, 20, 13), (76, 45, 34), (71, 31, 22), (75, 51, 38), (71, 35, 25),
    (75, 55, 41), (72, 36, 26), (49, 37, 18), (67, 43, 29), (48, 56, 27),
    (59, 69, 41), (50, 84, 42), (60, 85, 51), (51, 87, 44), (59, 92, 54),
    (50, 92, 46), (57, 96, 55), (96, 103, 99), (53, 114, 60),
]


def lines(capsys):
    out = capsys.readouterr().out.splitlines()
    return ([l for l in out if not l.startswith("#")],
            [l for l in out if l.startswith("#")])


@pytest.mark.parametrize("pct,count,fresh", UNIQUE_EXAMPLES)
def test_worked_examples_pin_uniquely(pct, count, fresh, capsys):
    rt.main(["pin", str(pct), str(count)])
    data, summary = lines(capsys)
    assert data == [f"{fresh}/{count} = {100 * fresh / count:.3f}%"]
    assert any(f"unique pin: {fresh}/{count} fresh" in l for l in summary)


def test_two_candidate_band_lists_both(capsys):
    # 86% on 234 -> 201/202 in the method note's own examples
    rt.main(["pin", "86", "234"])
    data, summary = lines(capsys)
    assert data[0].startswith("201/234 = 85.897%")
    assert data[1].startswith("202/234 = 86.325%")
    assert any("2 candidates for 86% on 234" in l for l in summary)
    assert any("conservative count" in l.lower() for l in summary)


def test_ambiguous_45_on_128_shows_the_hidden_twin(capsys):
    # The ledger recorded 58; 57/128 = 44.531% also rounds to 45 — the tool
    # must surface the twin the hand calculation can miss.
    rt.main(["pin", "45", "128"])
    data, _ = lines(capsys)
    assert len(data) == 2
    assert data[0].startswith("57/128") and data[1].startswith("58/128")


def test_prev_pin_filters_candidates(capsys):
    # Yesterday 58/127: fresh never drops, and only one review arrived.
    rt.main(["pin", "45", "128", "--prev", "58/127"])
    data, summary = lines(capsys)
    assert any("57/128" in l and "inconsistent" in l for l in data)
    assert any("58/128" in l and "consistent" in l for l in data)
    assert any("unique after --prev: 58/128" in l for l in summary)


def test_prev_pin_that_keeps_both_stays_ambiguous(capsys):
    # Yesterday 56/126: two arrivals — both 57 (+1) and 58 (+2) fit.
    rt.main(["pin", "45", "128", "--prev", "56/126"])
    data, summary = lines(capsys)
    assert sum("consistent" in l and "inconsistent" not in l
               for l in data) == 2
    assert not any("unique after --prev" in l for l in summary)


def test_prev_with_more_reviews_than_today_warns_not_filters(capsys):
    # RT occasionally drops reviews; a shrinking count means the prev pin
    # cannot bound today's — say so instead of quietly filtering wrong.
    rt.main(["pin", "45", "128", "--prev", "58/129"])
    _, summary = lines(capsys)
    assert any("review count fell" in l for l in summary)


def test_exact_half_boundary_is_flagged_both_sides(capsys):
    # 3/8 = 37.500% — RT's rounding side at .5 is unverified, so the
    # candidate must appear for both 37 and 38, flagged.
    for pct in ("37", "38"):
        rt.main(["pin", pct, "8"])
        data, _ = lines(capsys)
        assert any(l.startswith("3/8") and ".5 boundary" in l for l in data)


def test_impossible_display_fails_loudly(capsys):
    # 99% on 3 reviews fits no integer split — a misread, never silence.
    with pytest.raises(SystemExit) as e:
        rt.main(["pin", "99", "3"])
    assert e.value.code != 0
    assert "no integer split" in capsys.readouterr().err


def test_usage_on_bad_args():
    for argv in ([], ["nonsense"], ["pin"], ["pin", "53"],
                 ["pin", "53", "114", "--prev"],
                 ["pin", "53", "114", "--prev", "60"],
                 ["pin", "101", "114"], ["pin", "53", "0"],
                 ["pin", "fresh", "114"]):
        with pytest.raises(SystemExit):
            rt.main(argv)
