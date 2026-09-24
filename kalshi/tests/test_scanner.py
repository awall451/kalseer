"""scanner.py ranking: one event's strike ladder must not crowd the shortlist."""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parents[1]))
import scanner


def row(ticker, event, vol):
    return {"ticker": ticker, "event_ticker": event, "volume_24h": vol}


def test_caps_strikes_per_event_keeping_rank_order():
    rows = [row(f"EV1-{i}", "EV1", 100 - i) for i in range(6)] + [
        row("EV2-1", "EV2", 50), row("EV3-1", "EV3", 40)]
    out = scanner.cap_per_event(rows, 3)
    assert [r["ticker"] for r in out] == [
        "EV1-0", "EV1-1", "EV1-2", "EV2-1", "EV3-1"]


def test_keeps_the_most_liquid_strikes_of_the_capped_event():
    rows = [row("EV1-a", "EV1", 100), row("EV2-a", "EV2", 90),
            row("EV1-b", "EV1", 80), row("EV1-c", "EV1", 70),
            row("EV1-d", "EV1", 60), row("EV2-b", "EV2", 10)]
    out = scanner.cap_per_event(rows, 2)
    assert [r["ticker"] for r in out] == ["EV1-a", "EV2-a", "EV1-b", "EV2-b"]


def test_missing_event_ticker_never_groups_across_markets():
    rows = [row("A", "", 3), row("B", "", 2), row("C", "", 1)]
    assert scanner.cap_per_event(rows, 1) == rows


def test_zero_or_negative_cap_means_no_cap():
    rows = [row(f"EV1-{i}", "EV1", 10 - i) for i in range(5)]
    assert scanner.cap_per_event(rows, 0) == rows


# --- events-based scan: complete coverage, no pagination lottery -------------
# The /markets walk truncated at its page cap inside an 800k+ parlay-heavy
# universe, so whether gas/rain/econ surfaced depended on pagination order
# (three 0-candidate days in Sep 2026). scan() now walks /events, which
# exhausts, and takes the category straight off the event.

import datetime as dt


def market(ticker, hours=24, vol=5000, bid="0.40", ask="0.45"):
    close = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=hours)
    return {"ticker": ticker, "volume_24h_fp": str(vol),
            "yes_bid_dollars": bid, "yes_ask_dollars": ask,
            "close_time": close.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "title": ticker, "rules_primary": "rules"}


def scan_with(monkeypatch, events, **kw):
    monkeypatch.setattr(scanner.kalshi, "iter_events",
                        lambda *a, **k: iter(events))

    def no_backfill(*a, **k):  # categories come from the event now
        raise AssertionError("scan() must not call get_event")
    monkeypatch.setattr(scanner.kalshi, "get_event", no_backfill)
    return scanner.scan(days=7, min_volume=1000, **kw)


def test_scan_keeps_preferred_category_markets_with_event_category(monkeypatch):
    events = [{"event_ticker": "GAS", "category": "Economics",
               "markets": [market("GAS-4.50")]}]
    rows, n_events = scan_with(monkeypatch, events)
    assert [r["ticker"] for r in rows] == ["GAS-4.50"]
    assert rows[0]["category"] == "Economics"
    assert rows[0]["event_ticker"] == "GAS"
    assert n_events == 1


def test_scan_skips_non_preferred_categories_unless_asked(monkeypatch):
    events = [{"event_ticker": "TT", "category": "Sports",
               "markets": [market("TT-MATCH")]}]
    assert scan_with(monkeypatch, events)[0] == []
    rows, _ = scan_with(monkeypatch, events, all_categories=True)
    assert [r["ticker"] for r in rows] == ["TT-MATCH"]


def test_scan_filters_window_volume_price_and_parlays(monkeypatch):
    events = [{"event_ticker": "EV", "category": "Economics", "markets": [
        market("KEEP"),
        market("TOO-FAR", hours=24 * 30),
        market("ALREADY-CLOSED", hours=-2),
        market("THIN", vol=10),
        market("SETTLED-PRICE", ask="1.00"),
        dict(market("PARLAY"), mve_collection_ticker="MVE-1"),
    ]}]
    rows, _ = scan_with(monkeypatch, events)
    assert [r["ticker"] for r in rows] == ["KEEP"]


def test_scan_tolerates_events_without_nested_markets(monkeypatch):
    events = [{"event_ticker": "EMPTY", "category": "Economics"},
              {"event_ticker": "NONE", "category": "World", "markets": None}]
    rows, n_events = scan_with(monkeypatch, events)
    assert rows == [] and n_events == 2
