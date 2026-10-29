"""highfreeze.py score: a bucket-label day gets its grid error from the CLI.

Since #99 a day Kalshi settles with the winning bucket's label ('70° to
71°', KXHIGHLAX-26OCT22) prints "no grid error", because the label doesn't
give the max to the degree. op-10-28 note (b): the pipeline already archives
every CLI version (wx.py archive -> $DATA/wx/cli/<LOC>/), so read the newest
FINAL report for that station and day instead. Preliminary 'VALID TODAY AS
OF' / 'VALID AS OF' reports don't count. The CLI max is used only if it lands in
the bucket Kalshi settled YES. Otherwise the day stays out of the ledger, with
a tag saying why. LAX 10/22 shows why the newest final matters: CLILAX said 72
at 08:48Z and 71 at 23:44Z, and Kalshi settled 70-71.
"""

import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parents[1]))
import highfreeze
from test_highfreeze_bias import buckets, event

DAY = "2026-10-22"


def product(day_words, maximum, prelim=None):
    valid = f"\n{prelim}\n" if prelim else "\n"
    return ("000\nCDUS46 KLOX 230848\nCLILAX\n\nCLIMATE REPORT \n\n"
            "...THE LOS ANGELES INTL AIRPORT CA CLIMATE SUMMARY FOR "
            f"{day_words}...{valid}\nCLIMATE NORMAL PERIOD: 1991 TO 2020\n\n"
            "TEMPERATURE (F)\n YESTERDAY\n"
            f"  MAXIMUM        {maximum}   1:32 PM  91    1973  74      1\n"
            "  MINIMUM         60   3:45 AM  47    1949  58      2\n")


def archive(root, loc, versions):
    d = root / "cli" / loc
    d.mkdir(parents=True, exist_ok=True)
    for i, (issued, text) in enumerate(versions):
        (d / f"id-{i}.json").write_text(json.dumps(
            {"id": f"id-{i}", "issuanceTime": issued,
             "issuingOffice": "KLOX", "productText": text}))


@pytest.fixture
def labelled(tmp_path, monkeypatch):
    journal = tmp_path / "high-freeze.jsonl"
    journal.write_text(json.dumps(
        {"city": "LAX", "date": DAY, "event": event(DAY), "high": 76,
         "buckets": buckets(DAY)}) + "\n")
    monkeypatch.setattr(highfreeze, "JOURNAL", journal)
    monkeypatch.setattr(highfreeze, "EXTRA", {}, raising=False)
    monkeypatch.setattr(highfreeze.kalshi, "get_event", lambda t: {
        "markets": [{"ticker": b["ticker"], "expiration_value": "76° to 77°",
                     "result": "yes" if b["ticker"].endswith("B76.5")
                     else "no"} for b in buckets(DAY)]})
    return tmp_path


def row(capsys):
    out = capsys.readouterr().out.splitlines()
    return next(l for l in out if l.startswith(DAY)), out


def test_newest_final_cli_max_gives_the_grid_error(labelled, capsys):
    archive(labelled, "LAX", [
        ("2026-10-23T01:33:00+00:00", product(
            "OCTOBER 22 2026", 79, "VALID TODAY AS OF 0500 PM LOCAL TIME.")),
        ("2026-10-23T08:48:00+00:00", product("OCTOBER 22 2026", 78)),
        ("2026-10-23T23:44:00+00:00", product("OCTOBER 22 2026", 77)),
        ("2026-10-24T08:39:00+00:00", product("OCTOBER 23 2026", 70))])
    highfreeze.score()
    line, out = row(capsys)
    assert line.startswith(f"{DAY}  LAX  77  grid 76 err -1  "
                           "(CLI max: Kalshi settled '76° to 77°')")
    assert "RAW p " in line and "MKT p 0.4500" in line
    assert any(l.startswith("# LAX: n=1 grid bias -1.0F") for l in out)
    assert any(l.startswith("# n=1 settled city-days") for l in out)


def test_cli_max_outside_the_winning_bucket_is_not_used(labelled, capsys):
    archive(labelled, "LAX", [
        ("2026-10-23T08:48:00+00:00", product("OCTOBER 22 2026", 79))])
    highfreeze.score()
    line, out = row(capsys)
    assert line.startswith(f"{DAY}  LAX  76° to 77°  grid 76 err -  ")
    assert "(bucket label; CLI max 79 outside it: no grid error)" in line
    assert not any(l.startswith("# n=") for l in out)


def test_only_preliminary_reports_mean_no_cli_max(labelled, capsys):
    archive(labelled, "LAX", [
        ("2026-10-23T01:33:00+00:00", product(
            "OCTOBER 22 2026", 77, "VALID AS OF 1100 AM LOCAL TIME."))])
    highfreeze.score()
    line, _ = row(capsys)
    assert "(bucket label: no grid error)" in line


def test_cli_max_parsing(tmp_path, monkeypatch):
    monkeypatch.setattr(highfreeze, "JOURNAL", tmp_path / "high-freeze.jsonl")
    archive(tmp_path, "MDW", [
        ("2026-10-23T08:40:00+00:00", product("OCTOBER 22 2026", "101R")),
        ("2026-10-24T08:40:00+00:00", product("OCTOBER 23 2026", "MM")),
        ("2026-10-06T08:40:00+00:00", product("OCTOBER 5 2026", 64))])
    # CHI settles on CLIMDW (Midway), not the market suffix
    assert highfreeze.cli_max("CHI", "2026-10-22") == 101
    assert highfreeze.cli_max("CHI", "2026-10-23") is None
    assert highfreeze.cli_max("CHI", "2026-10-05") == 64
    assert highfreeze.cli_max("CHI", "2026-10-21") is None
    assert highfreeze.cli_max("LAX", "2026-10-22") is None  # nothing archived


def test_every_city_has_a_cli_station():
    assert set(highfreeze.CLI_STATION) == set(highfreeze.CITIES) | set(
        highfreeze.EXTRA)


def test_in_bucket_edges():
    less = {"strike_type": "less", "floor": None, "cap": 87}
    between = {"strike_type": "between", "floor": 70, "cap": 71}
    greater = {"strike_type": "greater", "floor": 94, "cap": None}
    assert highfreeze._in_bucket(86, less) and not highfreeze._in_bucket(87, less)
    assert highfreeze._in_bucket(70, between) and highfreeze._in_bucket(71, between)
    assert not highfreeze._in_bucket(72, between)
    assert highfreeze._in_bucket(95, greater)
    assert not highfreeze._in_bucket(94, greater)
