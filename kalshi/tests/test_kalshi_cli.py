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


# Item #20: the approval feed's settlement source (RCP) is 403 server-side,
# but every settled KXTRUMPAPPROVE market carries that day's RCP average as
# its expiration_value. `history` turns a series' settled markets into a dated
# value series: one line per event when every strike shares the value, one
# line per market when they don't (KXRAIN settles each city separately).
def settled(ticker, event, value, close):
    return {"ticker": ticker, "event_ticker": event, "status": "finalized",
            "result": "no", "expiration_value": value, "close_time": close}


APPROVE = [
    settled("KXTRUMPAPPROVE-26OCT12-E38.1", "KXTRUMPAPPROVE-26OCT12", "38.1",
            "2026-10-12T16:59:00Z"),
    settled("KXTRUMPAPPROVE-26OCT13-A38.4", "KXTRUMPAPPROVE-26OCT13", "38.4",
            "2026-10-13T16:59:00Z"),
    settled("KXTRUMPAPPROVE-26OCT13-E38.4", "KXTRUMPAPPROVE-26OCT13", "38.4",
            "2026-10-13T16:59:00Z"),
    settled("KXTRUMPAPPROVE-26OCT12-U37.5", "KXTRUMPAPPROVE-26OCT12", "38.1",
            "2026-10-12T16:59:00Z"),
]


def test_history_one_line_per_event_newest_first():
    lines = kalshi.fmt_history(APPROVE)
    assert len(lines) == 2
    assert lines[0].split() == ["KXTRUMPAPPROVE-26OCT13", "2026-10-13T16:59:00Z", "38.4"]
    assert lines[1].split() == ["KXTRUMPAPPROVE-26OCT12", "2026-10-12T16:59:00Z", "38.1"]


def test_history_splits_events_whose_markets_settle_differently():
    rain = [settled("KXRAIN-26OCT12-TTN", "KXRAIN-26OCT12", "0.02", "2026-10-13T05:00:00Z"),
            settled("KXRAIN-26OCT12-TPA", "KXRAIN-26OCT12", "0.00", "2026-10-13T05:00:00Z")]
    out = "\n".join(kalshi.fmt_history(rain))
    assert "KXRAIN-26OCT12-TTN" in out and "0.02" in out
    assert "KXRAIN-26OCT12-TPA" in out and "0.00" in out


def test_history_keeps_exact_strings_and_skips_unvalued():
    ms = [settled("KXAAAGASW-26OCT12-4.35", "KXAAAGASW-26OCT12", "4.3550",
                  "2026-10-12T03:59:00Z"),
          settled("KXAAAGASW-26OCT19-4.30", "KXAAAGASW-26OCT19", "",
                  "2026-10-19T03:59:00Z")]
    out = "\n".join(kalshi.fmt_history(ms))
    assert "4.3550" in out             # trailing zero kept: never via float()
    assert "KXAAAGASW-26OCT19" not in out


def test_history_limits_to_newest_n_events():
    lines = kalshi.fmt_history(APPROVE, limit=1)
    assert len(lines) == 1 and "26OCT13" in lines[0]


def test_main_history_reads_settled_markets_of_the_series(monkeypatch, capsys):
    seen = {}

    def fake(series):
        seen["series"] = series
        return APPROVE

    monkeypatch.setattr(kalshi, "settled_markets", fake)
    kalshi.main(["history", "KXTRUMPAPPROVE", "1"])
    out = capsys.readouterr().out
    assert seen == {"series": "KXTRUMPAPPROVE"}
    assert "38.4" in out and "38.1" not in out


def test_settled_markets_follows_the_cursor(monkeypatch):
    pages = {None: {"markets": [APPROVE[0]], "cursor": "c2"},
             "c2": {"markets": [APPROVE[1]], "cursor": ""}}
    calls = []

    def fake_get(path, **params):
        calls.append(params)
        return pages[params.get("cursor")]

    monkeypatch.setattr(kalshi, "_get", fake_get)
    assert kalshi.settled_markets("KXTRUMPAPPROVE") == APPROVE[:2]
    assert all(c["series_ticker"] == "KXTRUMPAPPROVE" and c["status"] == "settled"
               for c in calls)
