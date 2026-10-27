"""publish.title_map: a cached 404 miss is retried after MISS_DAYS.

Since 10/19 every operator run has flagged "$DATA/title-cache.json holds 10
empty-string misses" for the human to delete by hand. A miss was cached
forever, so tickers that later became resolvable (an event ticker after
#74's event fallback, e.g. KXTRUMPAPPROVE-26OCT18) never got a dashboard
title. These tests pin the dated misses, the retry of legacy undated ones,
and the series-title fallback for passes that name a whole series
(KXHORMUZPEAK).
"""

import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from test_publish import http404, publish  # noqa: F401


@pytest.fixture
def caches(tmp_path, monkeypatch):
    monkeypatch.setattr(publish, "TITLE_CACHE", tmp_path / "title-cache.json")
    monkeypatch.setattr(publish, "TITLE_MISSES", tmp_path / "title-misses.json")
    monkeypatch.setattr(publish, "_today", lambda: "2026-10-27")
    return tmp_path


def all_404(monkeypatch):
    for name in ("get_market", "get_event", "get_series"):
        monkeypatch.setattr(publish.kalshi, name, http404)


def counting(monkeypatch, title="Found"):
    calls = []
    monkeypatch.setattr(publish.kalshi, "get_market",
                        lambda t, tries=1: calls.append(t) or {"title": title})
    return calls


def test_a_404_miss_is_dated(caches, monkeypatch):
    all_404(monkeypatch)
    assert publish.title_map(["KXDEAD-26AUG"], {}) == {}
    misses = json.loads((caches / "title-misses.json").read_text())
    assert misses == {"KXDEAD-26AUG": "2026-10-27"}
    assert "KXDEAD-26AUG" not in json.loads(
        (caches / "title-cache.json").read_text())


def test_a_fresh_miss_is_not_retried(caches, monkeypatch):
    (caches / "title-misses.json").write_text(
        json.dumps({"KXDEAD-26AUG": "2026-10-22"}))
    calls = counting(monkeypatch)
    assert publish.title_map(["KXDEAD-26AUG"], {}) == {}
    assert calls == []


def test_a_stale_miss_is_retried_and_cleared_on_a_hit(caches, monkeypatch):
    (caches / "title-misses.json").write_text(
        json.dumps({"KXDEAD-26AUG": "2026-10-20"}))
    calls = counting(monkeypatch, "Back")
    assert publish.title_map(["KXDEAD-26AUG"], {}) == {"KXDEAD-26AUG": "Back"}
    assert calls == ["KXDEAD-26AUG"]
    assert json.loads((caches / "title-misses.json").read_text()) == {}
    assert json.loads((caches / "title-cache.json").read_text())[
        "KXDEAD-26AUG"] == "Back"


def test_a_stale_miss_that_404s_again_is_redated(caches, monkeypatch):
    (caches / "title-misses.json").write_text(
        json.dumps({"KXDEAD-26AUG": "2026-10-01"}))
    all_404(monkeypatch)
    publish.title_map(["KXDEAD-26AUG"], {})
    assert json.loads((caches / "title-misses.json").read_text()) == {
        "KXDEAD-26AUG": "2026-10-27"}


def test_legacy_empty_cache_entries_are_retried_once(caches, monkeypatch):
    # the 10 pre-dated misses in $DATA/title-cache.json
    (caches / "title-cache.json").write_text(json.dumps(
        {"KXTRUMPAPPROVE-26OCT18": "", "KXRT-ODY": "Odyssey"}))
    calls = counting(monkeypatch, "Approval Oct 18")
    out = publish.title_map(["KXTRUMPAPPROVE-26OCT18", "KXRT-ODY"], {})
    assert out == {"KXTRUMPAPPROVE-26OCT18": "Approval Oct 18",
                   "KXRT-ODY": "Odyssey"}
    assert calls == ["KXTRUMPAPPROVE-26OCT18"]
    cache = json.loads((caches / "title-cache.json").read_text())
    assert "" not in cache.values()


def test_a_series_ticker_falls_back_to_the_series_title(caches, monkeypatch):
    monkeypatch.setattr(publish.kalshi, "get_market", http404)
    monkeypatch.setattr(publish.kalshi, "get_event", http404)
    monkeypatch.setattr(publish.kalshi, "get_series",
                        lambda t, tries=1: {"title": "Hormuz peak transits"})
    assert publish.title_map(["KXHORMUZPEAK"], {}) == {
        "KXHORMUZPEAK": "Hormuz peak transits"}


def test_a_transient_error_is_not_a_miss(caches, monkeypatch):
    def boom(t, tries=1):
        raise OSError("timed out")
    monkeypatch.setattr(publish.kalshi, "get_market", boom)
    publish.title_map(["KXSLOW-26SEP"], {})
    misses = caches / "title-misses.json"
    assert not misses.exists() or json.loads(misses.read_text()) == {}
