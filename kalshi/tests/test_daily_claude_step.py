"""bin/daily.sh claude_step: file-tool grants on the run's actual data dir.

The repo allowlist's Edit(data/**) only matches the default ./data layout; a
deployed KALSEER_DATA_DIR lives outside the checkout, so the judgment step
could never Edit its own journal — every watchlist refresh was a full-file
Write rewrite (the source-hazards ledger's "data-dir edits still friction").
The step must pass --allowedTools rules built from $DATA_DIR itself, so any
deployment gets Read/Edit on its data dir without host-specific paths in
the public repo (Edit rules cover all file-editing tools, Write included).

The tests run the real claude_step function (extracted verbatim from
daily.sh) against a stub `claude` binary that records its argv.
"""

import json
import os
import pathlib
import subprocess

REPO = pathlib.Path(__file__).parents[2]
DAILY = REPO / "bin" / "daily.sh"


def extract_claude_step() -> str:
    # The function's closing brace is the first column-0 "}" after its start.
    text = DAILY.read_text()
    start = text.index("claude_step() {")
    end = text.index("\n}", start)
    return text[start:end + 2]


def run_claude_step(tmp_path, data_dir: str) -> list[str]:
    stub_bin = tmp_path / "stub-bin"
    stub_bin.mkdir()
    record = tmp_path / "argv.json"
    stub = stub_bin / "claude"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        "python3 - \"$@\" <<EOF\n"
        "import json, sys\n"
        f"json.dump(sys.argv[1:], open({str(record)!r}, 'w'))\n"
        "EOF\n"
    )
    stub.chmod(0o755)
    script = f'DATA_DIR="{data_dir}"\n' + extract_claude_step() + "\nclaude_step\n"
    env = dict(os.environ, PATH=f"{stub_bin}:{os.environ['PATH']}")
    r = subprocess.run(["bash", "-c", script], cwd=REPO, env=env,
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return json.loads(record.read_text())


def test_judgment_step_gets_file_tools_on_the_data_dir(tmp_path):
    argv = run_claude_step(tmp_path, "/srv/elsewhere/kalseer-data")
    assert "--allowedTools" in argv
    rules = argv[argv.index("--allowedTools") + 1:]
    # Permission-rule absolute paths start with "//" — $DATA_DIR already
    # carries the leading slash, so the rule is "Edit(/$DATA_DIR/**)".
    for rule in ("Read(//srv/elsewhere/kalseer-data/**)",
                 "Edit(//srv/elsewhere/kalseer-data/**)"):
        assert rule in rules, f"missing {rule} in {rules}"


def test_no_write_rule_only_edit_matches_file_tools(tmp_path):
    """Hazard 1f: the harness warns in every judgment log that
    Write(path) rules "are not matched by file permission checks — only
    Edit(path) rules are", and Edit rules already cover all file-editing
    tools (Write included). The Write grant is dead weight that prints a
    warning line into every daily log; it must stay gone."""
    argv = run_claude_step(tmp_path, "/srv/elsewhere/kalseer-data")
    rules = argv[argv.index("--allowedTools") + 1:]
    assert not [rule for rule in rules if rule.startswith("Write(")], rules


def test_permission_mode_stays_default(tmp_path):
    # The grants are additive; the step must not drift to a looser mode.
    argv = run_claude_step(tmp_path, "/srv/elsewhere/kalseer-data")
    assert argv[argv.index("--permission-mode") + 1] == "default"


def test_prompt_still_leads_with_the_data_dir(tmp_path):
    # daily-prompt.md's "first line of this prompt" contract.
    argv = run_claude_step(tmp_path, "/srv/elsewhere/kalseer-data")
    prompt = argv[argv.index("-p") + 1]
    assert prompt.startswith("Data directory: /srv/elsewhere/kalseer-data\n")


# The 2026-10-02..10-08 outage: #42 pinned claude-opus-5-5, the host CLI was
# too old for it, and every judgment run died on "API Error: 400 Claude Code
# 2.1.274 does not support this model; version 2.1.280 or newer is required".
# Seven briefs lost behind a generic "FAILED at step 'claude'" alert. The fix
# is `claude update`, not /login — the alert must say which.
CLI_OUTDATED_OUTPUT = (
    "API Error: 400 Claude Code 2.1.274 does not support this model; "
    "version 2.1.280 or newer is required. Run 'claude update', or update "
    "the Claude desktop app, then try again.")


def run_claude_step_flags(tmp_path, claude_body: str) -> dict:
    stub_bin = tmp_path / "stub-bin"
    stub_bin.mkdir()
    stub = stub_bin / "claude"
    stub.write_text("#!/usr/bin/env bash\n" + claude_body + "\n")
    stub.chmod(0o755)
    script = ('DATA_DIR=/srv/kalseer-data\nAUTH_FAILED=""\nCLI_OUTDATED=""\n'
              + extract_claude_step() + "\nclaude_step\n"
              'echo "AUTH_FAILED=$AUTH_FAILED CLI_OUTDATED=$CLI_OUTDATED"\n')
    env = dict(os.environ, PATH=f"{stub_bin}:{os.environ['PATH']}")
    r = subprocess.run(["bash", "-c", script], cwd=REPO, env=env,
                       capture_output=True, text=True, timeout=30)
    last = r.stdout.strip().splitlines()[-1]
    return dict(kv.split("=", 1) for kv in last.split(" "))


def test_claude_step_names_an_outdated_cli(tmp_path):
    flags = run_claude_step_flags(
        tmp_path, f"echo {CLI_OUTDATED_OUTPUT!r} >&2; exit 1")
    assert flags == {"AUTH_FAILED": "", "CLI_OUTDATED": "1"}


def test_unknown_model_warning_alone_is_not_outdated(tmp_path):
    # A CLI that merely lacks catalog metadata for the model prints this
    # warning but still runs; that must not cry "update" on a healthy run.
    flags = run_claude_step_flags(
        tmp_path,
        "echo 'model isn'\"'\"'t described by this version'\"'\"'s model "
        "catalog; update Claude Code' >&2; echo ok")
    assert flags["CLI_OUTDATED"] == ""


def extract_alert_block() -> str:
    text = DAILY.read_text()
    start = text.index('if [ -n "$FAILED_STEP" ]; then\n  MSG=')
    end = text.index("\nfi\n", start)
    return text[start:end + 4]


def test_outdated_cli_alert_says_claude_update():
    script = ('FAILED_STEP=claude\nAUTH_FAILED=""\nCLI_OUTDATED=1\n'
              'LOG=/x/daily.log\nPREV_OK=True\n'
              'alert() { echo "ALERT: $1"; }\n' + extract_alert_block())
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True,
                       timeout=30)
    assert "claude update" in r.stdout, r.stdout + r.stderr
    assert "/login" not in r.stdout  # the wrong fix costs another day
    assert "brief" in r.stdout       # ...and what it costs to ignore
