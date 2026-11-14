"""Render the daily brief narrative to speech: public/brief-<date>.mp3.

Uses edge-tts (Microsoft's neural voices — the same family Clipchamp
uses) via the free Edge endpoint; no API key. The dashboard shows a
speaker button only when the mp3 exists for a date, so this step is
safely optional: if edge-tts isn't installed we skip with a note.

Also renders the in-app wiki (frontend/src/content/*.md, in manifest order)
to public/wiki/<slug>.mp3 for listening; a page is only re-synthesized when
its spoken text changes (hashes in public/wiki/index.json).

Usage: speak.py [YYYY-MM-DD]   (defaults to today, else newest brief)
       speak.py --wiki
Env:   KALSEER_TTS_VOICE (default en-US-AndrewNeural)
"""

import asyncio
import datetime as dt
import hashlib
import json
import os
import pathlib
import re
import sys
import time

import paper

VOICE = os.environ.get("KALSEER_TTS_VOICE", "en-US-AndrewNeural")
# The voice has no lexicon entry for these names and guesses from spelling:
# both "Kalseer" and "Kalshi" come out "Kal-shure". Respelled on the way to
# the voice ("Cal" so it isn't "Kawl"). Kalseer = Kalshi + seer.
SPOKEN_NAME = "Cal-see-er"
SPOKEN_KALSHI = "Cal-shee"
WIKI_CONTENT = pathlib.Path(__file__).resolve().parents[1] / "frontend" / "src" / "content"


def md_to_text(md: str) -> str:
    """Markdown -> plain speakable text."""
    s = re.sub(r"```[\s\S]*?```", " ", md)
    s = re.sub(r"`([^`]*)`", r"\1", s)
    s = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", s)
    s = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", s)
    s = re.sub(r"^\s{0,3}#{1,6}\s*", "", s, flags=re.M)
    s = re.sub(r"[*_]{1,3}([^*_]+)[*_]{1,3}", r"\1", s)
    s = re.sub(r"^\s*[-+*]\s+", "", s, flags=re.M)
    return re.sub(r"[ \t]+", " ", s).strip()


MONTHS = {"JAN": "January", "FEB": "February", "MAR": "March", "APR": "April",
          "MAY": "May", "JUN": "June", "JUL": "July", "AUG": "August",
          "SEP": "September", "OCT": "October", "NOV": "November", "DEC": "December"}


def humanize(text: str) -> str:
    """Fallback for briefs without narrative_spoken: swap tickers for
    series names (via series-cache slugs) and speak the symbols."""
    slugs = {}
    if (paper.DATA / "public" / "series.json").exists():
        slugs = json.loads((paper.DATA / "public" / "series.json").read_text())

    def ticker_words(m):
        parts = m.group(0).split("-")
        name = (slugs.get(parts[0]) or "this market").replace("-", " ")
        dm = re.match(r"^\d{2}([A-Z]{3})(\d{2})$", parts[1]) if len(parts) > 1 else None
        when = f" for {MONTHS[dm.group(1)]} {int(dm.group(2))}" if dm and dm.group(1) in MONTHS else ""
        strike = parts[-1] if len(parts) > 2 else ""
        at = f", the {strike.lstrip('BT')} strike" if strike else ""
        return f"the {name} market{when}{at}"

    s = re.sub(r"\bKX[A-Z0-9]+(?:-[A-Z0-9.]+)+", ticker_words, text)
    s = s.replace("¢", " cents").replace("≤", " at or below ").replace("≥", " at or above ")
    s = re.sub(r">(?=\s?\$?\d)", " above ", s)
    s = re.sub(r"<(?=\s?\$?\d)", " below ", s)
    s = re.sub(r"\s?@\s?", " at ", s)
    return re.sub(r"[ \t]+", " ", s)


def _today() -> str:
    return dt.date.today().isoformat()


def pick_brief(arg_date: str | None):
    if arg_date:
        p = paper.DATA / f"brief-{arg_date}.json"
        return (arg_date, p) if p.exists() else sys.exit(f"no brief for {arg_date}")
    today = _today()
    p = paper.DATA / f"brief-{today}.json"
    if p.exists():
        return today, p
    briefs = sorted(paper.DATA.glob("brief-*.json"))
    if not briefs:
        sys.exit("no briefs exist yet")
    newest = briefs[-1]
    return newest.stem.replace("brief-", ""), newest


def pronounce(text: str) -> str:
    text = re.sub(r"\bkalseer\b", SPOKEN_NAME, text, flags=re.I)
    return re.sub(r"\bkalshi\b", SPOKEN_KALSHI, text, flags=re.I)


# The edge service intermittently answers with NoAudioReceived for text it
# renders fine minutes later (2026-10-23: the brief failed twice, then the
# identical text succeeded). Retry in-process before giving up; a client too
# old for the service fails every try and falls through to daily.sh's
# upgrade-and-retry.
RETRY_WAITS = (5, 20, 60)

# It can also end the stream early without raising: 2026-10-25 saved 2160
# bytes (~0.4s) for a 1207-character brief and the step logged "ok". Real
# takes run ~360 bytes per character, so anything under this floor is a
# truncated take and gets the same retries as an exception.
MIN_BYTES_PER_CHAR = 64


class ShortAudio(Exception):
    pass


def take(edge_tts, text: str, path: pathlib.Path):
    """One attempt at text -> path; a truncated take raises ShortAudio."""
    asyncio.run(edge_tts.Communicate(pronounce(text), VOICE).save(str(path)))
    size = path.stat().st_size
    if size < MIN_BYTES_PER_CHAR * len(text):
        raise ShortAudio(f"take too short: {size} bytes for {len(text)} chars")


def synth(edge_tts, text: str, out: pathlib.Path):
    """Render text to out. edge-tts creates its output file before the
    network can fail, and the dashboard shows a player whenever the mp3
    exists — so synthesize to a temp file and rename only a finished take
    into place. A failure leaves no 0-byte mp3 and keeps any earlier good one."""
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".part")
    try:
        for wait in (*RETRY_WAITS, None):
            try:
                take(edge_tts, text, tmp)
                break
            except Exception as e:
                if wait is None:
                    raise
                print(f"! tts: {type(e).__name__}: {e}; retrying in {wait}s", file=sys.stderr)
                time.sleep(wait)
        os.replace(tmp, out)
    finally:
        tmp.unlink(missing_ok=True)


# ── Wiki pages -> speech ─────────────────────────────────────────────────────
TOKEN_RE = re.compile(r"\{\{\s*[A-Za-z_][\w.]*\s*\}\}")
LIVE_NOTE = ("The live numbers on this page are left out of the audio; "
             "check the dashboard for today's values.")
SYMBOLS = [
    (r"\s*×\s*", " times "), (r"\s*−\s*", " minus "), (r"\s*→\s*", ", then "),
    (r"\s*≈\s*", " about "), (r"\s*—\s*", ", "), (r"\s+=\s+", " equals "),
    (r"\s+/\s+", " divided by "),
    (r"\s*÷\s*", " divided by "), (r"\s*≠\s*", " is not "),
]


def speak_symbols(s: str) -> str:
    for pat, word in SYMBOLS:
        s = re.sub(pat, word, s)
    return s


def _sentence(s: str) -> str:
    """Close a line with punctuation so the voice pauses between items."""
    s = s.strip()
    return s if not s or s[-1] in ".!?:;,)" else s + "."


def _cells(row: str) -> list[str]:
    return [md_to_text(c).strip().rstrip(".") for c in row.strip().strip("|").split("|")]


def wiki_to_speech(md: str) -> str:
    """Wiki markdown -> plain speakable text: admonitions read as
    "Label: title.", table rows as "Header: cell." pairs, fenced formulas
    spoken with their symbols, and live {{token}} lines left out. Hard-wrapped
    prose is joined back into paragraphs so a line break isn't read as a stop."""
    out, para, header, fence = [], [], None, None
    live_noted, fence_indent = False, 0

    def flush():
        if para:
            out.append(_sentence(md_to_text(" ".join(para))))
            para.clear()

    for line in md.split("\n"):
        if line.startswith("```"):
            flush()
            if fence is not None:
                out.extend(_sentence(t) for t in fence)
                fence = None
            else:
                fence = []
            continue
        if fence is not None:
            # A deeper-indented line continues the previous item.
            indent = len(line) - len(line.lstrip())
            if fence and line.strip() and indent > fence_indent + 2:
                fence[-1] += " " + line.strip()
            elif line.strip():
                fence.append(re.sub(r"\s{2,}", " ", line.strip()))
                fence_indent = indent
            continue
        if line.strip().startswith("|"):
            flush()
            if re.fullmatch(r"\s*\|[\s:|-]+\|\s*", line):
                continue
            if header is None:
                header = _cells(line)
                continue
            pairs = [f"{h}: {c}." for h, c in zip(header, _cells(line)) if c]
            out.append(" ".join(pairs))
            continue
        header = None
        if not line.strip() or "[[_TOC_]]" in line:
            flush()
            continue
        if TOKEN_RE.search(line):
            flush()
            if not live_noted:
                out.append(LIVE_NOTE)
                live_noted = True
            continue
        m = re.match(r"^!!!\s+(\w+)(?:\s+\"([^\"]*)\")?", line)
        if m:
            flush()
            label = m.group(1).capitalize()
            out.append(f"{label}: {m.group(2)}." if m.group(2) else f"{label}.")
            continue
        h = re.match(r"^#{1,6}\s+(.*)", line)
        if h:
            flush()
            t = md_to_text(h.group(1)).strip()
            out.append(t if t.endswith((".", "!", "?")) else t + ".")
            continue
        if re.match(r"^\s*([-+*]|\d+\.)\s", line):
            flush()  # each list item is its own sentence
        para.append(line.strip())
    flush()
    return humanize(speak_symbols("\n".join(t for t in out if t)))


def speak_wiki():
    import edge_tts
    out_dir = paper.DATA / "public" / "wiki"
    out_dir.mkdir(parents=True, exist_ok=True)
    idx_path = out_dir / "index.json"
    old = json.loads(idx_path.read_text()) if idx_path.exists() else {}
    manifest = json.loads((WIKI_CONTENT / "manifest.json").read_text())
    index, failed = {}, None
    for group in manifest:
        for item in group["items"]:
            slug, src = item["slug"], WIKI_CONTENT / f"{item['slug']}.md"
            if not src.exists():
                continue
            text = f"Kalseer wiki: {item['title']}.\n\n" + wiki_to_speech(src.read_text())
            h = hashlib.sha256(f"{VOICE}\n{pronounce(text)}".encode()).hexdigest()
            mp3 = out_dir / f"{slug}.mp3"
            if old.get(slug) == h and mp3.exists():
                index[slug] = h
                print(f"wiki {slug}: unchanged")
                continue
            try:
                synth(edge_tts, text, mp3)
                index[slug] = h
                print(f"wiki {slug}: spoke {len(text)} chars ({mp3.stat().st_size // 1024} KB)")
            except Exception as e:  # keep going; the old take stays served
                print(f"wiki {slug}: FAILED ({e})")
                if slug in old:
                    index[slug] = old[slug]
                failed = failed or e
    for stale in out_dir.glob("*.mp3"):  # pages dropped from the manifest
        if stale.stem not in index and not (WIKI_CONTENT / f"{stale.stem}.md").exists():
            stale.unlink()
    idx_path.write_text(json.dumps(index, indent=1, sort_keys=True) + "\n")
    if failed:
        raise failed


def main():
    try:
        import edge_tts
    except ImportError:
        print("edge-tts not installed — skipping spoken brief "
              "(pip install edge-tts to enable)")
        return
    if sys.argv[1:2] == ["--wiki"]:
        speak_wiki()
        return
    arg_date = sys.argv[1] if len(sys.argv) > 1 else None
    date, path = pick_brief(arg_date)
    out, chars = speak_brief(edge_tts, date, path)
    print(f"spoke {chars} chars -> {out} ({out.stat().st_size // 1024} KB, {VOICE})")
    if not arg_date:
        backfill(edge_tts, skip=date)


def brief_text(date: str, path: pathlib.Path) -> str:
    d = json.loads(path.read_text())
    # Prefer the ear-authored narrative; fall back to humanizing the
    # written one (tickers -> series names, symbols -> words).
    body = d.get("narrative_spoken") or humanize(md_to_text(d.get("narrative", "")))
    return f"Kalseer morning brief, {date}.\n\n" + body


def speak_brief(edge_tts, date: str, path: pathlib.Path):
    text = brief_text(date, path)
    out = paper.DATA / "public" / f"brief-{date}.mp3"
    synth(edge_tts, text, out)
    return out, len(text)


# The 11/12 brief was refused on all 12 whole-text tries over two days (8 on
# 11/12, 4 in the 11/13 backfill), while 11/13's brief spoke on the first try
# minutes earlier. That looks like a refusal tied to the text, not the
# service. A backfill whose whole take fails is voiced one paragraph at a
# time: edge-tts takes are bare MPEG frames, so the parts concatenate into
# one playable mp3. A paragraph still refused is left out, logged by number,
# and replaced by a spoken pointer to the written brief, so the listener
# hears that it's missing.
PART_WAITS = (5,)
SKIPPED_NOTE = ("One paragraph of this brief couldn't be voiced; "
                "the written brief has it.")


def speak_in_parts(edge_tts, date: str, path: pathlib.Path):
    paras = [p for p in brief_text(date, path).split("\n\n") if p.strip()]
    out = paper.DATA / "public" / f"brief-{date}.mp3"
    tmp = out.with_name(out.name + ".part")
    audio, skipped = [], []
    try:
        for i, para in enumerate(paras, 1):
            for wait in (*PART_WAITS, None):
                try:
                    take(edge_tts, para, tmp)
                    audio.append(tmp.read_bytes())
                    break
                except Exception as e:
                    if wait is None:
                        skipped.append(i)
                        print(f"! tts part {i}/{len(paras)}: "
                              f"{type(e).__name__}: {e} -> {para[:60]!r}",
                              file=sys.stderr)
                    else:
                        time.sleep(wait)
        if len(skipped) * 2 > len(paras):
            raise RuntimeError(f"{len(skipped)} of {len(paras)} paragraphs "
                               "refused")
        if skipped:
            take(edge_tts, SKIPPED_NOTE, tmp)
            audio.append(tmp.read_bytes())
        tmp.write_bytes(b"".join(audio))
        os.replace(tmp, out)
    finally:
        tmp.unlink(missing_ok=True)
    return out, skipped


# A take the service refused for every retry (2026-11-12: NoAudioReceived x8)
# is never re-attempted by a run for a later date, so the daily run also
# speaks recent briefs that have no mp3. Today's take decides the step; a
# failed backfill is only logged and comes up again tomorrow.
BACKFILL_DAYS = 3


def backfill(edge_tts, skip: str):
    first = (dt.date.fromisoformat(_today())
             - dt.timedelta(days=BACKFILL_DAYS)).isoformat()
    for path in sorted(paper.DATA.glob("brief-*.json")):
        date = path.stem.replace("brief-", "")
        if (date == skip or not first <= date <= _today()
                or (paper.DATA / "public" / f"brief-{date}.mp3").exists()):
            continue
        try:
            out, chars = speak_brief(edge_tts, date, path)
            print(f"backfill {date}: spoke {chars} chars "
                  f"({out.stat().st_size // 1024} KB)")
        except Exception as e:
            print(f"backfill {date}: whole take FAILED ({e}); "
                  "trying paragraph by paragraph")
            try:
                out, skipped = speak_in_parts(edge_tts, date, path)
                print(f"backfill {date}: spoke in parts "
                      f"({out.stat().st_size // 1024} KB"
                      + (f", skipped paragraph {skipped}" if skipped else "")
                      + ")")
            except Exception as e:  # keep today's ok; retried tomorrow
                print(f"backfill {date}: FAILED ({e})")


if __name__ == "__main__":
    main()
