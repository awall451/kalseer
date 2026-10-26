"""brief.py check: the judgment step's brief is valid before anything reads it.

The 10-25 judgment run ended with "I couldn't run the JSON check on the brief
because the command needed approval, but I wrote it carefully". Nothing
downstream checks either: daily.sh only tests that the file exists, and
publish.py json.loads every brief-*.json on every run, so one malformed
brief would crash publish on that run and every run after it until a human
fixed the file. These tests pin a granted checker, the pipeline gate that
calls it, and a publish step that skips (and names) an unreadable brief.
"""

import datetime as dt
import json
import pathlib
import subprocess
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parents[1]))
import brief
import publish

REPO = pathlib.Path(__file__).parents[2]


def good(date="2026-10-25", **kw):
    return dict({"date": date, "narrative": "No trades today.",
                 "narrative_spoken": "No trades today.",
                 "trades_opened": [], "trades_settled": [],
                 "considered_but_passed": [{"ticker": "KXRT-X", "why": "rate"}],
                 "bankroll": 1000.0, "at_risk": 43.05,
                 "sources_checked": ["kalshi.py"]}, **kw)


def write(tmp_path, body, date="2026-10-25"):
    p = tmp_path / f"brief-{date}.json"
    p.write_text(body if isinstance(body, str) else json.dumps(body))
    return p


def test_good_brief_has_no_problems(tmp_path):
    assert brief.problems(write(tmp_path, good())) == []


def test_narrative_spoken_is_optional(tmp_path):
    b = good()
    del b["narrative_spoken"]
    assert brief.problems(write(tmp_path, b)) == []


def test_malformed_json_names_the_line(tmp_path):
    p = write(tmp_path, '{"date": "2026-10-25", "narrative": "a "quoted" word"}')
    (msg,) = brief.problems(p)
    assert "not valid JSON" in msg and "line 1" in msg


def test_missing_keys_are_listed(tmp_path):
    b = good()
    del b["trades_settled"], b["bankroll"]
    msgs = brief.problems(write(tmp_path, b))
    assert any("trades_settled" in m for m in msgs)
    assert any("bankroll" in m for m in msgs)


def test_date_must_match_filename(tmp_path):
    msgs = brief.problems(write(tmp_path, good(date="2026-10-24")))
    assert any("2026-10-24" in m and "2026-10-25" in m for m in msgs)


def test_empty_narrative_is_a_problem(tmp_path):
    msgs = brief.problems(write(tmp_path, good(narrative="  ")))
    assert any("narrative" in m for m in msgs)


def test_trade_lists_need_ticker_objects(tmp_path):
    msgs = brief.problems(write(tmp_path, good(
        trades_opened={"ticker": "KX"},
        considered_but_passed=[{"ticker": "KX-A"}, "KX-B", {"why": "x"}])))
    assert any("trades_opened" in m and "list" in m for m in msgs)
    assert any("considered_but_passed[1]" in m for m in msgs)
    assert any("considered_but_passed[2]" in m for m in msgs)


def test_money_fields_are_numbers(tmp_path):
    msgs = brief.problems(write(tmp_path, good(bankroll="1000", at_risk=True)))
    assert any("bankroll" in m for m in msgs)
    assert any("at_risk" in m for m in msgs)


def test_cli_defaults_to_today_and_exits_zero_when_ok(tmp_path, monkeypatch,
                                                      capsys):
    monkeypatch.setattr(brief, "DATA", tmp_path)
    monkeypatch.setattr(brief, "_today", lambda: "2026-10-25")
    write(tmp_path, good())
    assert brief.main(["check"]) == 0
    out = capsys.readouterr().out
    assert "brief OK" in out and "brief-2026-10-25.json" in out


def test_cli_exits_nonzero_and_prints_each_problem(tmp_path, capsys):
    b = good()
    del b["narrative"]
    p = write(tmp_path, b)
    assert brief.main(["check", str(p)]) == 2
    assert "narrative" in capsys.readouterr().err


def test_cli_missing_file_is_a_problem(tmp_path, capsys):
    assert brief.main(["check", str(tmp_path / "brief-2026-10-25.json")]) == 2
    assert "cannot read" in capsys.readouterr().err


def test_publish_skips_an_unreadable_brief_and_names_it(tmp_path, capsys):
    ok = write(tmp_path, good(date="2026-10-24"), date="2026-10-24")
    bad = write(tmp_path, "{not json", date="2026-10-25")
    loaded = publish.load_briefs([ok, bad])
    assert [p for p, _ in loaded] == [ok]
    assert "brief-2026-10-25.json" in capsys.readouterr().out


def test_every_archived_brief_shape_passes(tmp_path):
    # the pre-gate schema, as written by 80 judgment runs (8/7 .. 10/25)
    b = good()
    b["trades_settled"] = [{"ticker": "KXDIESELW-26OCT19-T6.28", "side": "no",
                            "result": "no", "won": True, "pnl": 30.6,
                            "title": "t", "reasoning": "r"}]
    assert brief.problems(write(tmp_path, b)) == []


def test_daily_gates_the_brief_after_the_claude_step():
    text = (REPO / "bin" / "daily.sh").read_text()
    gate = text.index("kalshi/brief.py check")
    assert text.index("run_step claude") < gate < text.index("run_step publish")


def run_gate(tmp_path, body, failed_step=""):
    # the real gate block from daily.sh, from BRIEF= to its closing fi
    text = (REPO / "bin" / "daily.sh").read_text()
    start = text.index('BRIEF="$DATA_DIR/brief-')
    block = text[start:text.index("\nfi\n", start) + 4]
    if body is not None:
        write(tmp_path, body if isinstance(body, str)
              else good(date=dt.date.today().isoformat()),
              date=dt.date.today().isoformat())
    script = (f'DATA_DIR="{tmp_path}"\nFAILED_STEP="{failed_step}"\n' + block
              + 'echo "STEP=$FAILED_STEP"\n')
    r = subprocess.run(["bash", "-c", script], cwd=REPO, capture_output=True,
                       text=True)
    return r.stdout + r.stderr


def test_gate_passes_a_good_brief(tmp_path):
    out = run_gate(tmp_path, good())
    assert "brief OK" in out and "STEP=\n" in out


def test_gate_fails_the_run_on_a_malformed_brief(tmp_path):
    out = run_gate(tmp_path, "{not json")
    assert "is not a valid brief" in out and "STEP=claude" in out


def test_gate_still_fails_a_missing_brief(tmp_path):
    out = run_gate(tmp_path, None)
    assert "no " in out and "STEP=claude" in out


def test_gate_leaves_an_earlier_failure_alone(tmp_path):
    out = run_gate(tmp_path, "{not json", failed_step="scan")
    assert "STEP=scan" in out and "valid brief" not in out


def test_judgment_is_granted_the_checker():
    allow = json.loads((REPO / ".claude" / "settings.json").read_text())[
        "permissions"]["allow"]
    assert "Bash(python3 kalshi/brief.py *)" in allow


def test_prompt_tells_judgment_to_run_the_checker():
    assert "python3 kalshi/brief.py check" in (
        REPO / "bin" / "daily-prompt.md").read_text()
