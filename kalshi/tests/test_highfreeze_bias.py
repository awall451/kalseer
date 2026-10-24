"""highfreeze.py score: per-city grid bias and a bias-corrected BIAS leg.

The pooled "grid bias -2.7F" summary hides the one number the judgment step
tracks by hand: LAX's ("Grid-bias ledger: +7/+8/+7/+7/+5/+6. MKT keeps
beating RAW at LAX", brief 10/23). MINE at LAX was a hand bias correction
("grid +5F offshore bias from n=1") and was retired after losing to the
board four days running. A mechanical BIAS leg (RAW recentred by the city's
trailing grid error over earlier settled days only, no lookahead) asks the
same question every day without judgment, and scores against MKT.
"""

import json
import math
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parents[1]))
import highfreeze

DAYS = ["2026-10-18", "2026-10-19", "2026-10-20", "2026-10-21"]


def event(day):
    return highfreeze.event_ticker("LAX", day)


def buckets(day):
    e = event(day)
    return [
        {"ticker": f"{e}-T74", "strike_type": "less", "floor": None,
         "cap": 74, "yes_bid": "0.0400", "yes_ask": "0.0600"},
        {"ticker": f"{e}-B74.5", "strike_type": "between", "floor": 74,
         "cap": 75, "yes_bid": "0.1400", "yes_ask": "0.1600"},
        {"ticker": f"{e}-B76.5", "strike_type": "between", "floor": 76,
         "cap": 77, "yes_bid": "0.4400", "yes_ask": "0.4600"},
        {"ticker": f"{e}-B78.5", "strike_type": "between", "floor": 78,
         "cap": 79, "yes_bid": "0.2400", "yes_ask": "0.2600"},
        {"ticker": f"{e}-T79", "strike_type": "greater", "floor": 79,
         "cap": None, "yes_bid": "0.0900", "yes_ask": "0.1100"}]


@pytest.fixture
def lax(tmp_path, monkeypatch):
    """Grid 70 every day; the max settles 77 (grid low by 7) each day."""
    journal = tmp_path / "high-freeze.jsonl"
    journal.write_text("".join(json.dumps(
        {"city": "LAX", "date": d, "event": event(d), "high": 70,
         "buckets": buckets(d)}) + "\n" for d in DAYS))
    monkeypatch.setattr(highfreeze, "JOURNAL", journal)

    tickers = {event(d): [b["ticker"] for b in buckets(d)] for d in DAYS}

    def get_event(ticker):
        return {"markets": [
            {"ticker": t, "expiration_value": "77",
             "result": "yes" if t.endswith("B76.5") else "no"}
            for t in tickers[ticker]]}
    monkeypatch.setattr(highfreeze.kalshi, "get_event", get_event)


def lines(capsys):
    return capsys.readouterr().out.splitlines()


def test_bias_leg_waits_for_three_earlier_settled_days(lax, capsys):
    highfreeze.score()
    out = lines(capsys)
    for d in DAYS[:3]:
        line = [l for l in out if l.startswith(f"{d}  LAX")][0]
        assert "BIAS -" in line


def test_bias_leg_recentres_raw_by_the_trailing_grid_error(lax, capsys):
    highfreeze.score()
    line = [l for l in lines(capsys) if l.startswith(f"{DAYS[3]}  LAX")][0]
    # centre 70 + 7 = 77; "76 to 77" is 75.5 < X < 77.5
    cdf = lambda x: 0.5 * (1 + math.erf((x - 77) / (3 * math.sqrt(2))))
    assert f"BIAS p {cdf(77.5) - cdf(75.5):.4f}" in line
    assert "RAW p" in line and "MKT p 0.4500" in line


def test_per_city_grid_bias_lines_and_bias_vs_mkt_summary(lax, capsys):
    highfreeze.score()
    out = lines(capsys)
    assert "# LAX: n=4 grid bias -7.0F MAE 7.0F" in out
    summary = out[-1]
    assert summary.startswith("# n=4 ")
    # BIAS is compared with MKT only on days that have both
    assert "BIAS B" in summary and "vs MKT B" in summary
    assert "(n=1)" in summary


def test_no_bias_summary_without_a_bias_leg(lax, capsys, monkeypatch):
    monkeypatch.setattr(highfreeze, "BIAS_MIN", 9)
    highfreeze.score()
    out = lines(capsys)
    assert all("BIAS -" in l for l in out if "  LAX  " in l)
    assert "BIAS B" not in out[-1]
