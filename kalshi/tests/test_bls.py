"""bls.py CLI: timeseries reads off api.bls.gov for the CPI/payrolls complex.

Item #4: clevelandfed.org and bls.gov 403 WebFetch server-side (proven
8/8-8/9), keeping the CPI/payrolls complex unpriceable. The api.bls.gov curl
route was live-verified 9/30 (CUUR0000SA0 -> Aug 334.980, REQUEST_SUCCEEDED)
— this CLI wraps that exact GET interface so the judgment run gets repeatable
structured reads (MoM/YoY deltas, preliminary flags) instead of hand-rolled
curl + jq every release day. These tests pin the documented v2 response
schema (status, Results.series[].data[{year, period, periodName, latest,
value, footnotes}]); schema drift must fail loudly, never print garbage
deltas a settlement read would trust.
"""

import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parents[1]))
import bls


def body(series_id, rows, status="REQUEST_SUCCEEDED"):
    return {"status": status, "responseTime": 150, "message": [],
            "Results": {"series": [{"seriesID": series_id, "data": rows}]}}


def row(year, period, value, name="Month", latest=None, footnotes=None):
    out = {"year": year, "period": period, "periodName": name,
           "value": value, "footnotes": footnotes or [{}]}
    if latest:
        out["latest"] = "true"
    return out


# 14 months of CPI-shaped data, oldest deliberately first: order must come
# from the tool. 2026-08 is 'latest' and preliminary.
CPI_ROWS = [
    row("2025", "M07", "320.580", "July"),
    row("2025", "M08", "325.635", "August"),
    row("2025", "M09", "326.588", "September"),
    row("2025", "M10", "327.425", "October"),
    row("2025", "M11", "327.966", "November"),
    row("2025", "M12", "328.656", "December"),
    row("2026", "M01", "329.831", "January"),
    row("2026", "M02", "330.452", "February"),
    row("2026", "M03", "331.210", "March"),
    row("2026", "M04", "332.015", "April"),
    row("2026", "M05", "332.806", "May"),
    row("2026", "M06", "333.598", "June"),
    row("2026", "M07", "334.602", "July"),
    row("2026", "M08", "334.980", "August", latest=True,
        footnotes=[{"code": "P", "text": "preliminary"}]),
]


@pytest.fixture
def api(monkeypatch):
    """Capture requested series ids; serve canned BLS v2 responses."""
    state = {"calls": [], "response": body("CUUR0000SA0", list(CPI_ROWS))}

    def fake_fetch(series_id):
        state["calls"].append(series_id)
        return state["response"]
    monkeypatch.setattr(bls, "_fetch", fake_fetch)
    return state


def data_lines(capsys):
    return [line for line in capsys.readouterr().out.splitlines()
            if not line.startswith("#")]


def test_series_prints_newest_first(api, capsys):
    bls.main(["series", "CUUR0000SA0"])
    lines = data_lines(capsys)
    assert lines[0].startswith("2026-08  334.980")
    assert lines[1].startswith("2026-07  334.602")
    assert lines[-1].startswith("2025-07  320.580")


def test_mom_and_yoy_deltas_on_each_line(api, capsys):
    bls.main(["series", "CUUR0000SA0"])
    newest = data_lines(capsys)[0]
    # 334.980 - 334.602 and 334.980 - 325.635
    assert "mom +0.378 (+0.11%)" in newest
    assert "yoy +9.345 (+2.87%)" in newest


def test_deltas_omitted_when_no_base_month(api, capsys):
    bls.main(["series", "CUUR0000SA0"])
    oldest = data_lines(capsys)[-1]
    assert "mom" not in oldest and "yoy" not in oldest


def test_latest_and_preliminary_rows_are_marked(api, capsys):
    # Kalshi settles on the first print and BLS revises: the P flag is
    # exactly what separates a settled read from a moving one.
    bls.main(["series", "CUUR0000SA0"])
    lines = data_lines(capsys)
    assert "[P]" in lines[0] and "latest" in lines[0]
    assert "[P]" not in lines[1] and "latest" not in lines[1]


def test_alias_maps_to_the_settlement_series(api, capsys):
    bls.main(["series", "cpi"])
    assert api["calls"] == ["CUUR0000SA0"]


def test_every_alias_resolves_to_its_documented_series_id(api, capsys):
    for alias, series_id in [("cpi", "CUUR0000SA0"), ("cpi-sa", "CUSR0000SA0"),
                             ("payrolls", "CES0000000001"),
                             ("u3", "LNS14000000")]:
        api["calls"].clear()
        bls.main(["series", alias])
        assert api["calls"] == [series_id], alias


def test_raw_series_id_passes_through_untouched(api, capsys):
    bls.main(["series", "LNS14000000"])
    assert api["calls"] == ["LNS14000000"]


def test_payrolls_mom_delta_is_the_jobs_number(api, capsys):
    # KXPAYROLLS settles on the month-over-month change in thousands — the
    # mom column must be that number, straight off the level series.
    api["response"] = body("CES0000000001", [
        row("2026", "M07", "160121", "July"),
        row("2026", "M08", "160283", "August", latest=True),
    ])
    bls.main(["series", "payrolls"])
    assert "mom +162" in data_lines(capsys)[0]


def test_m13_annual_average_rows_are_skipped(api, capsys):
    rows = list(CPI_ROWS) + [row("2025", "M13", "326.000", "Annual")]
    api["response"] = body("CUUR0000SA0", rows)
    bls.main(["series", "CUUR0000SA0"])
    assert len(data_lines(capsys)) == len(CPI_ROWS)


def test_months_limits_printed_rows_but_not_delta_bases(api, capsys):
    bls.main(["series", "CUUR0000SA0", "--months", "2"])
    lines = data_lines(capsys)
    assert len(lines) == 2
    assert "yoy +9.345" in lines[0]  # base month beyond the display window


def test_footer_names_series_latest_period_and_value(api, capsys):
    bls.main(["series", "cpi"])
    summary = [l for l in capsys.readouterr().out.splitlines()
               if l.startswith("#")]
    assert any("cpi = CUUR0000SA0" in l and "latest 2026-08 (August)" in l
               and "334.980" in l for l in summary)


def test_empty_data_is_an_answer_not_an_error(api, capsys):
    api["response"] = body("CUUR0000SA0", [])
    bls.main(["series", "CUUR0000SA0"])  # exit 0
    assert "# no data" in capsys.readouterr().out


def test_failed_status_exits_loudly_with_the_message(api, capsys):
    api["response"] = {"status": "REQUEST_NOT_PROCESSED",
                       "message": ["Series does not exist: NOPE"],
                       "Results": {}}
    with pytest.raises(SystemExit) as e:
        bls.main(["series", "NOPE"])
    assert e.value.code != 0
    err = capsys.readouterr().err
    assert "REQUEST_NOT_PROCESSED" in err
    assert "Series does not exist" in err


def test_unexpected_body_shape_fails_loudly(api, capsys):
    api["response"] = {"error": "nope"}
    with pytest.raises(SystemExit) as e:
        bls.main(["series", "cpi"])
    assert e.value.code != 0
    assert "unexpected response shape" in capsys.readouterr().err


def test_fetch_targets_the_documented_endpoint(monkeypatch):
    seen = {}

    class FakeResponse:
        def read(self):
            return json.dumps(body("CUUR0000SA0", list(CPI_ROWS))).encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=30):
        seen["url"] = req.full_url
        return FakeResponse()
    monkeypatch.setattr(bls.urllib.request, "urlopen", fake_urlopen)
    bls.main(["series", "cpi"])
    assert seen["url"] == ("https://api.bls.gov/publicAPI/v2/timeseries/"
                           "data/CUUR0000SA0")


def test_usage_on_bad_args():
    with pytest.raises(SystemExit):
        bls.main([])
    with pytest.raises(SystemExit):
        bls.main(["nonsense"])
    with pytest.raises(SystemExit):
        bls.main(["series"])  # a series is required
    with pytest.raises(SystemExit):
        bls.main(["series", "cpi", "--months"])  # value required
