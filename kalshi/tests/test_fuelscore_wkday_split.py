"""fuelscore.py: the log-only WKDAY vs MOM race split by scored weekday.

The 11/5 brief: "The weekday model has now lost Wednesday and Thursday to
MOM, but still leads 13-8 overall, and its edge looks confined to
Sun/Mon/Tue". That split was counted by hand off the rows. The open
operator item (promote WKDAY into the race) and the "~3 more Sun/Mon pairs"
trading gate both hinge on it, so the tool prints it: per weekday of the
scored print, WKDAY closer / MOM closer / tied and both MAEs, over the same
days as the '# log-only WKDAY' line.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from test_fuelscore_wkday import (damped_series, fuelscore, journal,  # noqa: F401
                                  lines)


def split(capsys):
    out = lines(capsys)
    return [l for l in out if l.startswith("# WKDAY vs MOM by weekday")]


def test_split_counts_each_scored_weekday(journal, capsys):
    fuelscore.main(["regular"])
    (line,) = split(capsys)
    # scored Fri 10/23 and Sat 10/24 exact for both; Sun 10/25 MOM missed 1c
    assert "Fri 0-0-1 MAE 0.000/0.000c" in line
    assert "Sat 0-0-1 MAE 0.000/0.000c" in line
    assert "Sun 1-0-0 MAE 0.000/1.000c" in line
    assert "Mon" not in line and "Thu" not in line


def test_split_runs_monday_first(journal, capsys):
    journal(damped_series(end="2026-10-27"))
    fuelscore.main(["regular"])
    (line,) = split(capsys)
    assert line.index("Mon ") < line.index("Tue ") < line.index("Fri ") \
        < line.index("Sun ")


def test_split_matches_the_log_only_totals(journal, capsys):
    journal(damped_series(end="2026-11-08"))
    fuelscore.main(["regular"])
    out = lines(capsys)
    log = next(l for l in out if l.startswith("# log-only WKDAY"))
    (line,) = [l for l in out if l.startswith("# WKDAY vs MOM by weekday")]
    cells = [c.split()[1] for c in line.split(": ", 1)[1].split("  ")]
    totals = [sum(int(c.split("-")[i]) for c in cells) for i in range(3)]
    assert (f"closer than MOM {totals[0]}, MOM closer {totals[1]}, "
            f"tied {totals[2]}") in log


def test_no_split_line_before_anything_is_scorable(journal, capsys):
    journal(damped_series(end="2026-10-12"))
    fuelscore.main(["regular"])
    assert split(capsys) == []
