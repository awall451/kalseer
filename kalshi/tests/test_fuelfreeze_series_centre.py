"""fuelfreeze.py score: the centre-miss summary per series, not just pooled.

Watchlist aaa-gas-tracking-nov (11/13): "Diesel daily centre miss board vs
MOM over 13 gradable days 10/30-11/13 (fuelfreeze --days 14): board closer
8-5, MAE ~0.46c vs ~0.56c by hand from the tool's per-event lines". The
pooled `# centre miss` line mixes gas with diesel and k1 dailies with k7
weeklies (whose misses run ~10c), so rule 4's per-fuel question had to be
tallied by eye. Each series now gets its own line under the pooled one.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parents[1]))
from test_fuelfreeze_centre import ladder, rec, run


def diesel(event, day, books, centre):
    r = rec(event, day, ladder(event, books), centre)
    r["grade"] = "diesel"
    return r


def write_prints(tmp_path, monkeypatch, capsys, recs, gas, dsl):
    """run() with both grades in the AAA journal."""
    import json
    import fuelscore
    import fuelfreeze
    journal = tmp_path / "fuel-freeze.jsonl"
    journal.write_text("".join(json.dumps(r) + "\n" for r in recs))
    monkeypatch.setattr(fuelfreeze, "JOURNAL", journal)
    aaa = tmp_path / "prints.jsonl"
    days = sorted(set(gas) | set(dsl))
    aaa.write_text("".join(
        json.dumps({"date": d, "prices": {"current": {
            "regular": f"${gas[d]}", "diesel": f"${dsl[d]}"}}}) + "\n"
        for d in days))
    monkeypatch.setattr(fuelscore, "JOURNAL", aaa)
    monkeypatch.setattr(fuelfreeze.kalshi, "get_event",
                        lambda t: {"markets": []})
    fuelfreeze.score()
    return capsys.readouterr().out


def test_score_splits_the_centre_miss_summary_by_series(tmp_path,
                                                        monkeypatch, capsys):
    g = "KXAAAGASD-26NOV08"
    d1, d2 = "KXDIESELD-26NOV08", "KXDIESELD-26NOV09"
    gas = rec(g, "2026-11-08", ladder(g, [(4.02, "0.5900", "0.6100"),
                                          (4.03, "0.3900", "0.4100")]),
              {"MOM": "4.0054"})
    # board centre 6.20 + 0.01 * 0.1 / 0.2 = 6.205 on both diesel days
    books = [(6.20, "0.5900", "0.6100"), (6.21, "0.3900", "0.4100")]
    a = diesel(d1, "2026-11-08", books, {"MOM": "6.2000"})
    b = diesel(d2, "2026-11-09", books, {"MOM": "6.2100"})
    out = write_prints(tmp_path, monkeypatch, capsys, [gas, a, b],
                       {"2026-11-08": "4.0203", "2026-11-09": "4.0100"},
                       {"2026-11-08": "6.2060", "2026-11-09": "6.2090"})
    lines = out.splitlines()
    # gas: board 4.025 misses 0.47c, MOM 1.49c. Diesel 11/8: board 0.10c,
    # MOM 0.60c; 11/9: board 0.40c, MOM 0.10c -> MOM 0.35c vs 0.25c, 1-1
    assert lines[-3] == ("# centre miss, same events (mean |print - centre|, "
                         "closer wins): MOM 0.73c vs BOARD 0.32c 1-2 (m3)")
    assert lines[-2] == ("# centre miss KXAAAGASD: "
                         "MOM 1.49c vs BOARD 0.47c 0-1 (m1)")
    assert lines[-1] == ("# centre miss KXDIESELD: "
                         "MOM 0.35c vs BOARD 0.25c 1-1 (m2)")


def test_a_single_series_window_prints_its_line_too(tmp_path, monkeypatch,
                                                    capsys):
    g = "KXAAAGASD-26NOV08"
    gas = rec(g, "2026-11-08", ladder(g, [(4.02, "0.5900", "0.6100"),
                                          (4.03, "0.3900", "0.4100")]),
              {"MOM": "4.0054"})
    out = run(tmp_path, monkeypatch, capsys, [gas], {"2026-11-08": "4.0203"})
    assert out.splitlines()[-1] == ("# centre miss KXAAAGASD: "
                                    "MOM 1.49c vs BOARD 0.47c 0-1 (m1)")


def test_daily_prompt_names_the_per_series_line():
    prompt = (pathlib.Path(__file__).parents[2] / "bin" /
              "daily-prompt.md").read_text()
    assert "# centre miss KXDIESELD:" in prompt
