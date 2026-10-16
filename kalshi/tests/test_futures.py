"""futures.py CLI: dated daily futures closes for the gas/diesel boards.

Item #23 follow-up (brief 10/15): freightwaves.com gave the judgment step
dated CME ULSD settles and verified the 10/13 diesel shock, but "a dated
RBOB source would help the gas boards the same way". WebSearch for dated
RBOB/ULSD settlements came back thin twice (10/12, 10/13) and eia.gov's
daily spot lags. Yahoo's v8 chart endpoint serves dated daily bars for the
NYMEX front months (RB=F, HO=F, CL=F, BZ=F) as public JSON, no key. These
tests pin that documented shape (chart.result[0].meta/timestamp/
indicators.quote[0].close, chart.error on failure); drift must fail loudly,
never print an undated or misdated price a board read would trust.
"""

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parents[1]))
import futures

EDT = -14400  # gmtoffset Yahoo reports for NYMEX in October


def ts(day, hour=0, offset=EDT):
    """Unix time of 2026-10-<day> <hour>:00 in exchange-local time."""
    return 1791849600 + (day - 13) * 86400 + hour * 3600 - offset


def body(symbol, stamps, closes, offset=EDT, last=None):
    meta = {"currency": "USD", "symbol": symbol, "exchangeName": "NYM",
            "exchangeTimezoneName": "America/New_York", "gmtoffset": offset}
    if last:
        meta["regularMarketPrice"], meta["regularMarketTime"] = last
    return {"chart": {"error": None, "result": [{
        "meta": meta, "timestamp": stamps,
        "indicators": {"quote": [{"close": closes}]}}]}}


@pytest.fixture
def api(monkeypatch):
    """Capture requested symbols; serve canned Yahoo v8 chart responses."""
    state = {"calls": [], "response": body(
        "HO=F", [ts(9), ts(12), ts(13)], [4.5694, 4.7232, 4.934400081634521],
        last=(4.9344, ts(13, 14)))}

    def fake_fetch(symbol):
        state["calls"].append(symbol)
        return state["response"]
    monkeypatch.setattr(futures, "_fetch", fake_fetch)
    return state


def data_lines(capsys):
    return [line for line in capsys.readouterr().out.splitlines()
            if not line.startswith("#")]


def test_ts_helper_is_exchange_local_midnight():
    # 2026-10-13 00:00 EDT == 04:00Z
    import datetime
    assert (datetime.datetime.fromtimestamp(ts(13), datetime.UTC)
            == datetime.datetime(2026, 10, 13, 4, tzinfo=datetime.UTC))


def test_closes_print_dated_newest_first(api, capsys):
    futures.main(["closes", "ulsd"])
    lines = data_lines(capsys)
    assert lines[0].startswith("2026-10-13  4.9344")
    assert lines[1].startswith("2026-10-12  4.7232")
    assert lines[2].startswith("2026-10-09  4.5694")


def test_day_change_on_each_line_but_the_oldest(api, capsys):
    # FreightWaves 10/13: ULSD +21c in one day — the d/d column must say so
    futures.main(["closes", "ulsd"])
    lines = data_lines(capsys)
    assert "d/d +0.2112" in lines[0]
    assert "d/d +0.1538" in lines[1]
    assert "d/d" not in lines[2]


def test_newest_row_is_marked_latest(api, capsys):
    futures.main(["closes", "ulsd"])
    lines = data_lines(capsys)
    assert "latest" in lines[0]
    assert "latest" not in lines[1]


def test_aliases_map_to_front_month_symbols(api, capsys):
    for alias, symbol in [("rbob", "RB=F"), ("ulsd", "HO=F"), ("ho", "HO=F"),
                          ("wti", "CL=F"), ("brent", "BZ=F")]:
        api["calls"].clear()
        futures.main(["closes", alias])
        assert api["calls"] == [symbol], alias


def test_raw_symbol_passes_through_for_a_specific_contract(api, capsys):
    futures.main(["closes", "RBX26.NYM"])
    assert api["calls"] == ["RBX26.NYM"]


def test_session_start_stamps_date_to_the_trading_day(api, capsys):
    # If bars are stamped at Globex open (18:00 the evening before), the
    # row must still carry the trading day it settles on.
    api["response"] = body("RB=F", [ts(12, -6), ts(13, -6)], [1.95, 1.97])
    futures.main(["closes", "rbob"])
    lines = data_lines(capsys)
    assert lines[0].startswith("2026-10-13  1.9700")
    assert lines[1].startswith("2026-10-12  1.9500")


def test_null_close_bars_are_skipped_not_printed_as_zero(api, capsys):
    api["response"] = body("RB=F", [ts(9), ts(12), ts(13)], [1.9, None, 1.97])
    futures.main(["closes", "rbob"])
    lines = data_lines(capsys)
    assert len(lines) == 2
    assert lines[0].startswith("2026-10-13  1.9700  d/d +0.0700")


def test_days_option_limits_rows(api, capsys):
    futures.main(["closes", "ulsd", "--days", "2"])
    assert len(data_lines(capsys)) == 2


def test_footer_names_symbol_and_last_trade_time(api, capsys):
    futures.main(["closes", "ulsd"])
    out = capsys.readouterr().out
    footer = [l for l in out.splitlines() if l.startswith("#")][-1]
    assert "ulsd = HO=F" in footer
    assert "latest 2026-10-13 = 4.9344" in footer
    assert "last trade 4.9344 at 2026-10-13 14:00 America/New_York" in footer


def test_chart_error_is_a_loud_exit(api, capsys):
    api["response"] = {"chart": {"result": None, "error": {
        "code": "Not Found",
        "description": "No data found, symbol may be delisted"}}}
    with pytest.raises(SystemExit) as e:
        futures.main(["closes", "RBZ99.NYM"])
    assert e.value.code == 2
    assert "symbol may be delisted" in capsys.readouterr().err


def test_unexpected_shape_is_a_loud_exit(api, capsys):
    api["response"] = {"finance": {"error": "Too Many Requests"}}
    with pytest.raises(SystemExit) as e:
        futures.main(["closes", "rbob"])
    assert e.value.code == 2
    assert "unexpected response shape" in capsys.readouterr().err


def test_mismatched_timestamp_and_close_lengths_are_a_loud_exit(api, capsys):
    api["response"] = body("RB=F", [ts(12), ts(13)], [1.97])
    with pytest.raises(SystemExit) as e:
        futures.main(["closes", "rbob"])
    assert e.value.code == 2


def test_usage_without_subcommand(api):
    with pytest.raises(SystemExit) as e:
        futures.main([])
    assert "closes" in str(e.value.code)
    assert api["calls"] == []


def test_fetch_falls_back_to_query2_host(monkeypatch):
    import io
    import json
    import urllib.error
    hosts = []

    def fake_urlopen(req, timeout):
        hosts.append(req.full_url.split("/")[2])
        if len(hosts) == 1:
            raise urllib.error.HTTPError(req.full_url, 429, "Too Many", {},
                                         None)
        return io.BytesIO(json.dumps({"chart": {"result": []}}).encode())
    monkeypatch.setattr(futures.urllib.request, "urlopen", fake_urlopen)
    assert futures._fetch("RB=F") == {"chart": {"result": []}}
    assert hosts == ["query1.finance.yahoo.com", "query2.finance.yahoo.com"]
