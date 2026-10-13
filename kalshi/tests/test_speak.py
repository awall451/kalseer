"""speak.py + daily.sh speak_step: a failed TTS run must never leave a
broken speaker button, and a stale edge-tts client must heal itself.

2026-10-13: Microsoft's Edge read-aloud endpoint started 403ing the
handshake from edge-tts 7.2.8 (it rejects outdated client versions). Two
defects turned that into a lost morning brief:
  1. edge-tts opens the output file before the websocket handshake, so the
     failed run left a 0-byte brief-<date>.mp3 — and the dashboard shows the
     speaker button whenever the mp3 exists, so the button played nothing.
  2. Nothing ever upgraded edge-tts on the pipeline host; the fix (7.3.1)
     had already shipped, the host just never picked it up.
speak.py now synthesizes to a temp file and renames only on success;
speak_step upgrades edge-tts once and retries when the first attempt fails.
"""

import json
import os
import pathlib
import subprocess
import sys
import types

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parents[1]))
import paper
import speak

REPO = pathlib.Path(__file__).parents[2]
DAILY = REPO / "bin" / "daily.sh"


def fake_edge_tts(fail: bool):
    """Stand-in for edge_tts: like the real lib, save() creates the output
    file before the network can fail."""
    mod = types.ModuleType("edge_tts")

    class Communicate:
        def __init__(self, text, voice):
            self.text = text

        async def save(self, path):
            with open(path, "wb") as f:
                if fail:
                    raise RuntimeError("403, message='Invalid response status'")
                f.write(b"ID3" + self.text.encode())

    mod.Communicate = Communicate
    return mod


@pytest.fixture
def brief(tmp_path, monkeypatch):
    monkeypatch.setattr(paper, "DATA", tmp_path)
    (tmp_path / "brief-2026-10-13.json").write_text(
        json.dumps({"narrative_spoken": "Gas fell a cent."}))
    monkeypatch.setattr(sys, "argv", ["speak.py", "2026-10-13"])
    return tmp_path / "public" / "brief-2026-10-13.mp3"


def test_success_writes_mp3_and_no_temp(brief, monkeypatch):
    monkeypatch.setitem(sys.modules, "edge_tts", fake_edge_tts(fail=False))
    speak.main()
    assert brief.read_bytes().startswith(b"ID3")
    assert list(brief.parent.iterdir()) == [brief]


def test_failure_leaves_no_empty_mp3(brief, monkeypatch):
    monkeypatch.setitem(sys.modules, "edge_tts", fake_edge_tts(fail=True))
    with pytest.raises(RuntimeError):
        speak.main()
    assert list(brief.parent.iterdir()) == []


def test_failure_keeps_an_earlier_good_mp3(brief, monkeypatch):
    brief.parent.mkdir(parents=True)
    brief.write_bytes(b"ID3 earlier good take")
    monkeypatch.setitem(sys.modules, "edge_tts", fake_edge_tts(fail=True))
    with pytest.raises(RuntimeError):
        speak.main()
    assert brief.read_bytes() == b"ID3 earlier good take"
    assert list(brief.parent.iterdir()) == [brief]


# --- daily.sh speak_step: upgrade edge-tts once and retry on failure ---

def extract_speak_step() -> str:
    # The function's closing brace is the first column-0 "}" after its start.
    text = DAILY.read_text()
    start = text.index("speak_step() {")
    end = text.index("\n}", start)
    return text[start:end + 2]


def run_speak_step(tmp_path, speak_fails: int, with_pip: bool = True):
    """Run speak_step in a scratch checkout whose speaker fails its first
    `speak_fails` calls; returns (exit code, speak calls, pip argv lists)."""
    calls = tmp_path / "speak-calls"
    pip_log = tmp_path / "pip-calls"
    speaker = tmp_path / "speaker"
    speaker.write_text(
        "#!/usr/bin/env bash\n"
        f'echo x >> "{calls}"\n'
        f'[ "$(wc -l < "{calls}")" -gt {speak_fails} ]\n')
    speaker.chmod(0o755)
    if with_pip:
        venv_bin = tmp_path / ".venv" / "bin"
        venv_bin.mkdir(parents=True)
        pip = venv_bin / "pip"
        pip.write_text(f'#!/usr/bin/env bash\necho "$*" >> "{pip_log}"\n')
        pip.chmod(0o755)
    script = f'SPEAK_PY="{speaker}"\n' + extract_speak_step() + "\nspeak_step\n"
    r = subprocess.run(["bash", "-c", script], cwd=tmp_path, env=dict(os.environ),
                       capture_output=True, text=True, timeout=30)
    n = len(calls.read_text().splitlines()) if calls.exists() else 0
    pips = pip_log.read_text().splitlines() if pip_log.exists() else []
    return r.returncode, n, pips


def test_speak_ok_first_try_does_not_touch_pip(tmp_path):
    assert run_speak_step(tmp_path, speak_fails=0) == (0, 1, [])


def test_speak_failure_upgrades_edge_tts_and_retries(tmp_path):
    rc, n, pips = run_speak_step(tmp_path, speak_fails=1)
    assert (rc, n) == (0, 2)
    assert len(pips) == 1 and "-U" in pips[0].split() and "edge-tts" in pips[0]


def test_speak_still_failing_after_upgrade_fails_the_step(tmp_path):
    rc, n, pips = run_speak_step(tmp_path, speak_fails=2)
    assert rc != 0 and n == 2 and len(pips) == 1


def test_no_venv_pip_means_no_retry(tmp_path):
    rc, n, pips = run_speak_step(tmp_path, speak_fails=1, with_pip=False)
    assert rc != 0 and n == 1 and pips == []
