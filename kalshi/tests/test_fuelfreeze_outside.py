"""fuelfreeze.py score: a record of boards centred outside every model.

Brief 11/17: "Yesterday's diesel test was the first logged case of the board
sitting above *every* model, and it went to the models (print <= 5.985)."
The watchlist now keeps that as a hand ledger ("first logged
board-above-all-models diesel divergence goes to the models"), and whether
such a board is informed or overshooting is the question rule 4 keeps
deferring. Each scored event whose on-ladder board centre is above or below
every movement model (MOM, DRIFT, WKDAY; RW is today's print, so a falling
board always sits below it) is tagged, and one line per series scores the
board against the nearest model on those events.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parents[1]))
from test_fuelfreeze_centre import ladder, rec, run

# board centre 4.02 + 0.01 * 0.1 / 0.2 = 4.025 on every event
BOOKS = [(4.02, "0.5900", "0.6100"), (4.03, "0.3900", "0.4100")]


def event(day, centre):
    e = f"KXAAAGASD-26NOV{day[-2:]}"
    return rec(e, day, ladder(e, BOOKS), centre)


def test_outside_events_get_a_series_line(tmp_path, monkeypatch, capsys):
    recs = [
        # above both (RW doesn't count); print 4.0203: board 0.47c, DRIFT 0.53c
        event("2026-11-08", {"RW": "4.0400", "MOM": "4.0100",
                             "DRIFT": "4.0150"}),
        # above both; print 4.0120: board 1.30c, MOM 0.20c
        event("2026-11-09", {"MOM": "4.0100", "DRIFT": "4.0150"}),
        # between the models: not outside
        event("2026-11-10", {"MOM": "4.0300", "DRIFT": "4.0200"}),
        # below both; print 4.0290: board 0.40c, DRIFT 0.60c
        event("2026-11-11", {"MOM": "4.0400", "DRIFT": "4.0350"}),
        # one model only: nothing to be outside of
        event("2026-11-12", {"MOM": "4.0100"}),
    ]
    out = run(tmp_path, monkeypatch, capsys, recs, {
        "2026-11-08": "4.0203", "2026-11-09": "4.0120",
        "2026-11-10": "4.0250", "2026-11-11": "4.0290",
        "2026-11-12": "4.0200"})
    lines = out.splitlines()
    assert ("# board outside models KXAAAGASD: nearest model 0.44c vs "
            "BOARD 0.72c 1-2 (m3; above 1-1, below 0-1)") in lines
    tagged = {l.split("  ")[1]: l for l in lines if l.startswith("2026-")}
    assert "-> closest BOARD  board above models" in tagged["KXAAAGASD-26NOV08"]
    assert "  board below models" in tagged["KXAAAGASD-26NOV11"]
    assert "models" not in tagged["KXAAAGASD-26NOV10"]
    assert "models" not in tagged["KXAAAGASD-26NOV12"]


def test_no_outside_events_no_line(tmp_path, monkeypatch, capsys):
    recs = [event("2026-11-10", {"MOM": "4.0300", "DRIFT": "4.0200"})]
    out = run(tmp_path, monkeypatch, capsys, recs, {"2026-11-10": "4.0250"})
    assert "# board outside models" not in out


def test_daily_prompt_names_the_outside_line():
    prompt = (pathlib.Path(__file__).parents[2] / "bin" /
              "daily-prompt.md").read_text()
    assert "# board outside models" in prompt
