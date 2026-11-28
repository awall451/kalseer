"""futures.py margin --ahead K: a record for the 'fall slows' reversion hint.

After #151's record showed a gas print below its margin-reversion level
never rose toward it (0 of 27), the judgment step kept the level as a
softer, unscored hint (brief 11/27: "Yesterday's margin-reversion hint
(print under 3.5799, so the slide should slow) called it ... From now on I
use the level only as a 'fall slows' hint, never as a rise call"). One
slowdown is no record, and falls slow often anyway. A '# gas reversion
slowdown' line counts, after each K-print fall, whether the next K prints
fell slower (or rose), for prints below the level against prints above it
(the control).
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from test_futures_margin import PROMPT, aaa, data, futures, run, write  # noqa: F401


def slowdown(out, fuel="gas"):
    return [l for l in out if l.startswith(f"# {fuel} reversion slowdown")]


def falling(data, gas, diesel=("6.0198", "5.9989", "5.9848", "5.9700")):
    write(data / "aaa" / "prints.jsonl", [
        aaa(f"2026-11-{14 + i}", g, d)
        for i, (g, d) in enumerate(zip(gas, diesel))])


def test_counts_falls_that_slowed_on_each_side_of_the_level(data, capsys):
    # 11-15: 3.90 -> 3.80 (-10c), level 3.8500 above it -> next -5c, slowed
    # 11-16: 3.80 -> 3.75 (-5c), level 3.7332 below it -> next -6c, faster
    falling(data, ("3.9000", "3.8000", "3.7500", "3.6900"))
    out = slowdown(run(capsys, "--ahead", "1"))
    assert out == [
        "# gas reversion slowdown (1 prints ahead, window 15): after a "
        "1-print fall, the next 1 fell slower or rose: below the level 1 of "
        "1 (next -5.00c vs last -10.00c); above it 0 of 1 (next -6.00c vs "
        "last -5.00c)"]


def test_a_rise_is_not_a_fall_to_score(data, capsys):
    falling(data, ("3.7000", "3.8000", "3.8500", "3.9000"))
    out = slowdown(run(capsys, "--ahead", "1"))
    assert out[0].endswith("below the level 0 of 0; above it 0 of 0")


def test_the_record_line_is_unchanged_beside_it(data, capsys):
    falling(data, ("3.9000", "3.8000", "3.7500", "3.6900"))
    out = run(capsys, "--ahead", "1")
    record = [l for l in out if l.startswith("# gas reversion record")]
    assert record[0].startswith("# gas reversion record (1 prints ahead, "
                                "window 15): n=3 ")


def test_diesel_gets_its_own_slowdown_line(data, capsys):
    falling(data, ("3.9000", "3.8000", "3.7500", "3.6900"))
    out = slowdown(run(capsys, "--ahead", "1"), "diesel")
    assert out[0].startswith("# diesel reversion slowdown (1 prints ahead, "
                             "window 15): after a 1-print fall")


def test_no_ahead_prints_no_slowdown(data, capsys):
    assert slowdown(run(capsys)) == []


def test_prompt_names_the_slowdown_line():
    assert "# gas reversion slowdown" in PROMPT.read_text()
