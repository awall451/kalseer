"""econfreeze.py: journal the Hormuz weekly board every morning too.

Brief 11/14: "The board centre dropped from 23.5 to 20.8 overnight with no
PortWatch data." The watchlist keeps that path by hand ("In-week drift
record: wk7 up informed, wk8 down wrong, wk9 up then sharply down TBD"), and
the week-10 YES rule hangs on it. Nothing journals the board: prereg freezes
it once, and the daily centres live only in watchlist prose. KXHORMUZWEEKLY
is a 'greater' ladder like the macro boards, so econfreeze freezes it, and
`moves`/`score` read the drift and grade each day's median. Its events are
dated by week end (26NOV15), and the next week lists while this one trades,
so every open week is frozen, not just the nearest.
"""

import datetime as dt
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parents[1]))
import econfreeze
from test_econfreeze import board, market, rows  # noqa: F401 (fixture)

# live 11/15 ~07Z boards (bid/ask strings as Kalshi serves them)
W9C, W10C = "2026-11-17T14:00:00Z", "2026-11-24T14:00:00Z"
WK9 = [market("KXHORMUZWEEKLY-26NOV15-T15", 15, "0.9100", "0.9400", close=W9C),
       market("KXHORMUZWEEKLY-26NOV15-T20", 20, "0.6500", "0.6800", close=W9C),
       market("KXHORMUZWEEKLY-26NOV15-T23", 23, "0.2100", "0.2500", close=W9C),
       market("KXHORMUZWEEKLY-26NOV15-T25", 25, "0.1100", "0.1200", close=W9C)]
WK10 = [market("KXHORMUZWEEKLY-26NOV22-T20", 20, "0.6700", "0.6800", close=W10C),
        market("KXHORMUZWEEKLY-26NOV22-T23", 23, "0.5000", "0.5500", close=W10C),
        market("KXHORMUZWEEKLY-26NOV22-T25", 25, "0.4400", "0.4900", close=W10C)]


def hormuz(board):
    board["events"] = {"KXHORMUZWEEKLY": ["KXHORMUZWEEKLY-26NOV22",
                                          "KXHORMUZWEEKLY-26NOV15"]}
    board["markets"] = {"KXHORMUZWEEKLY-26NOV15": WK9,
                        "KXHORMUZWEEKLY-26NOV22": WK10}
    board["today"] = dt.date(2026, 11, 15)


def test_hormuz_is_a_frozen_series():
    assert "KXHORMUZWEEKLY" in econfreeze.SERIES


def test_week_dated_events_sort_by_day():
    assert econfreeze.nearest(["KXHORMUZWEEKLY-26NOV22",
                               "KXHORMUZWEEKLY-26NOV15"]) \
        == "KXHORMUZWEEKLY-26NOV15"
    assert econfreeze.nearest(["KXHORMUZWEEKLY-26DEC06",
                               "KXHORMUZWEEKLY-26NOV29"]) \
        == "KXHORMUZWEEKLY-26NOV29"
    # the month-dated macro tickers still parse
    assert econfreeze.nearest(["KXCPI-26DEC", "KXCPI-26NOV"]) == "KXCPI-26NOV"


def test_freeze_journals_every_open_hormuz_week(board, capsys):
    hormuz(board)
    assert econfreeze.freeze() == 2
    rs = rows()
    assert [r["event"] for r in rs] == ["KXHORMUZWEEKLY-26NOV15",
                                        "KXHORMUZWEEKLY-26NOV22"]
    assert [r["days_out"] for r in rs] == [2, 9]
    assert rs[0]["markets"][1] == {"ticker": "KXHORMUZWEEKLY-26NOV15-T20",
                                   "floor": 20, "yes_bid": "0.6500",
                                   "yes_ask": "0.6800"}
    out = capsys.readouterr().out
    assert "KXHORMUZWEEKLY-26NOV15 T-2 (4 strikes)  median 21.138" in out


def test_a_second_hormuz_freeze_the_same_day_is_skipped(board):
    hormuz(board)
    econfreeze.freeze()
    assert econfreeze.freeze() == 0
    assert len(rows()) == 2


def test_macro_series_still_freeze_only_the_nearest_month(board):
    board["events"]["KXPAYROLLS"] = ["KXPAYROLLS-26NOV", "KXPAYROLLS-26OCT"]
    assert econfreeze.freeze() == 1
    assert board["asked"] == ["KXPAYROLLS-26OCT"]


def test_moves_reads_the_hormuz_drift(board, capsys):
    hormuz(board)
    econfreeze.freeze()
    board["today"] = dt.date(2026, 11, 16)
    board["markets"]["KXHORMUZWEEKLY-26NOV15"] = [
        market("KXHORMUZWEEKLY-26NOV15-T15", 15, "0.9500", "0.9700", close=W9C),
        market("KXHORMUZWEEKLY-26NOV15-T20", 20, "0.8000", "0.8200", close=W9C),
        market("KXHORMUZWEEKLY-26NOV15-T23", 23, "0.4000", "0.4400", close=W9C),
        market("KXHORMUZWEEKLY-26NOV15-T25", 25, "0.2000", "0.2200", close=W9C)]
    econfreeze.freeze()
    capsys.readouterr()
    econfreeze.moves("KXHORMUZWEEKLY-26NOV15")
    out = capsys.readouterr().out.splitlines()
    assert "# T-2 -> T-1: T15 +0.03  T20 +0.15  T23 +0.19  T25 +0.09" in out
    assert out[-1] == "# board median: T-2 21.138  T-1 22.385"


def test_the_prompt_names_the_hormuz_board_freeze():
    prompt = (pathlib.Path(__file__).parents[2] / "bin" / "daily-prompt.md")
    text = " ".join(prompt.read_text().split())
    assert ("It also freezes every open KXHORMUZWEEKLY week, so "
            "`econfreeze.py moves KXHORMUZWEEKLY` is the in-week board drift "
            "record") in text
