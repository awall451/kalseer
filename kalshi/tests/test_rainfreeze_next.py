"""rainfreeze.py day-ahead leg: freeze tomorrow's KXRAIN board too.

MKT is the board at 12:01Z on the market's own day, by which time the rain
has usually fallen or been locked in overnight: rainfreeze's MKT Brier was
0.0001 over n=12 (op-2026-10-22), the two wet days already at 0.995. The
judgment step's MINE pre-regs are frozen the day before, so the fair
yardstick for them is the day-ahead board. Tomorrow's market lists ~09Z the
day before (KXRAIN-26OCT23-NYC opened 2026-10-22T09:11Z), so it is live at
the 12Z freeze. These tests pin a `next` block per row and its RAW1 / MKT1
score, leaving the same-day legs as they were.
"""

import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parents[1]))
import rainfreeze
from test_rainfreeze import BOARDS, apis, rows  # noqa: F401  (fixture)


@pytest.fixture
def tomorrow(monkeypatch):
    monkeypatch.setitem(BOARDS, "KXRAIN-26OCT16-DC", {
        "ticker": "KXRAIN-26OCT16-DC", "status": "active",
        "yes_bid_dollars": "0.0800", "yes_ask_dollars": "0.1000"})
    monkeypatch.setitem(BOARDS, "KXRAIN-26OCT16-NYC", {
        "ticker": "KXRAIN-26OCT16-NYC", "status": "active",
        "yes_bid_dollars": "0.3000", "yes_ask_dollars": "0.3200"})


def test_freeze_records_tomorrows_pop_and_board(apis, tomorrow):
    ok, failed = rainfreeze.freeze()
    assert (ok, failed) == (3, [])
    by_city = {r["city"]: r for r in rows()}
    dc = by_city["DC"]
    # the same-day leg is unchanged
    assert dc["date"] == "2026-10-15" and dc["raw"] == 0.77
    nxt = dc["next"]
    assert nxt["date"] == "2026-10-16"
    assert nxt["ticker"] == "KXRAIN-26OCT16-DC"
    assert nxt["raw"] == 0.05  # Friday's daytime PoP
    assert (nxt["yes_bid"], nxt["yes_ask"]) == ("0.0800", "0.1000")
    # NYC's grid shows no 10/16 daytime period: no RAW1, board still frozen
    nyc = by_city["NYC"]["next"]
    assert nyc["raw"] is None and nyc["yes_ask"] == "0.3200"


def test_unlisted_tomorrow_is_not_a_failed_city(apis, capsys):
    # OKC's 10/16 market is not in BOARDS (unlisted / 404)
    ok, failed = rainfreeze.freeze()
    assert (ok, failed) == (3, [])
    okc = {r["city"]: r for r in rows()}["OKC"]
    assert okc["next"]["yes_bid"] is None and okc["next"]["yes_ask"] is None
    assert "KXRAIN-26OCT16-OKC" in capsys.readouterr().err


def _journal(*recs):
    rainfreeze.JOURNAL.write_text("".join(json.dumps(r) + "\n" for r in recs))


def test_score_prints_day_ahead_legs_and_summary(apis, monkeypatch, capsys):
    _journal(
        {"date": "2026-10-15", "city": "DC", "ticker": "KXRAIN-26OCT15-DC",
         "raw": 0.1, "yes_bid": "0.0100", "yes_ask": "0.0200",
         "next": {"date": "2026-10-16", "ticker": "KXRAIN-26OCT16-DC",
                  "raw": 0.05, "yes_bid": "0.2000", "yes_ask": "0.3000"}},
        # a later re-run on 10/15 must not overwrite the binding day-ahead
        {"date": "2026-10-15", "city": "DC", "ticker": "KXRAIN-26OCT15-DC",
         "raw": 0.1, "yes_bid": "0.0100", "yes_ask": "0.0200",
         "next": {"date": "2026-10-16", "ticker": "KXRAIN-26OCT16-DC",
                  "raw": 0.9, "yes_bid": "0.9000", "yes_ask": "0.9100"}},
        {"date": "2026-10-16", "city": "DC", "ticker": "KXRAIN-26OCT16-DC",
         "raw": 0.6, "yes_bid": "0.9900", "yes_ask": "1.0000",
         "next": {"date": "2026-10-17", "ticker": "KXRAIN-26OCT17-DC",
                  "raw": 0.2, "yes_bid": None, "yes_ask": None}},
    )
    results = {"KXRAIN-26OCT15-DC": "no", "KXRAIN-26OCT16-DC": "yes",
               "KXRAIN-26OCT17-DC": ""}
    monkeypatch.setattr(rainfreeze.kalshi, "get_market",
                        lambda t, tries=4: {"ticker": t, "result": results[t]})
    rainfreeze.main(["score"])
    out = capsys.readouterr().out.splitlines()
    by_date = {l.split()[0]: l for l in out if l[:4].isdigit()}
    d16 = by_date["2026-10-16"]
    assert "RAW 0.60 0.1600" in d16 and "MKT 0.995 0.0000" in d16
    assert "RAW1 0.05 0.9025" in d16 and "MKT1 0.25 0.5625" in d16
    # 10/15 had no day-ahead freeze (the journal starts that day)
    assert "RAW1 -" in by_date["2026-10-15"]
    # 10/17 has only its day-ahead row: still listed, pending, empty book
    assert "pending" in by_date["2026-10-17"]
    assert "RAW1 0.20" in by_date["2026-10-17"]
    assert "MKT1 -" in by_date["2026-10-17"]
    # the same-day summary is unchanged; day-ahead gets its own line
    summary = [l for l in out if l.startswith("# n=")][0]
    assert summary.startswith("# n=2")
    ahead = [l for l in out if l.startswith("# day-ahead n=")][0]
    assert ahead.startswith("# day-ahead n=1")
    assert "RAW1 0.9025" in ahead and "MKT1 0.5625" in ahead
