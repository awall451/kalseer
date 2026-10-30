"""portwatch.py CLI: IMF PortWatch chokepoint reads for the Hormuz family.

The settlement source has been dark since 9/3 behind harness fetch rules
(item #17: WebFetch 'Invalid URL', then the curl fallback's quoted-URL
mismatch). urllib is the proven path from the judgment host, so this CLI
queries the ArcGIS FeatureServer directly. These tests pin the hazards the
watchlist records for the source: the shared per-minute quota (HAZARD 1b:
cap attempts, surface the server message, never sleep out the 60s window),
ArcGIS errors arriving as HTTP-200 JSON bodies, and the difference between
"blocked" and "published nothing" — a publication halt is a legitimate
answer that gates trading (the mostly-published-window rule), not a fetch
failure.
"""

import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parents[1]))
import portwatch

# epoch ms for 2026-09-15 / 2026-09-16 00:00 UTC — ArcGIS date fields
SEP15 = 1789430400000
SEP16 = 1789516800000

ROWS = {
    "features": [
        # newest deliberately NOT first: order must come from the tool
        {"attributes": {"date": SEP15, "n_total": 4}},
        {"attributes": {"date": SEP16, "n_total": 1}},
    ]
}

QUOTA_ERROR = {
    "error": {
        "code": 429,
        "message": "API calls quota exceeded! maximum allowed request "
                   "units (6000) per Minute. Retry after 60 sec.",
        "details": [],
    }
}


@pytest.fixture
def api(monkeypatch):
    """Capture query params; serve canned ArcGIS responses."""
    state = {"calls": [], "response": ROWS}

    def fake_query(params, tries=2):
        state["calls"].append(dict(params))
        return state["response"]
    monkeypatch.setattr(portwatch, "_query", fake_query)
    return state


def test_calls_prints_one_line_per_day_newest_first(api, capsys):
    portwatch.main(["calls", "--since", "2026-09-01"])
    out = capsys.readouterr().out.splitlines()
    data = [line for line in out if not line.startswith("#")]
    assert data == ["2026-09-16  1", "2026-09-15  4"]


def test_calls_summary_names_the_newest_published_day(api, capsys):
    portwatch.main(["calls", "--since", "2026-09-01"])
    summary = [line for line in capsys.readouterr().out.splitlines()
               if line.startswith("#")]
    # the publication lag is the standing trade gate (mostly-published rule)
    assert any("newest published day: 2026-09-16" in line
               for line in summary)


def test_query_filters_port_since_and_asks_for_exact_fields(api, capsys):
    portwatch.main(["calls", "--since", "2026-09-01"])
    (params,) = api["calls"]
    assert params["where"] == ("portname LIKE '%Hormuz%' AND "
                               "date >= TIMESTAMP '2026-09-01'")
    assert params["outFields"] == "date,n_total"
    assert params["orderByFields"] == "date DESC"
    assert params["f"] == "json"


def test_port_option_swaps_the_chokepoint(api, capsys):
    portwatch.main(["calls", "--port", "Suez", "--since", "2026-09-01"])
    (params,) = api["calls"]
    assert "portname LIKE '%Suez%'" in params["where"]


def test_default_since_is_a_date_not_a_crash(api, capsys):
    portwatch.main(["calls"])
    (params,) = api["calls"]
    assert "date >= TIMESTAMP '20" in params["where"]


def test_empty_result_is_a_publication_answer_not_an_error(api, capsys):
    api["response"] = {"features": []}
    portwatch.main(["calls", "--since", "2026-09-01"])  # exit 0
    out = capsys.readouterr().out
    assert "# no published days" in out


def test_arcgis_error_body_fails_loudly_and_is_not_retried(monkeypatch,
                                                           capsys):
    """HAZARD 1b: quota errors arrive as HTTP-200 JSON bodies and clear by
    the minute — burning retries inside one run is how 8/25 lost the
    settlement read. An error *body* is a final answer for this attempt."""
    attempts = []

    class FakeResponse:
        def read(self):
            return json.dumps(QUOTA_ERROR).encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=30):
        attempts.append(req.full_url)
        return FakeResponse()
    monkeypatch.setattr(portwatch.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(SystemExit) as e:
        portwatch.main(["calls", "--since", "2026-09-01"])
    assert e.value.code != 0
    assert "quota exceeded" in capsys.readouterr().err
    assert len(attempts) == 1


def test_query_url_targets_the_daily_chokepoints_layer(monkeypatch):
    seen = {}

    class FakeResponse:
        def read(self):
            return json.dumps(ROWS).encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=30):
        seen["url"] = req.full_url
        return FakeResponse()
    monkeypatch.setattr(portwatch.urllib.request, "urlopen", fake_urlopen)
    portwatch.main(["calls", "--since", "2026-09-01"])
    assert seen["url"].startswith(
        "https://services9.arcgis.com/weJ1QsnbMYJlCHdG/arcgis/rest/services/"
        "Daily_Chokepoints_Data/FeatureServer/0/query?")


def test_usage_on_bad_args():
    with pytest.raises(SystemExit):
        portwatch.main([])
    with pytest.raises(SystemExit):
        portwatch.main(["nonsense"])


def test_iso_string_dates_parse_like_epoch_ms(api, capsys):
    """Item #19: the 9/28 live read crashed — the API now returns `date` as
    an ISO string, not epoch ms. Both forms must yield the same rows."""
    api["response"] = {
        "features": [
            {"attributes": {"date": "2026-09-15", "n_total": 4}},
            {"attributes": {"date": "2026-09-16", "n_total": 1}},
        ]
    }
    portwatch.main(["calls", "--since", "2026-09-01"])
    out = capsys.readouterr().out.splitlines()
    data = [line for line in out if not line.startswith("#")]
    assert data == ["2026-09-16  1", "2026-09-15  4"]


def test_iso_string_with_time_part_still_yields_the_day(api, capsys):
    """ArcGIS string date fields may carry a time part; only the day
    matters for daily transit calls."""
    api["response"] = {
        "features": [
            {"attributes": {"date": "2026-09-20 00:00:00", "n_total": 7}},
            {"attributes": {"date": "2026-09-19T00:00:00", "n_total": 6}},
        ]
    }
    portwatch.main(["calls", "--since", "2026-09-01"])
    out = capsys.readouterr().out.splitlines()
    data = [line for line in out if not line.startswith("#")]
    assert data == ["2026-09-20  7", "2026-09-19  6"]


# archive / first: Kalshi settles Hormuz on the FIRST print and PortWatch
# revises upward (HAZARD 1c; the revision ledger was hand re-reads, n=3).
# The quota allows ~2-3 queries a run and the 10/16 brief skipped a call
# "to save quota". One pipeline query a day journals every first print and
# every revision, so the judgment step can read both without spending quota.

@pytest.fixture
def archive_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(portwatch, "DATA", tmp_path)
    return tmp_path / "portwatch" / "hormuz.jsonl"


def journal_rows(path):
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def test_archive_journals_first_prints_oldest_first(api, archive_dir):
    assert portwatch.archive("Hormuz") == (2, 0)
    rows = journal_rows(archive_dir)
    assert [(r["date"], r["n_total"]) for r in rows] == [
        ("2026-09-15", 4), ("2026-09-16", 1)]
    assert all("seen_at" in r and "revised_from" not in r for r in rows)
    # one query per run, Hormuz, a dated window
    assert len(api["calls"]) == 1
    assert "Hormuz" in api["calls"][0]["where"]


def test_archive_rerun_adds_nothing_and_logs_revisions(api, archive_dir):
    portwatch.archive("Hormuz")
    api["response"] = {"features": [
        {"attributes": {"date": SEP15, "n_total": 4}},
        {"attributes": {"date": SEP16, "n_total": 3}},
        {"attributes": {"date": "2026-09-17", "n_total": 2}}]}
    assert portwatch.archive("Hormuz") == (1, 1)
    rows = journal_rows(archive_dir)
    rev = [r for r in rows if "revised_from" in r]
    assert [(r["date"], r["revised_from"], r["n_total"]) for r in rev] == [
        ("2026-09-16", 1, 3)]
    assert portwatch.archive("Hormuz") == (0, 0)


def test_first_prints_first_and_latest_per_day(api, archive_dir, capsys):
    portwatch.archive("Hormuz")
    api["response"] = {"features": [
        {"attributes": {"date": SEP15, "n_total": 4}},
        {"attributes": {"date": SEP16, "n_total": 3}}]}
    portwatch.archive("Hormuz")
    api["calls"].clear()
    portwatch.main(["first", "--since", "2026-09-01"])
    out = capsys.readouterr().out.splitlines()
    assert api["calls"] == []  # offline: no quota spent
    data = [l for l in out if not l.startswith("#")]
    assert data == ["2026-09-16  first 1  latest 3  (+2)",
                    "2026-09-15  first 4  latest 4"]
    assert any(l.startswith("# 1 of 2 days revised") for l in out)


def test_first_without_an_archive_says_so(archive_dir, capsys):
    portwatch.main(["first"])
    assert "no archive" in capsys.readouterr().out


def test_main_archive_reports_counts(api, archive_dir, capsys):
    portwatch.main(["archive"])
    assert "2 new days, 0 revised" in capsys.readouterr().out


def test_archive_quota_error_skips_without_failing_the_pipeline(
        monkeypatch, archive_dir, capsys):
    # a quota answer is final for the run (HAZARD 1b), not a broken source;
    # failing the step would page the human for the shared endpoint's load
    monkeypatch.setattr(portwatch.urllib.request, "urlopen",
                        lambda req, timeout=30: FakeResponse(QUOTA_ERROR))
    monkeypatch.setattr(portwatch.time, "sleep", lambda s: None)
    portwatch.main(["archive"])
    assert "skipped" in capsys.readouterr().out
    assert not archive_dir.exists()


class FakeResponse:
    def __init__(self, body):
        self.body = json.dumps(body).encode()

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_daily_archives_portwatch_before_the_judgment_step():
    daily = (pathlib.Path(__file__).parents[2] / "bin" / "daily.sh").read_text()
    step = daily.index("run_step portwatch")
    assert "kalshi/portwatch.py archive" in daily[step:daily.index("\n", step)]
    assert step < daily.index("run_step claude")
