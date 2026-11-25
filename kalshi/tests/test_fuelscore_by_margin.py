"""fuelscore.py --moves K --by-margin: the k-print moves split by the
retail-wholesale margin the window started at.

Brief 11/24 passed the weekly diesel on exactly this gap: "fuelscore --moves
6 --need -18 diesel: 0 of 56 windows (min -16.66c) -> the empirical
distribution says YES T5.62 is cheap, but the 41.5c margin gap and the -22c
HO settle say the fall accelerates". Whether a wide margin has preceded the
big falls was left to judgment. These tests pin the start margin (the
window's first print minus the newest settle dated before it, as in
`futures.py margin`), the thirds, and the at-or-above-latest line.
"""

import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from test_fuelscore import SERIES, fuelscore, journal, row  # noqa: F401

import futures

PROMPT = pathlib.Path(fuelscore.__file__).parents[1] / "bin" / "daily-prompt.md"

# a close the day before each print: start margins 10-09 1.00, 10-10 1.20,
# 10-11 1.40, 10-12 1.10, 10-13 1.30; latest (10-15) 1.30. The 2-print
# moves from those starts are -0.12 +0.14 -0.73 +0.51 +1.17 (cents)
CLOSES = [("2026-10-08", 3.35), ("2026-10-09", 3.1456),
          ("2026-10-10", 2.9488), ("2026-10-11", 3.247),
          ("2026-10-12", 3.0415), ("2026-10-14", 3.0532)]


@pytest.fixture
def closes(tmp_path, monkeypatch):
    monkeypatch.setattr(futures, "DATA", tmp_path)
    path = tmp_path / "futures" / "rbob.jsonl"
    path.parent.mkdir()

    def write(rows):
        path.write_text("".join(json.dumps({"date": d, "close": c}) + "\n"
                                for d, c in rows))
    write(CLOSES)
    return write


def run(capsys, *args):
    fuelscore.main(["regular", "--moves", "2", "--by-margin", *args])
    return [l for l in capsys.readouterr().out.splitlines()
            if "margin" in l]


def test_start_margin_is_the_print_minus_the_settle_before_it(journal,
                                                               closes):
    prices = dict(fuelscore.series("regular"))
    got = fuelscore.start_margins(prices, "regular")
    assert got["2026-10-09"] == fuelscore.Decimal("1.0000")
    assert got["2026-10-11"] == fuelscore.Decimal("1.4000")
    assert got["2026-10-15"] == fuelscore.Decimal("1.3000")


def test_thirds_by_start_margin(journal, closes, capsys):
    out = run(capsys)
    assert out[0].startswith("# regular 2-print moves by start margin "
                             "(regular - RB front month; 5 of 5 windows")
    assert "low 1.0000..1.0000 n=1 median -0.12c" in out[0]
    assert "mid 1.1000..1.2000 n=2 median +0.14c" in out[0]
    assert "high 1.3000..1.4000 n=2 median -0.73c" in out[0]


def test_windows_at_or_above_the_latest_margin(journal, closes, capsys):
    out = run(capsys)
    assert out[1] == ("# regular latest margin 1.3000 (2026-10-15): 2 of 5 "
                      "windows started at or above it (starts 2026-10-11.."
                      "2026-10-13, overlapping): median -0.73c "
                      "min -0.73c max +1.17c")


def test_need_is_counted_per_band(journal, closes, capsys):
    out = run(capsys, "--need", "-0.50")
    assert "n=1 median -0.12c need 0/1" in out[0]
    assert "n=2 median -0.73c need 1/2" in out[0]
    assert out[1].endswith("max +1.17c need 1/2")


def test_plain_moves_lines_still_print_first(journal, closes, capsys):
    fuelscore.main(["regular", "--moves", "2", "--need", "-0.50",
                    "--by-margin"])
    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith("# regular 2-print moves (windows")
    assert "# need -0.50c: 1 of 5 windows" in out[3]
    assert "by start margin" in out[4]


def test_latest_margin_above_every_start_says_so(journal, closes, capsys):
    closes(CLOSES[:-1] + [("2026-10-14", 2.8532)])  # latest margin 1.5000
    out = run(capsys)
    assert out[1] == ("# regular latest margin 1.5000 (2026-10-15): no "
                      "window started at or above it (widest 1.4000 on "
                      "2026-10-11)")


def test_windows_without_a_settle_are_left_out(journal, closes, capsys):
    closes(CLOSES[1:])  # no close before 10-09
    out = run(capsys)
    assert "4 of 5 windows" in out[0]


def test_no_futures_journal_says_so(journal, closes, capsys, tmp_path):
    (tmp_path / "futures" / "rbob.jsonl").unlink()
    out = run(capsys)
    assert out == ["# regular moves by start margin: no settled RB closes "
                   "before any window start"]


def test_by_margin_needs_moves_and_a_fuel(journal, closes):
    with pytest.raises(SystemExit):
        fuelscore.main(["regular", "--by-margin"])
    with pytest.raises(SystemExit):
        fuelscore.main(["premium", "--moves", "2", "--by-margin"])


def test_the_judgment_prompt_names_by_margin():
    text = PROMPT.read_text()
    assert "`--moves K --by-margin`" in text
