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


def fake_edge_tts(fail):
    """Stand-in for edge_tts: like the real lib, save() creates the output
    file before the network can fail. fail=True fails every call; an int
    fails that many calls, then succeeds."""
    mod = types.ModuleType("edge_tts")
    mod.calls = 0

    class Communicate:
        def __init__(self, text, voice):
            self.text = text

        async def save(self, path):
            mod.calls += 1
            with open(path, "wb") as f:
                if fail is True or mod.calls <= fail:
                    raise RuntimeError("403, message='Invalid response status'")
                f.write(b"ID3" + self.text.encode())

    mod.Communicate = Communicate
    return mod


@pytest.fixture(autouse=True)
def _no_retry_sleep(monkeypatch):
    monkeypatch.setattr(speak.time, "sleep", lambda s: None)


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


# --- wiki audio: speak.py --wiki renders each wiki page to public/wiki/ ---
#
# The in-app wiki (frontend/src/content/*.md) is reading material; the same
# edge-tts voice reads it aloud. Pages change rarely, so a page is only
# re-synthesized when its spoken text changes (public/wiki/index.json keeps a
# hash per slug) — otherwise every run would commit fresh mp3s to the data
# repo. Live {{token}} lines are left out of the audio for the same reason:
# filling them would change the text (and the mp3) every day, and an
# unfilled or stale number read aloud would be wrong.

def test_wiki_speech_reads_admonitions_with_their_label():
    md = '!!! warning "Never bet full Kelly"\n    Full Kelly assumes you are right.\n'
    text = speak.wiki_to_speech(md)
    assert "Warning: Never bet full Kelly." in text
    assert "Full Kelly assumes you are right." in text
    assert "!!!" not in text


def test_wiki_speech_reads_table_rows_as_header_cell_pairs():
    md = ("| Treatment | Consequence |\n|---|---|\n"
          "| **Gambling income** | Losses only offset winnings. |\n")
    text = speak.wiki_to_speech(md)
    assert "Treatment: Gambling income. Consequence: Losses only offset winnings." in text
    assert "|" not in text and "---" not in text


def test_wiki_speech_speaks_formula_fences():
    md = "```\nfee = 0.07 × contracts × price × (1 − price)\n```\n"
    text = speak.wiki_to_speech(md)
    assert "fee equals 0.07 times contracts times price times (1 minus price)" in text
    assert "```" not in text


def test_wiki_speech_drops_live_token_lines_and_toc():
    md = ("# How it works\n\n[[_TOC_]]\n\n## Live numbers\n\n"
          "Bankroll **{{bankroll}}** today.\n\n## Next\n\nPlain text.\n")
    text = speak.wiki_to_speech(md)
    assert "{{" not in text and "bankroll" not in text.lower()
    assert "_TOC_" not in text
    assert "live numbers" in text.lower() and "dashboard" in text.lower()
    assert "How it works." in text and "Plain text." in text


@pytest.fixture
def wiki(tmp_path, monkeypatch):
    content = tmp_path / "content"
    content.mkdir()
    (content / "manifest.json").write_text(json.dumps([
        {"id": "basics", "label": "Basics", "items": [
            {"slug": "kalshi-101", "title": "Kalshi 101"},
            {"slug": "glossary", "title": "Glossary"},
            {"slug": "missing", "title": "Not written yet"}]}]))
    (content / "kalshi-101.md").write_text("# Kalshi 101\n\nYes or no.\n")
    (content / "glossary.md").write_text("# Glossary\n\nEdge: fair minus price.\n")
    data = tmp_path / "data"
    monkeypatch.setattr(paper, "DATA", data)
    monkeypatch.setattr(speak, "WIKI_CONTENT", content)
    return content, data / "public" / "wiki"


def test_wiki_renders_every_page_and_records_hashes(wiki, monkeypatch):
    content, out = wiki
    monkeypatch.setitem(sys.modules, "edge_tts", fake_edge_tts(fail=False))
    speak.speak_wiki()
    assert (out / "kalshi-101.mp3").read_bytes().startswith(b"ID3")
    # "Kalshi" is respelled for the voice (pronounce()), so the title is
    # spoken as SPOKEN_KALSHI.
    assert f"{speak.SPOKEN_KALSHI} 101".encode() in (out / "kalshi-101.mp3").read_bytes()
    assert (out / "glossary.mp3").exists()
    assert not (out / "missing.mp3").exists()
    assert set(json.loads((out / "index.json").read_text())) == {"kalshi-101", "glossary"}


def test_wiki_skips_unchanged_pages(wiki, monkeypatch):
    content, out = wiki
    monkeypatch.setitem(sys.modules, "edge_tts", fake_edge_tts(fail=False))
    speak.speak_wiki()
    (out / "glossary.mp3").write_bytes(b"ID3 untouched")
    (content / "kalshi-101.md").write_text("# Kalshi 101\n\nYes or no. Edited.\n")
    speak.speak_wiki()
    assert (out / "glossary.mp3").read_bytes() == b"ID3 untouched"
    assert b"Edited." in (out / "kalshi-101.mp3").read_bytes()


def test_wiki_failure_keeps_old_audio_and_raises(wiki, monkeypatch):
    content, out = wiki
    monkeypatch.setitem(sys.modules, "edge_tts", fake_edge_tts(fail=False))
    speak.speak_wiki()
    before = json.loads((out / "index.json").read_text())
    (content / "glossary.md").write_text("# Glossary\n\nRewritten.\n")
    monkeypatch.setitem(sys.modules, "edge_tts", fake_edge_tts(fail=True))
    with pytest.raises(RuntimeError):
        speak.speak_wiki()
    assert b"Edge: fair minus price" in (out / "glossary.mp3").read_bytes()
    # The failed page's hash is not advanced, so the next run retries it.
    assert json.loads((out / "index.json").read_text())["glossary"] == before["glossary"]
    assert not list(out.glob("*.part"))


def test_speak_step_passes_its_arguments_through(tmp_path):
    record = tmp_path / "argv"
    speaker = tmp_path / "speaker"
    speaker.write_text(f'#!/usr/bin/env bash\necho "$*" > "{record}"\n')
    speaker.chmod(0o755)
    script = f'SPEAK_PY="{speaker}"\n' + extract_speak_step() + "\nspeak_step --wiki\n"
    r = subprocess.run(["bash", "-c", script], cwd=tmp_path, capture_output=True,
                       text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    assert record.read_text().split() == ["kalshi/speak.py", "--wiki"]


def test_wiki_speech_joins_hard_wrapped_lines_into_one_sentence():
    md = ('!!! danger "Not tax advice"\n'
          "    The tax treatment of prediction-market\n"
          "    contracts is unsettled.\n\n"
          "- first item\n- second item\n")
    text = speak.wiki_to_speech(md)
    assert "prediction-market contracts is unsettled." in text
    assert "first item.\nsecond item." in text


def test_wiki_speech_headings_always_pause():
    assert speak.wiki_to_speech("## Live (from today)\n\nBody.\n").startswith(
        "Live (from today).")


# Edge's voice reads "Kalseer" as "Kal-shure"; it's Kalshi + seer, three
# syllables. Every spoken text goes through pronounce() on its way to the
# voice, and the wiki hash covers the respelled text so a respelling change
# re-renders the pages that say the name.

def test_pronounce_respells_the_name():
    assert speak.pronounce("Kalseer morning brief. KALSEER wiki.") == (
        f"{speak.SPOKEN_NAME} morning brief. {speak.SPOKEN_NAME} wiki.")
    assert "kalseer" not in speak.SPOKEN_NAME.lower().replace("-", "")


def test_synth_speaks_the_respelled_name(brief, monkeypatch):
    monkeypatch.setitem(sys.modules, "edge_tts", fake_edge_tts(fail=False))
    speak.main()
    spoken = brief.read_bytes()
    assert b"Kalseer" not in spoken
    assert speak.SPOKEN_NAME.encode() in spoken


def test_wiki_rerenders_when_the_respelling_changes(wiki, monkeypatch):
    content, out = wiki
    monkeypatch.setitem(sys.modules, "edge_tts", fake_edge_tts(fail=False))
    speak.speak_wiki()
    (out / "glossary.mp3").write_bytes(b"ID3 old name")
    monkeypatch.setattr(speak, "SPOKEN_NAME", "Kal-seer")
    speak.speak_wiki()
    assert b"Kal-seer" in (out / "glossary.mp3").read_bytes()


def test_pronounce_respells_kalshi_too():
    # Same lexicon gap: "Kalshi" also came out "Kal-shure" (2026-10-14).
    out = speak.pronounce("Per Kalshi's help center, KALSHI fees apply.")
    assert out == (f"Per {speak.SPOKEN_KALSHI}'s help center, "
                   f"{speak.SPOKEN_KALSHI} fees apply.")
    # Tickers and the Kalseer name are untouched by the Kalshi rule.
    assert speak.pronounce("Kalseer") == speak.SPOKEN_NAME


def test_transient_tts_failure_is_retried_in_process(brief, monkeypatch, capsys):
    # 2026-10-23: NoAudioReceived twice, then the same text rendered fine.
    tts = fake_edge_tts(fail=2)
    monkeypatch.setitem(sys.modules, "edge_tts", tts)
    speak.main()
    assert brief.read_bytes().startswith(b"ID3") and tts.calls == 3
    assert "retrying" in capsys.readouterr().err


def test_persistent_tts_failure_gives_up_after_the_retries(brief, monkeypatch):
    tts = fake_edge_tts(fail=True)
    monkeypatch.setitem(sys.modules, "edge_tts", tts)
    with pytest.raises(RuntimeError):
        speak.main()
    assert tts.calls == len(speak.RETRY_WAITS) + 1 and not brief.exists()
