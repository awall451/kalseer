"""bin/daily.sh health_check: a DNS blip must not fail a finished run.

2026-11-13: every step through push was ok, then `--- FAILED: health
(exit 6)` paged the human. curl exit 6 is "could not resolve host", which
curl's --retry treats as permanent, so the five retries never ran. And -s
hid the reason, so the log showed only the bare number. health_check retries
every error and names the curl exit code in words. It never logs the URL,
because a private dashboard address belongs in the env file, not the public log.
"""

import os
import pathlib
import subprocess

REPO = pathlib.Path(__file__).parents[2]
DAILY = REPO / "bin" / "daily.sh"


def extract_health_fn() -> str:
    text = DAILY.read_text()
    start = text.index("health_check() {")
    end = text.index("\n}", start)
    return text[start:end + 2]


def run_health(tmp_path, curl_rc: int):
    stub = tmp_path / "bin"
    stub.mkdir()
    (stub / "curl").write_text(
        f'#!/bin/bash\necho "$@" > {tmp_path}/argv\nexit {curl_rc}\n')
    os.chmod(stub / "curl", 0o755)
    env = dict(os.environ, PATH=f"{stub}:{os.environ['PATH']}",
               HEALTH_URL="https://dash.example.internal/data/aggregates.json")
    r = subprocess.run(["bash", "-c", extract_health_fn() + "\nhealth_check\n"],
                       env=env, capture_output=True, text=True, timeout=30)
    return r, (tmp_path / "argv").read_text()


def test_health_retries_dns_failures(tmp_path):
    _, argv = run_health(tmp_path, 0)
    assert "--retry-all-errors" in argv
    assert "--retry" in argv.split()
    assert "dash.example.internal" in argv


def test_health_ok_is_quiet_and_green(tmp_path):
    r, _ = run_health(tmp_path, 0)
    assert r.returncode == 0
    assert r.stdout == ""


def test_health_failure_names_the_curl_error(tmp_path):
    r, _ = run_health(tmp_path, 6)
    assert r.returncode == 6  # run_step still logs "(exit 6)" and alerts
    assert "could not resolve host" in r.stdout
    assert "dash.example.internal" not in r.stdout + r.stderr


def test_health_failure_names_http_errors(tmp_path):
    r, _ = run_health(tmp_path, 22)
    assert r.returncode == 22
    assert "HTTP error" in r.stdout


def test_health_failure_unknown_code_still_logged(tmp_path):
    r, _ = run_health(tmp_path, 92)
    assert r.returncode == 92
    assert "curl exit 92" in r.stdout


def test_health_step_uses_health_check():
    text = DAILY.read_text()
    assert "run_step health health_check" in text
    assert "run_step health curl" not in text
