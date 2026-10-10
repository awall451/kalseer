"""wx.py CLI: NWS climate-report reads for the rain-family scoring step.

Scoring a climate day means the two-step dance the watchlist records as the
working recipe (HAZARD 1g): list product ids at
/products/types/CLI/locations/{LOC}, then fetch the product text. These tests
pin what that recipe exists for: the newest report is picked by issuanceTime
(not list order), and productText is printed verbatim — the precipitation
line is a settlement source, never reflowed or summarised.
"""

import json
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


# Gap #3 (2026-10-02..10-08): NWS keeps about 7 days of CLI reports, and the
# 10/1 finals had aged out by the time the judgment step came back on 10/9.
# The rain/high-temp settlement source got recovered from MTD arithmetic
# that time. `wx.py archive` is a deterministic pipeline step (like aaa.py)
# that saves every CLI version before it ages out.
@pytest.fixture
def archive_api(monkeypatch):
    products = dict(PRODUCTS)
    products["/products/older-uuid"] = {
        "id": "older-uuid", "issuanceTime": "2026-09-21T06:19:00+00:00",
        "issuingOffice": "KLWX", "productText": "THE 9/20 FINAL"}
    calls = []

    def fake_get(path, tries=3):
        calls.append(path)
        if path not in products:
            raise OSError(f"HTTP 503 for {path}")
        return products[path]
    monkeypatch.setattr(wx, "_get", fake_get)
    return products, calls


def test_archive_saves_every_version_verbatim(archive_api, tmp_path):
    saved, failed = wx.archive(tmp_path, ["DCA"])
    assert (saved, failed) == (3, [])
    out = tmp_path / "wx" / "cli" / "DCA"
    assert sorted(p.name for p in out.iterdir()) == [
        "middle-uuid.json", "newest-uuid.json", "older-uuid.json"]
    rec = json.loads((out / "newest-uuid.json").read_text())
    assert rec["issuanceTime"] == "2026-09-22T06:24:00+00:00"
    assert "  YESTERDAY        0.43   0.11    0.32     29.85" in rec["productText"]


def test_archive_only_fetches_new_versions(archive_api, tmp_path):
    _, calls = archive_api
    wx.archive(tmp_path, ["DCA"])
    calls.clear()
    saved, failed = wx.archive(tmp_path, ["DCA"])
    assert (saved, failed) == (0, [])
    assert calls == ["/products/types/CLI/locations/DCA"]


def test_archive_keeps_going_past_a_bad_location(archive_api, tmp_path):
    saved, failed = wx.archive(tmp_path, ["XXX", "DCA"])
    assert failed == ["XXX"]
    assert saved == 3


def test_archive_skips_a_failed_product_without_a_partial_file(archive_api,
                                                               tmp_path):
    products, _ = archive_api
    del products["/products/middle-uuid"]
    saved, failed = wx.archive(tmp_path, ["DCA"])
    assert (saved, failed) == (2, ["DCA"])
    names = sorted(p.name for p in (tmp_path / "wx" / "cli" / "DCA").iterdir())
    assert names == ["newest-uuid.json", "older-uuid.json"]


def test_archive_refuses_path_like_ids(archive_api, tmp_path):
    products, _ = archive_api
    products["/products/types/CLI/locations/BAD"] = {
        "@graph": [{"id": "../../escape", "issuanceTime": "x"}]}
    saved, failed = wx.archive(tmp_path, ["BAD"])
    assert (saved, failed) == (0, ["BAD"])
    assert not (tmp_path / "escape.json").exists()
    assert not list(tmp_path.rglob("escape*"))


def test_archive_cli_exit_codes(archive_api, tmp_path, monkeypatch):
    monkeypatch.setattr(wx, "DATA", tmp_path)
    # partial failure is a log line, not a failed pipeline step...
    assert wx.main(["archive", "XXX", "DCA"]) in (None, 0)
    # ...but nothing reachable at all is (host down / API moved)
    with pytest.raises(SystemExit) as e:
        wx.main(["archive", "XXX", "YYY"])
    assert e.value.code == 1


def test_default_locations_cover_the_traded_settlement_stations():
    # CLI codes as named in Kalshi's KXRAIN/KXHIGH* rules (checked live
    # 2026-10-10): NOLA settles on CLIMSY, Chicago rain on CLIORD but the
    # high on CLIMDW, Dallas on CLIDFW, Las Vegas on CLILAS.
    for code in ("NYC", "DCA", "OKC", "LAX", "MIA", "MSY", "ATL", "ORD",
                 "MDW", "DFW", "LAS", "PHL", "SFO", "PHX", "DTW"):
        assert code in wx.DEFAULT_LOCATIONS


def test_daily_archives_cli_before_the_judgment_step():
    daily = (pathlib.Path(__file__).parents[2] / "bin" / "daily.sh").read_text()
    step = daily.index("run_step wx")
    assert "kalshi/wx.py archive" in daily[step:daily.index("\n", step)]
    assert step < daily.index("run_step claude")
