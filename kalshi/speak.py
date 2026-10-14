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

import paper

VOICE = os.environ.get("KALSEER_TTS_VOICE", "en-US-AndrewNeural")
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


def pick_brief(arg_date: str | None):
    if arg_date:
        p = paper.DATA / f"brief-{arg_date}.json"
        return (arg_date, p) if p.exists() else sys.exit(f"no brief for {arg_date}")
    today = dt.date.today().isoformat()
    p = paper.DATA / f"brief-{today}.json"
    if p.exists():
        return today, p
    briefs = sorted(paper.DATA.glob("brief-*.json"))
    if not briefs:
        sys.exit("no briefs exist yet")
    newest = briefs[-1]
    return newest.stem.replace("brief-", ""), newest


def synth(edge_tts, text: str, out: pathlib.Path):
    """Render text to out. edge-tts creates its output file before the
    network can fail, and the dashboard shows a player whenever the mp3
    exists — so synthesize to a temp file and rename only a finished take
    into place. A failure leaves no 0-byte mp3 and keeps any earlier good one."""
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".part")
    try:
        asyncio.run(edge_tts.Communicate(text, VOICE).save(str(tmp)))
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
            h = hashlib.sha256(f"{VOICE}\n{text}".encode()).hexdigest()
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
    date, path = pick_brief(sys.argv[1] if len(sys.argv) > 1 else None)
    d = json.loads(path.read_text())
    # Prefer the ear-authored narrative; fall back to humanizing the
    # written one (tickers -> series names, symbols -> words).
    body = d.get("narrative_spoken") or humanize(md_to_text(d.get("narrative", "")))
    text = f"Kalseer morning brief, {date}.\n\n" + body
    out = paper.DATA / "public" / f"brief-{date}.mp3"
    synth(edge_tts, text, out)
    print(f"spoke {len(text)} chars -> {out} ({out.stat().st_size // 1024} KB, {VOICE})")


if __name__ == "__main__":
    main()
