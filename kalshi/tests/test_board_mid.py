"""kalshi.board_mid: an empty, crossed or one-sided book is not a board price.

Kalshi reports an empty book as "0.0000"/"0.0000", which is truthy, so a
`bid and ask` check reads it as a board at 0.00 (daily-2026-10-20.log: every
KXDIESELD-26OCT21 strike printed "board 0.00"). fuelfreeze was fixed in #77.
prereg, highfreeze and rainfreeze kept the truthy check: in prereg an empty
book scored as a board mid of 0.00 instead of the unpriced 0.5, in highfreeze
an empty bucket entered the MKT leg at 0.00, and a 0.0100/0.9900 book scored
as 0.50 in all three.
"""

import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parents[1]))
import highfreeze
import kalshi
import prereg
import rainfreeze


def test_board_mid_rejects_empty_crossed_and_wide_books():
    assert kalshi.board_mid("0.0000", "0.0000") is None
    assert kalshi.board_mid("0.5000", "0.4000") is None
    assert kalshi.board_mid("0.0100", "0.9900") is None
    assert kalshi.board_mid(None, "0.5000") is None
    assert kalshi.board_mid("", "") is None


def test_board_mid_keeps_tight_books_including_the_edges():
    assert kalshi.board_mid("0.5900", "0.6900") == pytest.approx(0.64)
    assert kalshi.board_mid("0.0000", "0.0100") == pytest.approx(0.005)
    assert kalshi.board_mid("0.9900", "1.0000") == pytest.approx(0.995)
    assert kalshi.board_mid("0.4000", "0.6000") == pytest.approx(0.5)


def test_prereg_scores_an_empty_book_as_unpriced(tmp_path, monkeypatch,
                                                 capsys):
    journal = tmp_path / "preregs.jsonl"
    rec = {"event": "KXDIESELD-26OCT22", "leg": "MINE",
           "at": "2026-10-21T12:05:00+00:00",
           "probs": {"KXDIESELD-26OCT22-T6.31": 0.7},
           "board": {"KXDIESELD-26OCT22-T6.31": ["0.0000", "0.0000"]}}
    journal.write_text(json.dumps(rec) + "\n")
    monkeypatch.setattr(prereg, "JOURNAL", journal)
    monkeypatch.setattr(prereg.kalshi, "get_event", lambda t: {"markets": [
        {"ticker": "KXDIESELD-26OCT22-T6.31", "result": "yes",
         "expiration_value": "6.3150"}]})
    prereg.score()
    out = capsys.readouterr().out
    # unpriced board -> 0.5, (0.5 - 1)^2; the truthy check gave 0.0 -> 1.0
    assert "BOARD 0.2500" in out
    assert "MINE 0.0900" in out


def test_highfreeze_has_no_mkt_leg_with_an_empty_bucket():
    assert highfreeze._mid({"yes_bid": "0.0000", "yes_ask": "0.0000"}) is None
    assert highfreeze._mid({"yes_bid": "0.0100", "yes_ask": "0.9900"}) is None
    assert highfreeze._mid({"yes_bid": "0.1200",
                            "yes_ask": "0.1300"}) == pytest.approx(0.125)


def test_rainfreeze_has_no_mkt_leg_off_an_empty_book(tmp_path, monkeypatch,
                                                     capsys):
    journal = tmp_path / "rain-freeze.jsonl"
    row = {"date": "2026-10-21", "city": "NYC", "ticker": "KXRAIN-26OCT21-NYC",
           "raw": 0.2, "yes_bid": "0.0000", "yes_ask": "0.0000"}
    journal.write_text(json.dumps(row) + "\n")
    monkeypatch.setattr(rainfreeze, "JOURNAL", journal)
    monkeypatch.setattr(rainfreeze.kalshi, "get_market",
                        lambda t: {"result": "no"})
    rainfreeze.score()
    out = capsys.readouterr().out
    assert "MKT -" in out
