"""aaa.py: deterministic capture of the AAA national-average print.

The gas/diesel series settles real markets, and until this step existed a
print was only captured if the judgment session's own page fetch succeeded —
pipeline gap #2 (12 lost runs, Sep 2026) nearly lost the series for good.
These tests pin the two properties the step exists for: the raw page is
archived BEFORE parsing (a successful fetch can never lose a print), and
prices land in the journal as the page's exact strings (display-precision
hazard — AAA prints 4 decimals; never round them through float).
"""

import gzip
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parents[1]))
import aaa

# Shaped like the live page: the national-average table is one of several
# tables, headed by the grade columns, with the five retention rows AAA
# keeps (current/yesterday/week/month/year — the recovery cells the
# judgment session used to backfill gap #2).
PAGE = """
<html><body>
<table class="sidebar-junk"><tr><td>ad</td><td>$9.99</td></tr></table>
<h2>National average gas prices</h2>
<table class="table-mob">
  <thead>
    <tr><th></th><th>Regular</th><th>Mid-Grade</th><th>Premium</th><th>Diesel</th></tr>
  </thead>
  <tbody>
    <tr><td>Current Avg.</td><td>$4.4744</td><td>$4.9012</td><td>$5.2330</td><td>$6.5217</td></tr>
    <tr><td>Yesterday Avg.</td><td>$4.4750</td><td>$4.9020</td><td>$5.2341</td><td>$6.5276</td></tr>
    <tr><td>Week Ago Avg.</td><td>$4.4425</td><td>$4.8700</td><td>$5.2001</td><td>$6.5100</td></tr>
    <tr><td>Month Ago Avg.</td><td>$4.3010</td><td>$4.7300</td><td>$5.0600</td><td>$6.4000</td></tr>
    <tr><td>Year Ago Avg.</td><td>$3.8100</td><td>$4.2400</td><td>$4.5800</td><td>$5.9000</td></tr>
  </tbody>
</table>
</body></html>
"""


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(aaa, "AAA_DIR", tmp_path / "aaa")
    monkeypatch.setattr(aaa, "RAW_DIR", tmp_path / "aaa" / "raw")
    monkeypatch.setattr(aaa, "JOURNAL", tmp_path / "aaa" / "prints.jsonl")
    return tmp_path


def test_parse_keeps_exact_4_decimal_strings():
    rows = aaa.parse(PAGE)
    assert rows["current"]["regular"] == "$4.4744"
    assert rows["current"]["diesel"] == "$6.5217"
    assert rows["yesterday"]["regular"] == "$4.4750"
    assert rows["week_ago"]["regular"] == "$4.4425"
    assert rows["month_ago"]["diesel"] == "$6.4000"
    assert rows["year_ago"]["premium"] == "$4.5800"


def test_parse_maps_all_grades_from_the_header():
    rows = aaa.parse(PAGE)
    assert set(rows["current"]) == {"regular", "mid_grade", "premium", "diesel"}


def test_parse_ignores_other_tables_on_the_page():
    # the sidebar table carries a price-shaped string; it must not win
    rows = aaa.parse(PAGE)
    assert "$9.99" not in json.dumps(rows)


def test_parse_survives_a_dropped_year_ago_row():
    page = "\n".join(l for l in PAGE.splitlines() if "Year Ago" not in l)
    rows = aaa.parse(page)
    assert "year_ago" not in rows
    assert rows["current"]["regular"] == "$4.4744"


def test_parse_fails_loudly_without_the_table():
    with pytest.raises(aaa.ParseError):
        aaa.parse("<html><body><p>maintenance</p></body></html>")


def test_parse_fails_loudly_when_current_row_is_not_priced():
    page = PAGE.replace("$4.4744", "—").replace("$4.9012", "—") \
               .replace("$5.2330", "—").replace("$6.5217", "—")
    with pytest.raises(aaa.ParseError):
        aaa.parse(page)


def test_main_archives_raw_and_appends_exact_journal_line(data_dir, monkeypatch):
    monkeypatch.setattr(aaa, "fetch", lambda: PAGE)
    assert aaa.main([]) == 0
    raws = list((data_dir / "aaa" / "raw").glob("aaa-*.html.gz"))
    assert len(raws) == 1
    assert gzip.decompress(raws[0].read_bytes()).decode() == PAGE
    lines = (data_dir / "aaa" / "prints.jsonl").read_text().splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["prices"]["current"]["regular"] == "$4.4744"
    assert rec["prices"]["current"]["diesel"] == "$6.5217"
    assert rec["date"] and rec["fetched_at"]
    # the journal line names its raw page so a bad parse is always auditable
    assert rec["raw"] == f"aaa/raw/{raws[0].name}"


def test_main_is_append_only_across_reruns(data_dir, monkeypatch):
    monkeypatch.setattr(aaa, "fetch", lambda: PAGE)
    assert aaa.main([]) == 0
    assert aaa.main([]) == 0
    lines = (data_dir / "aaa" / "prints.jsonl").read_text().splitlines()
    assert len(lines) == 2  # append-only journal; consumers take the last line per date


def test_main_archives_raw_even_when_parse_fails(data_dir, monkeypatch, capsys):
    monkeypatch.setattr(aaa, "fetch", lambda: "<html>redesigned page</html>")
    assert aaa.main([]) == 2
    assert list((data_dir / "aaa" / "raw").glob("aaa-*.html.gz"))  # print recoverable
    assert not (data_dir / "aaa" / "prints.jsonl").exists()
    assert "parse failed" in capsys.readouterr().err


def test_main_exit_1_when_fetch_fails(data_dir, monkeypatch, capsys):
    def boom():
        raise OSError("connection refused")
    monkeypatch.setattr(aaa, "fetch", boom)
    assert aaa.main([]) == 1
    assert not (data_dir / "aaa").exists()
    assert "fetch failed" in capsys.readouterr().err


def test_reparse_prints_json_without_touching_the_journal(data_dir, tmp_path, capsys):
    gz = tmp_path / "aaa-2026-09-16.html.gz"
    gz.write_bytes(gzip.compress(PAGE.encode()))
    assert aaa.main(["--parse", str(gz)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["current"]["regular"] == "$4.4744"
    assert not (data_dir / "aaa" / "prints.jsonl").exists()
