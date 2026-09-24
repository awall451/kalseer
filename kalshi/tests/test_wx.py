"""wx.py CLI: NWS climate-report reads for the rain-family scoring step.

Scoring a climate day means the two-step dance the watchlist records as the
working recipe (HAZARD 1g): list product ids at
/products/types/CLI/locations/{LOC}, then fetch the product text. These tests
pin what that recipe exists for: the newest report is picked by issuanceTime
(not list order), and productText is printed verbatim — the precipitation
line is a settlement source, never reflowed or summarised.
"""

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parents[1]))
import wx

REPORT_TEXT = """
CLIMATE REPORT
NATIONAL WEATHER SERVICE BALTIMORE/WASHINGTON
624 AM EDT TUE SEP 22 2026

...THE WASHINGTON DC CLIMATE SUMMARY FOR SEPTEMBER 21 2026...

PRECIPITATION (IN)
  YESTERDAY        0.43   0.11    0.32     29.85
"""

LISTING = {
    "@graph": [
        {"id": "older-uuid", "issuanceTime": "2026-09-21T06:19:00+00:00",
         "issuingOffice": "KLWX", "productCode": "CLI",
         "productName": "Climatological Report (Daily)"},
        # newest deliberately NOT first: order must come from issuanceTime
        {"id": "newest-uuid", "issuanceTime": "2026-09-22T06:24:00+00:00",
         "issuingOffice": "KLWX", "productCode": "CLI",
         "productName": "Climatological Report (Daily)"},
        {"id": "middle-uuid", "issuanceTime": "2026-09-21T16:41:00+00:00",
         "issuingOffice": "KLWX", "productCode": "CLI",
         "productName": "Climatological Report (Daily)"},
    ]
}

PRODUCTS = {
    "/products/types/CLI/locations/DCA": LISTING,
    "/products/newest-uuid": {"id": "newest-uuid",
                              "issuanceTime": "2026-09-22T06:24:00+00:00",
                              "productText": REPORT_TEXT},
    "/products/middle-uuid": {"id": "middle-uuid",
                              "issuanceTime": "2026-09-21T16:41:00+00:00",
                              "productText": "AN OLDER VERSION"},
}


@pytest.fixture
def api(monkeypatch):
    calls = []

    def fake_get(path, tries=3):
        calls.append(path)
        try:
            return PRODUCTS[path]
        except KeyError:
            raise ValueError(f"unexpected path {path}")
    monkeypatch.setattr(wx, "_get", fake_get)
    return calls


def test_cli_prints_the_newest_report_by_issuance_time(api, capsys):
    wx.main(["cli", "DCA"])
    out = capsys.readouterr().out
    assert "PRECIPITATION" in out
    assert "2026-09-22T06:24:00+00:00" in out       # header names the issuance
    assert "AN OLDER VERSION" not in out
    assert "/products/newest-uuid" in api


def test_cli_report_text_is_verbatim(api, capsys):
    wx.main(["cli", "DCA"])
    # exact-string hazard: the precipitation line keeps its spacing
    assert "  YESTERDAY        0.43   0.11    0.32     29.85" \
        in capsys.readouterr().out


def test_cli_list_shows_every_version_without_fetching_any(api, capsys):
    wx.main(["cli", "DCA", "--list"])
    out = capsys.readouterr().out.splitlines()
    assert len(out) == 3
    assert out[0].startswith("2026-09-22T06:24:00+00:00")  # newest first
    assert "newest-uuid" in out[0] and "older-uuid" in out[2]
    assert api == ["/products/types/CLI/locations/DCA"]


def test_cli_id_fetches_that_exact_version(api, capsys):
    wx.main(["cli", "DCA", "--id", "middle-uuid"])
    assert "AN OLDER VERSION" in capsys.readouterr().out
    assert api == ["/products/middle-uuid"]


def test_cli_empty_listing_fails_loudly(api, monkeypatch, capsys):
    monkeypatch.setitem(PRODUCTS, "/products/types/CLI/locations/XXX",
                        {"@graph": []})
    with pytest.raises(SystemExit):
        wx.main(["cli", "XXX"])
    assert "no CLI products" in capsys.readouterr().err


def test_usage_on_bad_args():
    with pytest.raises(SystemExit):
        wx.main([])
    with pytest.raises(SystemExit):
        wx.main(["cli"])
