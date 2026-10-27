"""publish.title_map: event tickers get the event's title, not a 404.

Daily log 10-18, publish step:
  ! title KXHORMUZWEEKLY-26OCT18: HTTP Error 404: Not Found
  ! title KXTRUMPAPPROVE-26OCT18: HTTP Error 404: Not Found
Both are live EVENTS ("Traffic through the Strait of Hormuz? (10/12 - 10/18)",
"Trump's RCP approval average on Oct 18, 2026?"): the judgment step logs a
pass on a whole ladder by its event ticker, /markets/<event> 404s, and the
miss is cached forever, so the dashboard shows that pass untitled. Most of
the cached misses on 10/19 have this event-ticker shape.
"""

import pathlib
import sys
import urllib.error

sys.path.insert(0, str(pathlib.Path(__file__).parents[1]))
import publish
from test_publish import http404, title_cache  # noqa: F401  (fixture)


def test_event_ticker_falls_back_to_the_event_title(title_cache, monkeypatch,
                                                    capsys):
    calls = []
    monkeypatch.setattr(publish.kalshi, "get_market", http404)
    monkeypatch.setattr(
        publish.kalshi, "get_event",
        lambda t, tries=4: calls.append((t, tries)) or
        {"title": "Traffic through the Strait of Hormuz? (10/12 - 10/18)"})
    out = publish.title_map(["KXHORMUZWEEKLY-26OCT18"], {})
    assert out == {"KXHORMUZWEEKLY-26OCT18":
                   "Traffic through the Strait of Hormuz? (10/12 - 10/18)"}
    assert calls == [("KXHORMUZWEEKLY-26OCT18", 1)]  # one shot, no backoff
    assert "! title" not in capsys.readouterr().out


def test_event_title_is_cached_like_a_market_title(title_cache, monkeypatch):
    monkeypatch.setattr(publish.kalshi, "get_market", http404)
    monkeypatch.setattr(publish.kalshi, "get_event",
                        lambda t, tries=4: {"title": "RCP **approval**"})
    publish.title_map(["KXTRUMPAPPROVE-26OCT18"], {})
    monkeypatch.setattr(publish.kalshi, "get_market", None)
    monkeypatch.setattr(publish.kalshi, "get_event", None)
    out = publish.title_map(["KXTRUMPAPPROVE-26OCT18"], {})
    assert out == {"KXTRUMPAPPROVE-26OCT18": "RCP approval"}


def test_both_404_is_still_a_cached_miss(title_cache, monkeypatch, capsys):
    monkeypatch.setattr(publish.kalshi, "get_market", http404)
    monkeypatch.setattr(publish.kalshi, "get_event", http404)
    monkeypatch.setattr(publish.kalshi, "get_series", http404)
    assert publish.title_map(["KXDEAD-26AUG"], {}) == {}
    assert "! title KXDEAD-26AUG" in capsys.readouterr().out
    monkeypatch.setattr(publish.kalshi, "get_market", None)
    monkeypatch.setattr(publish.kalshi, "get_event", None)
    assert publish.title_map(["KXDEAD-26AUG"], {}) == {}


def test_event_lookup_transient_error_retries_next_run(title_cache,
                                                       monkeypatch):
    def boom(t, tries=4):
        raise OSError("timed out")
    monkeypatch.setattr(publish.kalshi, "get_market", http404)
    monkeypatch.setattr(publish.kalshi, "get_event", boom)
    assert publish.title_map(["KXSLOW-26OCT18"], {}) == {}
    monkeypatch.setattr(publish.kalshi, "get_event",
                        lambda t, tries=4: {"title": "Recovered"})
    assert publish.title_map(["KXSLOW-26OCT18"], {}) == {
        "KXSLOW-26OCT18": "Recovered"}


def test_get_event_passes_tries_through(monkeypatch):
    seen = {}

    def fake_get(path, tries=4, **params):
        seen.update(path=path, tries=tries, **params)
        return {"event": {"title": "x"}}
    monkeypatch.setattr(publish.kalshi, "_get", fake_get)
    publish.kalshi.get_event("KXE-1", tries=1)
    assert seen["tries"] == 1 and seen["path"] == "/events/KXE-1"
    assert seen["with_nested_markets"] is True
    publish.kalshi.get_event("KXE-1")
    assert seen["tries"] == 4
