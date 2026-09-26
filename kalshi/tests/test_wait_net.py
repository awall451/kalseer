"""bin/wait-net.sh: hold a Persistent= catch-up run until the network is up.

Gap #1 (2026-08-31..09-02): the host woke at 14:09, the timer fired instantly,
and every step — including the failure alert itself — died on DNS. The gate is
probed with file:// URLs so the tests never depend on real network state.
"""

import pathlib
import subprocess
import threading
import time

REPO = pathlib.Path(__file__).parents[2]
SCRIPT = REPO / "bin" / "wait-net.sh"


def run_gate(url, max_wait="0", poll="0.1"):
    return subprocess.run(["bash", str(SCRIPT), url, max_wait, poll],
                          capture_output=True, text=True, timeout=30)


def test_reachable_probe_exits_zero_immediately(tmp_path):
    probe = tmp_path / "up"
    probe.write_text("ok\n")
    start = time.monotonic()
    r = run_gate(probe.as_uri())
    assert r.returncode == 0
    assert time.monotonic() - start < 5  # no pointless polling once it answers


def test_unreachable_probe_exits_one_after_deadline(tmp_path):
    r = run_gate((tmp_path / "never").as_uri(), max_wait="0")
    assert r.returncode == 1  # deadline passed: caller proceeds, honestly failed


def test_network_arriving_mid_wait_unblocks(tmp_path):
    probe = tmp_path / "late"
    threading.Timer(0.5, lambda: probe.write_text("ok\n")).start()
    r = run_gate(probe.as_uri(), max_wait="15", poll="0.1")
    assert r.returncode == 0


def test_default_probe_url_is_a_settlement_host():
    # The default probe must be a host the pipeline needs anyway, so a "network
    # up" verdict means the run can actually do its job.
    assert "api.elections.kalshi.com" in SCRIPT.read_text()
