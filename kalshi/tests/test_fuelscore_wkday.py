"""fuelscore.py: the log-only WKDAY model (day-of-week-scaled MOM).

The 10/31 brief found weekend damping in the gas print (Sunday moves
-0.65..-1.10c and Monday ~-0.3c against weekday runs of -1.4..-2.2c),
pre-registered a hand "weekday estimate" (4.1722 = -2.09c x 0.55) as a
log-only leg beside the binding MOM, wrote a falsifier ("two straight days
closer to MOM than to WKDAY and the idea is dropped"), and asked: "if WKDAY
beats MOM on 11/1 and 11/2, add a day-of-week term to fuelscore/fuelfreeze".
These tests pin a mechanical WKDAY the tool can score every day and over the
whole journal, WITHOUT entering the RW / MOM / DRIFT race: the '# n=' wins
the MINE->MOM rule was read off must not move.

  WKDAY  tomorrow = today + today's change x A(tomorrow's weekday) /
         A(today's weekday), A = mean |daily change| on that weekday over
         changes ending on or before today (no lookahead), each weekday
         needing WKDAY_MIN observations.
"""

import json
import pathlib
import sys
from datetime import date, timedelta
from decimal import Decimal

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parents[1]))
import fuelscore


def row(day, regular):
    return {"date": day, "prices": {"current": {
        "regular": regular, "mid_grade": "$4.8000", "premium": "$5.2000",
        "diesel": "$6.0000"}}}


def damped_series(start="2026-10-01", end="2026-10-25"):
    """-2c every day except Sundays (-1c), from $4.5000 on `start`."""
    out, price = [], Decimal("4.5000")
    d, last = date.fromisoformat(start), date.fromisoformat(end)
    while d <= last:
        out.append((d.isoformat(), price))
        d += timedelta(days=1)
        price -= Decimal("0.01") if d.weekday() == 6 else Decimal("0.02")
    return out


@pytest.fixture
def journal(tmp_path, monkeypatch):
    path = tmp_path / "prints.jsonl"

    def write(series):
        path.write_text("".join(json.dumps(row(d, f"${p}")) + "\n"
                                for d, p in series))
    write(damped_series())
    monkeypatch.setattr(fuelscore, "JOURNAL", path)
    return write


def lines(capsys):
    return capsys.readouterr().out.splitlines()


def by_day(out):
    return {l[:10]: l for l in out if l[:4].isdigit()}


def test_wkday_scales_todays_change_by_the_weekday_ratio(journal):
    prices = dict(fuelscore.series("regular"))
    # Sat 10/24 -> Sun 10/25: Saturday moves 2c, Sundays 1c -> half of -2c
    assert fuelscore.wkday(prices, "2026-10-24") == \
        prices["2026-10-24"] - Decimal("0.01")
    # Sun 10/25 -> Mon 10/26: today's -1c doubled
    assert fuelscore.wkday(prices, "2026-10-25") == \
        prices["2026-10-25"] - Decimal("0.02")


def test_wkday_needs_min_observations_of_both_weekdays(journal):
    prices = dict(fuelscore.series("regular"))
    # by Sat 10/17 only two Sundays (10/4, 10/11) have been seen
    assert fuelscore.WKDAY_MIN == 3
    assert fuelscore.wkday(prices, "2026-10-17") is None


def test_wkday_never_looks_ahead(journal):
    prices = dict(fuelscore.series("regular"))
    later = dict(prices)
    # a wild Sunday after the forecast day must not change the forecast
    later["2026-11-01"] = prices["2026-10-25"] + Decimal("0.50")
    assert fuelscore.wkday(later, "2026-10-24") == \
        fuelscore.wkday(prices, "2026-10-24")


def test_wkday_is_none_across_a_missing_day(journal):
    journal([r for r in damped_series() if r[0] != "2026-10-23"])
    prices = dict(fuelscore.series("regular"))
    assert fuelscore.wkday(prices, "2026-10-23") is None
    assert fuelscore.wkday(prices, "2026-10-24") is None


def test_rows_carry_a_wkday_column(journal, capsys):
    fuelscore.main(["regular"])
    rows = by_day(lines(capsys))
    assert rows["2026-10-25"].startswith("2026-10-25  4.0600")
    assert "WKDAY 4.0600 +0.00" in rows["2026-10-25"]
    assert "MOM 4.0500 +1.00" in rows["2026-10-25"]
    assert "WKDAY -" in rows["2026-10-18"]


def test_wkday_stays_out_of_the_race_summary(journal, capsys):
    fuelscore.main(["regular", "--days", "30"])
    out = lines(capsys)
    race = next(l for l in out if l.startswith("# n="))
    assert "WKDAY" not in race
    assert "RW MAE" in race and "MOM MAE" in race and "DRIFT MAE" in race
    nxt = next(l for l in out if l.startswith("# next"))
    assert "WKDAY" not in nxt


def test_log_only_summary_races_wkday_against_mom(journal, capsys):
    fuelscore.main(["regular"])
    out = lines(capsys)
    log = next(l for l in out if l.startswith("# log-only WKDAY"))
    # scored on Fri 10/23, Sat 10/24, Sun 10/25: exact each time; MOM
    # missed only the Sunday (by 1c)
    assert "n=3" in log
    assert "WKDAY MAE 0.000c vs MOM MAE 0.333c" in log
    assert "closer than MOM 1, MOM closer 0, tied 2" in log
    assert "next 2026-10-26 WKDAY 4.0400" in log


def test_log_only_summary_when_nothing_is_scorable_yet(journal, capsys):
    journal(damped_series(end="2026-10-12"))
    fuelscore.main(["regular"])
    out = lines(capsys)
    log = next(l for l in out if l.startswith("# log-only WKDAY"))
    assert "n=0" in log and f"{fuelscore.WKDAY_MIN}" in log
