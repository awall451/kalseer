"""fuelscore.py CLI: mechanical RW / MOM / DRIFT scoring off the AAA journal.

Every judgment run re-derives the daily gas/diesel model race by hand: RW
(tomorrow = today), MOM (today + today's change), DRIFT (today + mean of the
last-N changes) and the drift bar (2 standard errors of that mean). The
running MAEs (10/15 brief: "Over n=41, RW MAE is 0.820 and MOM 0.863") and
the drift-bar gate ("mean -0.65, bar 0.52") are hand arithmetic over a
growing series, and the 10/3-10/9 and 10/12 days were logged "unscorable"
because no pre-reg was frozen, though the models are mechanical and the
journal has every print. These tests pin the model definitions and the
gap handling: a forecast is never scored across a missing day.
"""

import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parents[1]))
import fuelscore


def row(date, regular, diesel="$6.0000"):
    return {"date": date, "prices": {"current": {
        "regular": regular, "mid_grade": "$4.8000", "premium": "$5.2000",
        "diesel": diesel}}}


# 10/09..10/15 regular, cents changes: -0.44 +0.32 -0.18 -0.55 +1.06 +0.11
SERIES = [("2026-10-09", "$4.3500"), ("2026-10-10", "$4.3456"),
          ("2026-10-11", "$4.3488"), ("2026-10-12", "$4.3470"),
          ("2026-10-13", "$4.3415"), ("2026-10-14", "$4.3521"),
          ("2026-10-15", "$4.3532")]


@pytest.fixture
def journal(tmp_path, monkeypatch):
    path = tmp_path / "prints.jsonl"

    def write(rows):
        path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    write([row(d, p) for d, p in SERIES])
    monkeypatch.setattr(fuelscore, "JOURNAL", path)
    return write


def day_lines(capsys):
    return [l for l in capsys.readouterr().out.splitlines()
            if l[:4].isdigit()]


def test_series_reads_exact_strings_by_grade(journal):
    s = fuelscore.series("regular")
    assert s[0] == ("2026-10-09", fuelscore.Decimal("4.3500"))
    assert len(s) == 7
    assert fuelscore.series("diesel")[0][1] == fuelscore.Decimal("6.0000")


def test_rw_and_mom_forecasts_and_errors_in_cents(journal, capsys):
    fuelscore.main(["regular", "--window", "3"])
    newest = day_lines(capsys)[0]
    # 10/15 actual 4.3532; RW 4.3521 (err +0.11); MOM 4.3521+0.0106 = 4.3627
    assert newest.startswith("2026-10-15  4.3532")
    assert "RW 4.3521 +0.11" in newest
    assert "MOM 4.3627 -0.95" in newest


def test_drift_is_last_plus_mean_of_last_n_changes(journal, capsys):
    fuelscore.main(["regular", "--window", "3"])
    newest = day_lines(capsys)[0]
    # changes into 10/14: -0.18 -0.55 +1.06 -> mean +0.11c -> 4.3532
    assert "DRIFT 4.3532 +0.00" in newest


def test_drift_unscored_until_window_has_enough_history(journal, capsys):
    fuelscore.main(["regular", "--window", "5"])
    lines = day_lines(capsys)
    by_day = {l[:10]: l for l in lines}
    # 10/15 has 5 changes behind it (10/10..10/14), 10/14 has only 4
    assert "DRIFT" in by_day["2026-10-15"]
    assert "DRIFT -" in by_day["2026-10-14"]


def test_forecast_is_never_scored_across_a_missing_day(journal, capsys):
    journal([row(d, p) for d, p in SERIES if d != "2026-10-12"])
    fuelscore.main(["regular", "--window", "2"])
    by_day = {l[:10]: l for l in day_lines(capsys)}
    # 10/13 has no 10/12 behind it: nothing scorable
    assert "RW -" in by_day["2026-10-13"]
    # 10/14 has RW (10/13 present) but no MOM (10/12 change missing)
    assert "RW 4.3415" in by_day["2026-10-14"]
    assert "MOM -" in by_day["2026-10-14"]


def test_summary_mae_and_wins_over_days_all_models_scored(journal, capsys):
    fuelscore.main(["regular", "--window", "3"])
    out = capsys.readouterr().out
    # scored days 10/13, 10/14, 10/15 (window 3 needs 4 prior prints).
    # 10/13: RW +0.55 err .55, MOM 4.3470-0.0018=4.3452 err .37,
    #        DRIFT 4.3470+(-0.44+0.32-0.18)/3c=4.3460 err .45  -> MOM
    # 10/14: RW 1.06, MOM 4.3415-0.0055=4.3360 err 1.61,
    #        DRIFT 4.3415+(0.32-0.18-0.55)/3c=4.34013 err 1.197 -> RW
    # 10/15: RW .11, MOM .95, DRIFT .00 -> DRIFT
    summary = [l for l in out.splitlines() if l.startswith("# n=")][0]
    assert summary.startswith("# n=3")
    assert "RW MAE 0.573c wins 1" in summary
    assert "MOM MAE 0.977c wins 1" in summary
    assert "DRIFT MAE 0.549c wins 1" in summary


def test_next_day_forecasts_and_drift_bar(journal, capsys):
    fuelscore.main(["regular", "--window", "5"])
    out = capsys.readouterr().out
    nxt = [l for l in out.splitlines() if l.startswith("# next")][0]
    # last-5 changes: +0.32 -0.18 -0.55 +1.06 +0.11 -> mean +0.152,
    # sample sd 0.6036, bar 2*sd/sqrt(5) = 0.540 -> does not clear
    assert nxt.startswith("# next 2026-10-16:")
    assert "RW 4.3532" in nxt and "MOM 4.3543" in nxt
    assert "DRIFT 4.3547" in nxt
    assert "last-5 mean +0.15c sd 0.60c bar 0.54c -> no drift" in nxt


def test_drift_bar_clears_when_mean_beats_it(journal, capsys):
    falling = [("2026-10-1%d" % i, "$4.%04d" % (3600 - 60 * i))
               for i in range(6)]
    journal([row(d, p) for d, p in falling])
    fuelscore.main(["regular"])
    nxt = [l for l in capsys.readouterr().out.splitlines()
           if l.startswith("# next")][0]
    assert "mean -0.60c sd 0.00c bar 0.00c -> drift clears" in nxt


def test_duplicate_date_keeps_the_last_row(journal):
    journal([row(d, p) for d, p in SERIES] + [row("2026-10-15", "$4.4000")])
    assert fuelscore.series("regular")[-1][1] == fuelscore.Decimal("4.4000")


def test_rows_without_the_grade_are_skipped(journal):
    rows = [row(d, p) for d, p in SERIES]
    rows[2]["prices"] = {}
    journal(rows)
    assert "2026-10-11" not in [d for d, _ in fuelscore.series("regular")]


def test_days_option_limits_rows(journal, capsys):
    fuelscore.main(["regular", "--days", "2"])
    assert len(day_lines(capsys)) == 2


def test_judgment_allowlist_grants_the_cli():
    # Invoked by relative path like every repo CLI; without its own Bash
    # grant the judgment run stops for approval and falls back to hand math.
    settings = pathlib.Path(__file__).parents[2] / ".claude" / "settings.json"
    allow = json.loads(settings.read_text())["permissions"]["allow"]
    assert "Bash(python3 kalshi/fuelscore.py *)" in allow


def test_usage_on_unknown_grade(journal):
    with pytest.raises(SystemExit) as e:
        fuelscore.main(["kerosene"])
    assert "regular" in str(e.value.code)


# --settled: the journal starts 9/24, but KXAAAGASD / KXDIESELD settle on
# the exact AAA print dated by the event ticker, back to August. The 10/16
# brief scores the race over n=42 by hand; the journal alone gives n=17.

def settled(event, value, strike="4.330"):
    return {"ticker": f"{event}-T{strike}", "event_ticker": event,
            "expiration_value": value, "close_time": "x"}


@pytest.fixture
def finals(monkeypatch):
    calls = []

    def fake(series_ticker, max_pages=5):
        calls.append(series_ticker)
        return [settled("KXAAAGASD-26OCT12", "4.347"),
                settled("KXAAAGASD-26OCT12", "4.347", "4.340"),
                settled("KXAAAGASD-26OCT08", "4.3510"),
                settled("KXAAAGASD-26OCT15", "4.3999"),
                {"ticker": "KXAAAGASD-26OCT16-T4.33",
                 "event_ticker": "KXAAAGASD-26OCT16", "expiration_value": ""}]
    monkeypatch.setattr(fuelscore.kalshi, "settled_markets", fake)
    return calls


def test_settled_prints_dates_events_and_pads_exact_strings(finals):
    got = fuelscore.settled_prints("regular")
    assert finals == ["KXAAAGASD"]
    # unsettled 10/16 skipped; '4.347' is the API dropping a trailing zero
    assert got == {"2026-10-08": fuelscore.Decimal("4.3510"),
                   "2026-10-12": fuelscore.Decimal("4.3470"),
                   "2026-10-15": fuelscore.Decimal("4.3999")}
    assert str(got["2026-10-12"]) == "4.3470"


def test_settled_diesel_reads_kxdieseld(monkeypatch):
    seen = []
    monkeypatch.setattr(fuelscore.kalshi, "settled_markets",
                        lambda s, max_pages=5: seen.append(s) or [])
    assert fuelscore.settled_prints("diesel") == {}
    assert seen == ["KXDIESELD"]


def test_settled_fills_gaps_and_the_journal_wins(journal, finals, capsys):
    journal([row(d, p) for d, p in SERIES if d != "2026-10-12"])
    fuelscore.main(["regular", "--window", "2", "--settled"])
    out = capsys.readouterr().out
    by_day = {l[:10]: l for l in out.splitlines() if l[:4].isdigit()}
    # 10/12 recovered from KXAAAGASD, so 10/13 is scorable again
    assert by_day["2026-10-12"].startswith("2026-10-12  4.3470")
    assert "RW 4.3470 -0.55" in by_day["2026-10-13"]
    # 10/08 extends the series back; 10/15 keeps the journal's print
    assert "2026-10-09" in by_day
    assert by_day["2026-10-15"].startswith("2026-10-15  4.3532")
    note = [l for l in out.splitlines() if l.startswith("# settled")][0]
    assert "+2 days from KXAAAGASD" in note
    assert "2026-10-15 journal 4.3532 vs settled 4.3999" in note


def test_without_settled_flag_no_network(journal, monkeypatch, capsys):
    def boom(*a, **k):
        raise AssertionError("network")
    monkeypatch.setattr(fuelscore.kalshi, "settled_markets", boom)
    fuelscore.main(["regular"])
    assert "# settled" not in capsys.readouterr().out


def test_settled_refuses_grades_without_a_series(journal):
    with pytest.raises(SystemExit) as e:
        fuelscore.main(["premium", "--settled"])
    assert "regular" in str(e.value.code) and "diesel" in str(e.value.code)
