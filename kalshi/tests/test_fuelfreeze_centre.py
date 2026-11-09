"""fuelfreeze.py: the board's implied centre, next to each model's centre.

Brief 11/8: "Yesterday's gas board was centred ~4.0195 and missed by only
+0.08c, the best of every forecaster", and "The gas daily and weekly boards
are both centred ~4.012". Standing rule 4 (defer to a tight board inside 48
hours) is judged on that centre every day, read by hand off the ladder. The
freeze already holds every strike's book and each model's centre, so the
centre is where the board's mids cross 0.5, and score grades it like a model.
"""

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parents[1]))
import fuelfreeze
import fuelscore
from test_fuelfreeze_summary import strike

E = "KXAAAGASD-26NOV08"


def rec(event, day, strikes, centre=None):
    return {"event": event, "series": event.split("-")[0], "grade": "regular",
            "date": day, "k": 1, "strikes": strikes, "centre": centre or {}}


def ladder(event, books):
    return [strike(event, f, b, a, 0.5) for f, b, a in books]


def test_centre_interpolates_where_the_mids_cross_half():
    r = rec(E, "2026-11-08", ladder(E, [(4.01, "0.9800", "0.9900"),
                                        (4.015, "0.6600", "0.6700"),
                                        (4.02, "0.0600", "0.0700")]))
    side, value = fuelfreeze.centre(r)
    # 0.665 at 4.015, 0.065 at 4.02: 4.015 + 0.005 * 0.165 / 0.6
    assert side == "" and abs(value - 4.016375) < 1e-9


def test_centre_skips_unpriced_books():
    r = rec(E, "2026-11-08", ladder(E, [(4.01, "0.7000", "0.7100"),
                                        (4.015, "0.0000", "0.0000"),
                                        (4.02, "0.0100", "0.9900"),
                                        (4.025, "0.2900", "0.3100")]))
    side, value = fuelfreeze.centre(r)
    # only 4.01 (0.705) and 4.025 (0.30) are priced
    assert side == ""
    assert abs(value - (4.01 + 0.015 * 0.205 / 0.405)) < 1e-9


def test_centre_off_the_ladder_or_unpriced():
    below = rec(E, "d", ladder(E, [(4.01, "0.3000", "0.3100")]))
    above = rec(E, "d", ladder(E, [(4.01, "0.9000", "0.9100"),
                                   (4.02, "0.8000", "0.8100")]))
    none = rec(E, "d", ladder(E, [(4.01, "0.0000", "0.0000")]))
    assert fuelfreeze.centre(below) == ("<", 4.01)
    assert fuelfreeze.centre(above) == (">", 4.02)
    assert fuelfreeze.centre(none) == ("-", None)


def run(tmp_path, monkeypatch, capsys, recs, prints):
    journal = tmp_path / "fuel-freeze.jsonl"
    journal.write_text("".join(json.dumps(r) + "\n" for r in recs))
    monkeypatch.setattr(fuelfreeze, "JOURNAL", journal)
    aaa = tmp_path / "prints.jsonl"
    aaa.write_text("".join(
        json.dumps({"date": d, "prices": {"current": {"regular": f"${p}"}}})
        + "\n" for d, p in prints.items()))
    monkeypatch.setattr(fuelscore, "JOURNAL", aaa)
    monkeypatch.setattr(fuelfreeze.kalshi, "get_event",
                        lambda t: {"markets": []})
    fuelfreeze.score()
    return capsys.readouterr().out


def test_score_names_each_centre_and_its_miss(tmp_path, monkeypatch, capsys):
    # the 11/8 gas daily: print 4.0203
    r = rec(E, "2026-11-08",
            ladder(E, [(4.015, "0.7400", "0.7600"),
                       (4.02, "0.5400", "0.5600"),
                       (4.025, "0.1400", "0.1600")]),
            {"RW": "4.0371", "MOM": "4.0054", "DRIFT": "4.0106",
             "WKDAY": "4.0170"})
    out = run(tmp_path, monkeypatch, capsys, [r], {"2026-11-08": "4.0203"})
    line = [l for l in out.splitlines() if l.startswith("2026-11-08")][0]
    # board crosses 0.5 at 4.02 + 0.005 * 0.05 / 0.4 = 4.020625
    assert ("centre miss (c): BOARD 4.0206 -0.03  RW 4.0371 -1.68  "
            "MOM 4.0054 +1.49  DRIFT 4.0106 +0.97  WKDAY 4.0170 +0.33  "
            "-> closest BOARD") in line
    assert line.endswith("(AAA journal, Kalshi unsettled)")


def test_score_summarises_centre_misses_on_the_same_events(tmp_path,
                                                           monkeypatch,
                                                           capsys):
    e2 = "KXAAAGASD-26NOV09"
    a = rec(E, "2026-11-08",
            ladder(E, [(4.02, "0.5900", "0.6100"),
                       (4.03, "0.3900", "0.4100")]),
            {"RW": "4.0371", "MOM": "4.0054", "DRIFT": None})
    # no board centre on the ladder: its models sit out of the paired line
    b = rec(e2, "2026-11-09", ladder(e2, [(4.02, "0.0000", "0.0000")]),
            {"RW": "4.0203", "MOM": "4.0035", "DRIFT": "3.9945"})
    out = run(tmp_path, monkeypatch, capsys, [a, b],
              {"2026-11-08": "4.0203", "2026-11-09": "4.0100"})
    lines = out.splitlines()
    nov9 = [l for l in lines if l.startswith("2026-11-09")][0]
    assert ("centre miss (c): BOARD -  RW 4.0203 -1.03  MOM 4.0035 +0.65  "
            "DRIFT 3.9945 +1.55  -> closest MOM") in nov9
    summary = [l for l in lines if l.startswith("# centre miss")][0]
    # board centre 4.025 on 11/8, miss 0.47c; DRIFT never paired
    assert summary == ("# centre miss, same events (mean |print - centre|, "
                       "closer wins): RW 1.68c vs BOARD 0.47c 0-1 (m1)  "
                       "MOM 1.49c vs BOARD 0.47c 0-1 (m1)")


def test_freeze_prints_each_events_board_centre(monkeypatch, capsys):
    r = rec(E, "2026-11-08",
            ladder(E, [(4.01, "0.6500", "0.6700"),
                       (4.015, "0.0600", "0.0800")]),
            {"RW": "4.0203", "MOM": "4.0035", "DRIFT": None,
             "WKDAY": "4.0145"})
    monkeypatch.setattr(fuelfreeze, "freeze", lambda: ([E], []))
    monkeypatch.setattr(fuelfreeze, "frozen_lines", lambda: [json.dumps(r)])
    fuelfreeze.main(["freeze"])
    out = capsys.readouterr().out.splitlines()
    # 4.01 + 0.005 * 0.16 / 0.59
    assert (f"  {E} centre: BOARD 4.0114  RW 4.0203  MOM 4.0035  "
            "WKDAY 4.0145") in out
