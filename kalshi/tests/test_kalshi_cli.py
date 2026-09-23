"""kalshi.py CLI: precise board/rules/settlement reads for the judgment step.

The judgment session used to hand-write a throwaway fetch script into the
data dir every run (the watchlist's "TOOLING RECIPE" hazard). These tests pin
the two properties that recipe existed for: prices come out as the API's
exact dollar strings (display-precision hazard), and rules/settlement fields
are shown, not summarised.
"""

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parents[1]))
import kalshi

OPEN_MARKET = {
    "ticker": "KXAAAGASW-26SEP28-4.4800",
    "status": "active",
    "title": "Will average gas prices be above $4.4800?",
    "yes_sub_title": "Above 4.4800",
    "yes_bid_dollars": "0.43",
    "yes_ask_dollars": "0.45",
    "volume_24h_fp": "3067",
    "open_interest_fp": "12045",
    "close_time": "2026-09-29T14:00:00Z",
    "rules_primary": "If the AAA national average gas price is strictly "
                     "greater than $4.4800 on Sep 28, 2026, then the market "
                     "resolves to Yes.",
}

SETTLED_MARKET = {
    "ticker": "KXRAIN-26SEP21-DC",
    "status": "finalized",
    "title": "Will it rain in Washington DC on Sep 21?",
    "yes_bid_dollars": "1.00",
    "yes_ask_dollars": "1.00",
    "volume_24h_fp": "0",
    "close_time": "2026-09-22T04:00:00Z",
    "result": "yes",
    "expiration_value": "0.43",
    "rules_primary": "Resolves Yes if measurable precipitation is recorded.",
}


def test_fmt_market_keeps_exact_api_strings():
    out = kalshi.fmt_market(OPEN_MARKET)
    assert "KXAAAGASW-26SEP28-4.4800" in out
    # exact strings, never floats: "0.43", not 0.43 rounded through float()
    assert "0.43/0.45" in out
    assert "strictly greater than $4.4800 on Sep 28, 2026" in out
    assert "2026-09-29T14:00:00Z" in out


def test_fmt_market_shows_settlement_fields():
    out = kalshi.fmt_market(SETTLED_MARKET)
    assert "result yes" in out
    assert "expiration_value 0.43" in out


def test_fmt_board_row_is_one_line_with_exact_prices():
    row = kalshi.fmt_board_row(OPEN_MARKET)
    assert "\n" not in row
    assert "0.43" in row and "0.45" in row
    assert "Above 4.4800" in row


def test_fmt_board_row_shows_result_when_settled():
    assert "yes" in kalshi.fmt_board_row(SETTLED_MARKET)


def test_missing_fields_render_as_dash_not_crash():
    out = kalshi.fmt_market({"ticker": "X"})
    assert "-" in out
    assert "\n" not in kalshi.fmt_board_row({"ticker": "X"})


def test_main_market_command_prints_each_ticker(monkeypatch, capsys):
    monkeypatch.setattr(kalshi, "get_market",
                        lambda t: dict(OPEN_MARKET, ticker=t))
    kalshi.main(["market", "T-A", "T-B"])
    out = capsys.readouterr().out
    assert "T-A" in out and "T-B" in out


def test_main_event_command_prints_board(monkeypatch, capsys):
    monkeypatch.setattr(kalshi, "get_event", lambda et: {
        "event_ticker": et, "title": "Gas weekly", "category": "Financials",
        "markets": [OPEN_MARKET, SETTLED_MARKET],
    })
    kalshi.main(["event", "KXAAAGASW-26SEP28"])
    out = capsys.readouterr().out
    assert "Gas weekly" in out
    assert "KXAAAGASW-26SEP28-4.4800" in out
    assert "KXRAIN-26SEP21-DC" in out


def test_main_series_command_passes_status(monkeypatch, capsys):
    seen = {}

    def fake_get_markets(**params):
        seen.update(params)
        return [SETTLED_MARKET]

    monkeypatch.setattr(kalshi, "get_markets", fake_get_markets)
    kalshi.main(["series", "KXRAIN", "settled"])
    assert seen == {"series_ticker": "KXRAIN", "status": "settled"}
    assert "KXRAIN-26SEP21-DC" in capsys.readouterr().out


def test_main_rejects_unknown_command():
    with pytest.raises(SystemExit):
        kalshi.main(["frobnicate"])
    with pytest.raises(SystemExit):
        kalshi.main([])
