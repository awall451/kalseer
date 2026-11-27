"""fuelscore.py --ahead K: the RW / MOM / DRIFT race K prints out.

The weekly/monthly boards settle on a print K days away, and the judgment
step projects each model there by hand on every one of them (watchlist
11/26: "DRIFT x4 ~3.472 says NO", "DRIFT x4 ~5.612 vs MOM path ~5.565
straddle the board"; 11/4: "RW 6.256, DRIFT -0.93x4 6.219, MOM -1.84x4
6.183"), with no record of which K-print path has been right. These tests
pin the K-print paths (MOM: today's change K times; DRIFT: the window mean
K times), the scored history, and the `# next` line dated K prints ahead.
"""

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from test_fuelscore import SERIES, day_lines, fuelscore, journal, row  # noqa: F401

PROMPT = pathlib.Path(fuelscore.__file__).parents[1] / "bin" / "daily-prompt.md"
D = fuelscore.Decimal


def test_k_print_forecasts_scale_mom_and_drift(journal):
    prices = dict(fuelscore.series("regular"))
    fc = fuelscore.forecasts(prices, "2026-10-11", 2, k=3)
    # 10-11 4.3488; today's change +0.32c; last-2 mean (-0.44 + 0.32) / 2
    assert fc == {"RW": D("4.3488"), "MOM": D("4.3584"),
                  "DRIFT": D("4.3470")}


def test_one_print_default_is_unchanged(journal):
    prices = dict(fuelscore.series("regular"))
    assert (fuelscore.forecasts(prices, "2026-10-11", 2)
            == fuelscore.forecasts(prices, "2026-10-11", 2, k=1))


def test_rows_score_the_forecast_made_k_prints_before(journal, capsys):
    fuelscore.main(["regular", "--window", "2", "--ahead", "2"])
    rows = day_lines(capsys)
    # 10-13 4.3415 from 10-11: RW 4.3488, MOM 4.3552, DRIFT 4.3476
    assert ("2026-10-13  4.3415  RW 4.3488 -0.73  MOM 4.3552 -1.37  "
            "DRIFT 4.3476 -0.61") in rows
    assert not any("WKDAY" in l for l in rows)


def test_summary_and_next_are_k_prints_ahead(journal, capsys):
    fuelscore.main(["regular", "--window", "2", "--ahead", "2"])
    out = capsys.readouterr().out.splitlines()
    summary = [l for l in out if l.startswith("# n=")]
    assert summary and "ahead 2" in summary[0]
    nxt = [l for l in out if l.startswith("# next")]
    # from 10-15 4.3532: change +0.11c, last-2 mean (+1.06 + 0.11) / 2
    assert nxt == ["# next 2026-10-17 (2 prints ahead of 2026-10-15): "
                   "RW 4.3532  MOM 4.3554  DRIFT 4.3649"]
    assert not any(l.startswith("# log-only") for l in out)


def test_a_missing_origin_print_is_unscored(journal, capsys):
    journal([row(d, p) for d, p in SERIES if d != "2026-10-12"])
    fuelscore.main(["regular", "--window", "2", "--ahead", "2"])
    rows = day_lines(capsys)
    # 10-13 from 10-11 still scores (the gap sits between origin and
    # target, and only the origin's own changes feed the paths); 10-14
    # from 10-12 does not
    assert [l for l in rows if l.startswith("2026-10-14")] == [
        "2026-10-14  4.3521  RW -  MOM -  DRIFT -"]


def test_ahead_must_be_positive_and_not_with_moves(journal):
    with pytest.raises(SystemExit):
        fuelscore.main(["regular", "--ahead", "0"])
    with pytest.raises(SystemExit):
        fuelscore.main(["regular", "--ahead", "2", "--moves", "2"])


def test_the_judgment_prompt_names_ahead():
    text = PROMPT.read_text()
    assert "`--ahead K`" in text
