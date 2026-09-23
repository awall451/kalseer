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
