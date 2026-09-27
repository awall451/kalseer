"""bin/auth-probe.sh: evening claude-credential probe (operator item #18).

Gap #2 (2026-09-06..09-17): a silent OAuth expiry cost 12 straight briefs.
daily.sh names the condition reactively, but at 08:00 the run is already lost
and the human is asleep; the probe spends one trivial claude call the evening
before instead. Stubs everywhere: a fake `claude` on PATH, file:// network
probes, and KALSEER_ALERT_CMD pointed at a recorder — no real network, no
tokens spent.
"""

import os
import pathlib
import subprocess

REPO = pathlib.Path(__file__).parents[2]
SCRIPT = REPO / "bin" / "auth-probe.sh"


def run_probe(tmp_path, claude_body: str, network_up: bool = True):
    stub_bin = tmp_path / "stub-bin"
    stub_bin.mkdir()
    claude = stub_bin / "claude"
    claude.write_text("#!/usr/bin/env bash\n" + claude_body + "\n")
    claude.chmod(0o755)

    alerts = tmp_path / "alerts.txt"
    alert_cmd = stub_bin / "alert-rec"
    alert_cmd.write_text(f'#!/usr/bin/env bash\necho "$@" >> "{alerts}"\n')
    alert_cmd.chmod(0o755)

    net_probe = tmp_path / "net-up"
    if network_up:
        net_probe.write_text("ok\n")

    env = dict(
        os.environ,
        PATH=f"{stub_bin}:{os.environ['PATH']}",
        KALSEER_NET_PROBE_URL=net_probe.as_uri(),
        KALSEER_AUTHPROBE_NET_WAIT="0",
        KALSEER_ALERT_CMD=str(alert_cmd),
    )
    env.pop("KALSEER_ALERT_URL", None)
    r = subprocess.run(["bash", str(SCRIPT)], env=env, cwd=REPO,
                       capture_output=True, text=True, timeout=30)
    return r, (alerts.read_text() if alerts.exists() else "")


def test_working_credentials_exit_zero_and_stay_quiet(tmp_path):
    r, alerts = run_probe(tmp_path, 'echo ok')
    assert r.returncode == 0, r.stdout + r.stderr
    assert alerts == ""


def test_dead_login_alerts_with_the_fix(tmp_path):
    r, alerts = run_probe(
        tmp_path, 'echo "OAuth token expired. Please run /login" >&2; exit 1')
    assert r.returncode == 1
    assert "/login" in alerts  # the alert must say what to do, not just what broke
    assert "brief" in alerts   # ...and what it costs to ignore


def test_auth_error_with_success_exit_code_still_alerts(tmp_path):
    # The CLI has surfaced auth failures in output while exiting 0; the grep
    # daily.sh uses reactively must gate the probe's verdict too.
    r, alerts = run_probe(tmp_path, 'echo "failed to authenticate"; exit 0')
    assert r.returncode == 1
    assert alerts != ""


def test_no_network_is_not_an_auth_verdict(tmp_path):
    # A 20:00 outage must not cry wolf about credentials (and the alert
    # could not send anyway). Quiet exit 0; the morning gate handles it.
    r, alerts = run_probe(tmp_path, 'echo ok', network_up=False)
    assert r.returncode == 0, r.stdout + r.stderr
    assert alerts == ""
