"""speak.py backfills a recent brief whose audio was never made.

2026-11-12: the edge service answered NoAudioReceived to all 8 tries (3
in-process retries, then daily.sh's upgrade-and-retry), so the step failed
and brief-2026-11-12.mp3 was never written. speak only ever renders the one
date it is run for, so that brief would stay silent for good, even though
the service answered fine the next morning. The daily (no-argument) run now
also speaks any brief from the last BACKFILL_DAYS that has no mp3. Today's
take comes first and still decides the step's exit; a failed backfill is
logged and retried the next day.
"""

import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parents[1]))
import paper
import speak
from test_speak import fake_edge_tts


@pytest.fixture(autouse=True)
def _no_retry_sleep(monkeypatch):
    monkeypatch.setattr(speak.time, "sleep", lambda s: None)


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setattr(paper, "DATA", tmp_path)
    monkeypatch.setattr(speak, "_today", lambda: "2026-11-13")
    monkeypatch.setattr(sys, "argv", ["speak.py"])
    for d in ("2026-11-09", "2026-11-10", "2026-11-11", "2026-11-12",
              "2026-11-13"):
        (tmp_path / f"brief-{d}.json").write_text(
            json.dumps({"narrative_spoken": f"Brief for {d}."}))
    pub = tmp_path / "public"
    pub.mkdir()
    (pub / "brief-2026-11-11.mp3").write_bytes(b"ID3 good take 11")
    return tmp_path


def mp3s(data):
    return sorted(p.name for p in (data / "public").glob("*.mp3"))


def test_daily_run_backfills_recent_briefs_without_audio(data, monkeypatch,
                                                         capsys):
    tts = fake_edge_tts(fail=False)
    monkeypatch.setitem(sys.modules, "edge_tts", tts)
    speak.main()
    # 11/13 (today) and the missing 11/12 and 11/10; 11/09 is outside the
    # window, and 11/11's existing take is left alone.
    assert mp3s(data) == ["brief-2026-11-10.mp3", "brief-2026-11-11.mp3",
                          "brief-2026-11-12.mp3", "brief-2026-11-13.mp3"]
    assert (data / "public" / "brief-2026-11-11.mp3").read_bytes() == \
        b"ID3 good take 11"
    assert b"Brief for 2026-11-12." in \
        (data / "public" / "brief-2026-11-12.mp3").read_bytes()
    out = capsys.readouterr().out
    assert "backfill 2026-11-12: spoke" in out
    assert tts.calls == 3


def test_today_is_spoken_first(data, monkeypatch):
    order = []
    real = speak.synth
    monkeypatch.setattr(speak, "synth", lambda e, t, out: (
        order.append(out.name), real(e, t, out)))
    monkeypatch.setitem(sys.modules, "edge_tts", fake_edge_tts(fail=False))
    speak.main()
    assert order[0] == "brief-2026-11-13.mp3"


def test_failed_backfill_is_logged_and_does_not_fail_the_step(
        data, monkeypatch, capsys):
    # Today's take succeeds; every later call fails (4 tries per backfill).
    tts = fake_edge_tts(fail=False)
    calls = {"n": 0}
    real = speak.synth

    def flaky(edge_tts, text, out):
        calls["n"] += 1
        if calls["n"] > 1:
            raise RuntimeError("NoAudioReceived")
        return real(edge_tts, text, out)

    monkeypatch.setattr(speak, "synth", flaky)
    monkeypatch.setitem(sys.modules, "edge_tts", tts)
    speak.main()
    assert mp3s(data) == ["brief-2026-11-11.mp3", "brief-2026-11-13.mp3"]
    out = capsys.readouterr().out
    assert "backfill 2026-11-12: FAILED (NoAudioReceived)" in out


def test_todays_failure_still_fails_the_step_without_backfilling(
        data, monkeypatch):
    tts = fake_edge_tts(fail=True)
    monkeypatch.setitem(sys.modules, "edge_tts", tts)
    with pytest.raises(RuntimeError):
        speak.main()
    assert mp3s(data) == ["brief-2026-11-11.mp3"]
    assert tts.calls == len(speak.RETRY_WAITS) + 1


def test_an_explicit_date_speaks_only_that_date(data, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["speak.py", "2026-11-12"])
    monkeypatch.setitem(sys.modules, "edge_tts", fake_edge_tts(fail=False))
    speak.main()
    assert mp3s(data) == ["brief-2026-11-11.mp3", "brief-2026-11-12.mp3"]
