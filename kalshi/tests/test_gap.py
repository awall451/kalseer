"""kalshi/gap.py: tell a cold-starting judgment session it is resuming a gap.

2026-10-02..10-08: an outdated host CLI killed seven straight judgment runs
(settle, scan, and the AAA capture kept going). The watchlist froze
pre-registrations that scored inside the gap — Sept NFP 10/2, PMMS 10/2,
rain 10/2, Verity/Digger 10/5, Hormuz week 3 ~10/7, the gas triple 10/5 —
and the judgment step starts every run cold, reading "today's" candidates.
Nothing told the first recovered run that a week of scoring was owed, or
that time-limited sources (NWS CLI archives) age out first. The pipeline
now prepends a gap notice to the prompt; silence on a normal day.
"""

import os
import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parents[1]))

import gap  # noqa: E402

REPO = pathlib.Path(__file__).parents[2]
DAILY = REPO / "bin" / "daily.sh"


def briefs(tmp_path, *days):
    for d in days:
        (tmp_path / f"brief-{d}.json").write_text("{}")
    return tmp_path


def test_no_notice_when_yesterday_has_a_brief(tmp_path):
    briefs(tmp_path, "2026-09-30", "2026-10-01")
    assert gap.notice(tmp_path, "2026-10-02") == ""


def test_no_notice_on_a_fresh_install(tmp_path):
    assert gap.notice(tmp_path, "2026-10-02") == ""
    assert gap.notice(tmp_path / "missing", "2026-10-02") == ""


def test_todays_own_brief_does_not_hide_the_gap(tmp_path):
    # A rerun later the same day may find today's brief already written;
    # the gap is still measured from the last brief BEFORE today.
    briefs(tmp_path, "2026-10-01", "2026-10-09")
    assert "2026-10-01" in gap.notice(tmp_path, "2026-10-09")


def test_the_october_outage_names_its_span_and_size(tmp_path):
    briefs(tmp_path, "2026-09-30", "2026-10-01")
    note = gap.notice(tmp_path, "2026-10-09")
    assert "brief-2026-10-01.json" in note
    assert "2026-10-02..2026-10-08" in note
    assert "7 daily runs" in note


def test_notice_says_what_to_do_and_what_not_to(tmp_path):
    note = gap.notice(briefs(tmp_path, "2026-10-01"), "2026-10-09")
    assert "score" in note.lower()
    assert "wx.py cli" in note             # aging archives first
    assert "kalshi.py market" in note      # finals stay readable
    assert "unscorable" in note            # never reconstruct a pre-reg
    assert "narrative" in note             # and the brief says so


def test_single_missed_day_is_singular(tmp_path):
    note = gap.notice(briefs(tmp_path, "2026-10-07"), "2026-10-09")
    assert "1 daily run (2026-10-08)" in note


def test_ignores_non_brief_files(tmp_path):
    briefs(tmp_path, "2026-10-08")
    (tmp_path / "brief-2026-10-01.mp3").write_text("")
    (tmp_path / "brief-latest.json").write_text("{}")
    assert gap.notice(tmp_path, "2026-10-09") == ""


def test_cli_prints_notice_and_exits_zero(tmp_path):
    briefs(tmp_path, "2026-10-01")
    r = subprocess.run([sys.executable, str(REPO / "kalshi" / "gap.py"),
                        str(tmp_path), "--today", "2026-10-09"],
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    assert "PIPELINE GAP" in r.stdout


def run_claude_step_prompt(tmp_path, data_dir) -> str:
    # The real claude_step from daily.sh against a stub `claude` that records
    # its -p prompt (same pattern as test_daily_claude_step.py).
    stub_bin = tmp_path / "stub-bin"
    stub_bin.mkdir()
    record = tmp_path / "prompt.txt"
    stub = stub_bin / "claude"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        'while [ $# -gt 0 ]; do [ "$1" = -p ] && printf %s "$2" > '
        f'"{record}"; shift; done\n')
    stub.chmod(0o755)
    text = DAILY.read_text()
    start = text.index("claude_step() {")
    func = text[start:text.index("\n}", start) + 2]
    script = f'DATA_DIR="{data_dir}"\n' + func + "\nclaude_step\n"
    env = dict(os.environ, PATH=f"{stub_bin}:{os.environ['PATH']}")
    r = subprocess.run(["bash", "-c", script], cwd=REPO, env=env,
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return record.read_text()


def test_daily_prompt_carries_the_gap_notice(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "brief-2000-01-01.json").write_text("{}")
    prompt = run_claude_step_prompt(tmp_path, data)
    assert prompt.startswith(f"Data directory: {data}\n")  # contract kept
    assert "PIPELINE GAP" in prompt
    assert prompt.index("PIPELINE GAP") < prompt.index("# Kalshi daily judgment step")


def test_daily_prompt_unchanged_without_a_gap(tmp_path):
    prompt = run_claude_step_prompt(tmp_path, "/srv/no-such-kalseer-data")
    assert prompt.startswith("Data directory: /srv/no-such-kalseer-data\n"
                             "# Kalshi daily judgment step")


# Gap #3 ran seven days, and nobody could say whether a single FAILED alert
# had been sent: daily.sh's alert() fails silently when neither
# KALSEER_ALERT_URL nor KALSEER_ALERT_CMD is set. When the gap notice fires,
# it must also say if this host can page anyone, so the brief puts that in
# front of the human.
def test_gap_notice_flags_unconfigured_alerting(tmp_path):
    note = gap.notice(briefs(tmp_path, "2026-10-01"), "2026-10-09",
                      alerting=False)
    assert "KALSEER_ALERT_URL" in note
    assert "operator" in note.lower()  # the brief must surface it to the human


def test_gap_notice_quiet_about_alerting_when_configured(tmp_path):
    note = gap.notice(briefs(tmp_path, "2026-10-01"), "2026-10-09",
                      alerting=True)
    assert "PIPELINE GAP" in note
    assert "KALSEER_ALERT_URL" not in note


def test_cli_reads_alerting_config_from_env(tmp_path):
    briefs(tmp_path, "2026-10-01")
    base = {k: v for k, v in os.environ.items()
            if k not in ("KALSEER_ALERT_URL", "KALSEER_ALERT_CMD")}
    cmd = [sys.executable, str(REPO / "kalshi" / "gap.py"), str(tmp_path),
           "--today", "2026-10-09"]
    bare = subprocess.run(cmd, env=base, capture_output=True, text=True)
    assert "KALSEER_ALERT_URL" in bare.stdout
    wired = subprocess.run(cmd, env=dict(base, KALSEER_ALERT_CMD="notify"),
                           capture_output=True, text=True)
    assert "PIPELINE GAP" in wired.stdout
    assert "KALSEER_ALERT_URL" not in wired.stdout
    # An empty value counts as unset, same as daily.sh's ${VAR:-} tests.
    empty = subprocess.run(cmd, env=dict(base, KALSEER_ALERT_URL=""),
                           capture_output=True, text=True)
    assert "KALSEER_ALERT_URL" in empty.stdout
