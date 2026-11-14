"""speak.py voices a refused backfill one paragraph at a time.

The 11/12 brief was refused (NoAudioReceived) on all 12 whole-text tries
over two days, while 11/13's brief spoke on its first try minutes before
the 11/13 backfill. A whole-take failure in the backfill now falls back to
per-paragraph takes, concatenated into one mp3. A paragraph that's still
refused is skipped, logged by number, and replaced with a spoken note.
"""

import json
import pathlib
import sys
import types

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parents[1]))
import paper
import speak


def poison_tts(*poison):
    """Refuses any text containing a poison substring, like a service that
    chokes on one passage; everything else renders at real-voice size."""
    mod = types.ModuleType("edge_tts")
    mod.texts = []

    class Communicate:
        def __init__(self, text, voice):
            self.text = text

        async def save(self, path):
            mod.texts.append(self.text)
            with open(path, "wb") as f:
                if any(p in self.text for p in poison):
                    raise RuntimeError("No audio was received.")
                f.write(b"[" + self.text.encode() + b"]"
                        + b"\0" * (360 * len(self.text)))

    mod.Communicate = Communicate
    return mod


@pytest.fixture(autouse=True)
def _no_retry_sleep(monkeypatch):
    monkeypatch.setattr(speak.time, "sleep", lambda s: None)


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setattr(paper, "DATA", tmp_path)
    monkeypatch.setattr(speak, "_today", lambda: "2026-11-13")
    monkeypatch.setattr(sys, "argv", ["speak.py"])
    (tmp_path / "brief-2026-11-13.json").write_text(
        json.dumps({"narrative_spoken": "Gas fell."}))
    (tmp_path / "brief-2026-11-12.json").write_text(json.dumps(
        {"narrative_spoken": "No trades.\n\nHormuz POISON week.\n\n"
                             "Diesel fell.\n\nTwo movies."}))
    return tmp_path


def mp3(data, date):
    return (data / "public" / f"brief-{date}.mp3")


def test_refused_paragraph_is_skipped_and_the_rest_is_voiced(data, monkeypatch,
                                                              capsys):
    tts = poison_tts("POISON")
    monkeypatch.setitem(sys.modules, "edge_tts", tts)
    speak.main()
    audio = mp3(data, "2026-11-12").read_bytes()
    # in order, without the refused paragraph, ending with the spoken note
    heard = [p for p in ("morning brief, 2026-11-12", "No trades.", "Diesel fell.",
                         "Two movies.", "couldn't be voiced") if p.encode() in audio]
    assert len(heard) == 5
    assert [audio.index(p.encode()) for p in heard] == \
        sorted(audio.index(p.encode()) for p in heard)
    assert b"POISON" not in audio
    out = capsys.readouterr()
    assert "backfill 2026-11-12: whole take FAILED" in out.out
    assert "spoke in parts" in out.out and "skipped paragraph [3]" in out.out
    assert "tts part 3/5" in out.err  # the header counts as paragraph 1
    assert not list((data / "public").glob("*.part"))


def test_parts_without_refusals_carry_no_note(data, monkeypatch):
    # The whole take fails, but every paragraph alone renders fine.
    tts = poison_tts("Hormuz POISON week.\n\nDiesel")
    monkeypatch.setitem(sys.modules, "edge_tts", tts)
    speak.main()
    audio = mp3(data, "2026-11-12").read_bytes()
    assert b"POISON" in audio and b"couldn't be voiced" not in audio


def test_mostly_refused_brief_publishes_nothing(data, monkeypatch, capsys):
    tts = poison_tts("No trades", "POISON", "Diesel")
    monkeypatch.setitem(sys.modules, "edge_tts", tts)
    speak.main()
    assert not mp3(data, "2026-11-12").exists()
    assert "backfill 2026-11-12: FAILED (3 of 5 paragraphs refused)" in \
        capsys.readouterr().out
    assert not list((data / "public").glob("*.part"))


def test_each_part_gets_one_retry(data, monkeypatch):
    tts = poison_tts("POISON")
    monkeypatch.setitem(sys.modules, "edge_tts", tts)
    speak.main()
    assert sum("POISON" in t and "\n\n" not in t for t in tts.texts) == \
        len(speak.PART_WAITS) + 1


def test_todays_take_never_falls_back_to_parts(data, monkeypatch):
    (data / "brief-2026-11-13.json").write_text(
        json.dumps({"narrative_spoken": "Gas POISON.\n\nDiesel fell."}))
    monkeypatch.setitem(sys.modules, "edge_tts", poison_tts("POISON"))
    with pytest.raises(RuntimeError):
        speak.main()  # daily.sh's upgrade-and-retry still sees the failure
    assert not mp3(data, "2026-11-13").exists()
