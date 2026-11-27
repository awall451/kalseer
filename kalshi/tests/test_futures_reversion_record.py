"""futures.py margin --ahead K: a scored record for the margin-reversion level.

The weekly/monthly gas passes set the reversion level against the momentum
models with no record of which has been right (watchlist 11/26: "Reversion
3.5799 says YES, DRIFT x4 ~3.472 says NO -> model-dependent"; brief 11/26:
"the first time the gas print has undershot it, which argues the gas slide
should slow"). These tests pin the record: each origin print's reversion
level (as of that print, over the same --days window) scored against the
print K days later, next to RW (no change), and whether the print moved
toward the level, split by which side of it the print started.
"""

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from test_futures_margin import PROMPT, aaa, data, futures, run, write  # noqa: F401


def record(out, fuel="gas"):
    return [l for l in out if l.startswith(f"# {fuel} reversion record")]


def test_level_as_of_an_origin_uses_only_prints_up_to_it(data):
    prints = futures._prints("regular")
    # 11-16's window is 11-14 (1.2028) and 11-16 (1.1904); the settle
    # after 11-16 is RBZ26 11-16 2.5379
    assert futures.reversion_at("rbob", prints, "2026-11-16", 15) == 3.7345
    assert futures.reversion_at("rbob", prints, "2026-11-16", 1) == 3.7283


def test_record_scores_the_level_against_rw(data, capsys):
    out = record(run(capsys, "--ahead", "1"))
    # origin 11-16 3.8118 -> 11-17 3.7818: level 3.7345 off 4.73c, RW 3.00c
    assert out == [
        "# gas reversion record (1 prints ahead, window 15): n=1 level MAE "
        "4.730c vs RW MAE 3.000c (level closer 0, RW closer 1, tied 0); "
        "started below the level: moved toward it 0 of 0; above it: "
        "toward 1 of 1; last 1 newest first: 11-16 3.8118 lvl 3.7345 -> "
        "3.7818 toward"]


def test_a_print_below_the_level_that_rises_moved_toward_it(data, capsys):
    write(data / "aaa" / "prints.jsonl", [
        aaa("2026-11-14", "3.8242", "6.0198"),
        aaa("2026-11-16", "3.6000", "5.9989"),
        aaa("2026-11-17", "3.7000", "5.9848"),
    ])
    out = record(run(capsys, "--days", "2", "--ahead", "1"))
    # window margins 1.2028, 0.9786 -> mean 1.0907; level 3.6286
    assert ("level MAE 7.140c vs RW MAE 10.000c (level closer 1, RW closer "
            "0, tied 0); started below the level: moved toward it 1 of 1; "
            "above it: toward 0 of 0") in out[0]


def test_no_print_k_days_on_means_nothing_to_score(data, capsys):
    out = record(run(capsys, "--ahead", "5"))
    assert out == ["# gas reversion record (5 prints ahead, window 15): "
                   "no origin has a print 5 days on"]


def test_diesel_gets_its_own_record(data, capsys):
    assert record(run(capsys, "--ahead", "1"), "diesel")[0].startswith(
        "# diesel reversion record (1 prints ahead, window 15): n=1 ")


def test_no_ahead_prints_no_record(data, capsys):
    assert record(run(capsys)) == []


def test_bad_margin_args_exit(data):
    for args in (["--ahead", "0"], ["--ahead", "x"], ["--bogus"]):
        with pytest.raises(SystemExit):
            futures.main(["margin", *args])


def test_prompt_names_the_reversion_record():
    assert "futures.py margin --ahead K" in PROMPT.read_text()
