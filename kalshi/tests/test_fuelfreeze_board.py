"""fuelfreeze.py: an empty or one-sided book is not a board price.

daily-2026-10-20.log, the first live fuelfreeze step: every KXDIESELD-26OCT21
strike printed "board 0.00  RW 1.00  MOM 1.00  DRIFT 1.00" off a 0.0000/0.0000
book (no quotes at all), and KXAAAGASD-26OCT21 printed "board 0.50" at >4.29
off 0.0100/0.9900 and "board 0.56" at >4.24 off 0.1200/1.0000. Those were 15
of the 34 divergence lines, and each one would score as a model win in the
board-vs-model tally that is meant to replace the watchlist's "board 3-1".
A strike counts as a board price only with a real two-sided book: ask above
bid and a spread of at most MAX_SPREAD.
"""

import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parents[1]))
import fuelfreeze


def strike(bid, ask, floor=6.30, p=1.0):
    return {"ticker": f"KXDIESELD-26OCT21-T{floor:.3f}", "floor": floor,
            "yes_bid": bid, "yes_ask": ask,
            "p": {"RW": p, "MOM": p, "DRIFT": p}}


def test_a_book_with_no_quotes_has_no_mid():
    assert fuelfreeze._mid(strike("0.0000", "0.0000")) is None


def test_a_spread_wider_than_the_cap_has_no_mid():
    assert fuelfreeze._mid(strike("0.0100", "0.9900")) is None
    assert fuelfreeze._mid(strike("0.1200", "1.0000")) is None


def test_tight_books_keep_their_mid_including_at_the_edges():
    assert fuelfreeze._mid(strike("0.5900", "0.6900")) == pytest.approx(0.64)
    assert fuelfreeze._mid(strike("0.9900", "1.0000")) == pytest.approx(0.995)
    assert fuelfreeze._mid(strike("0.0000", "0.0100")) == pytest.approx(0.005)
    # exactly at the cap still counts
    assert fuelfreeze._mid(strike("0.4000", "0.6000")) == pytest.approx(0.5)


def test_empty_books_print_no_divergence():
    rec = {"event": "KXDIESELD-26OCT21",
           "strikes": [strike("0.0000", "0.0000", 6.27),
                       strike("0.0100", "0.9900", 6.29),
                       strike("0.5900", "0.6900", 6.38, p=0.0)]}
    lines = fuelfreeze.divergences(rec)
    assert len(lines) == 1 and ">6.38 board 0.64" in lines[0]


def test_score_skips_empty_books_for_board_brier_and_tally(tmp_path,
                                                          monkeypatch, capsys):
    journal = tmp_path / "fuel-freeze.jsonl"
    rec = {"event": "KXDIESELD-26OCT21", "series": "KXDIESELD",
           "grade": "diesel", "date": "2026-10-21", "k": 1,
           "strikes": [strike("0.0000", "0.0000", 6.27, p=1.0),
                       strike("0.9000", "0.9600", 6.30, p=1.0)]}
    journal.write_text(json.dumps(rec) + "\n")
    monkeypatch.setattr(fuelfreeze, "JOURNAL", journal)
    markets = [{"ticker": s["ticker"], "result": "yes",
                "expiration_value": "6.3300"} for s in rec["strikes"]]
    monkeypatch.setattr(fuelfreeze.kalshi, "get_event",
                        lambda t: {"markets": markets})
    fuelfreeze.score()
    out = capsys.readouterr().out
    line = [l for l in out.splitlines() if "KXDIESELD-26OCT21" in l][0]
    # only the 0.90/0.96 strike is a board: (0.93 - 1)^2
    assert f"BOARD {0.07 ** 2:.4f}" in line
    assert "board-RW 0-0" in out
