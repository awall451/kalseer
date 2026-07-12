"""Render the daily brief narrative to speech: public/brief-<date>.mp3.

Uses edge-tts (Microsoft's neural voices — the same family Clipchamp
uses) via the free Edge endpoint; no API key. The dashboard shows a
speaker button only when the mp3 exists for a date, so this step is
safely optional: if edge-tts isn't installed we skip with a note.

Usage: speak.py [YYYY-MM-DD]   (defaults to today, else newest brief)
Env:   KALSEER_TTS_VOICE (default en-US-AndrewNeural)
"""

import asyncio
import datetime as dt
import json
import os
import re
import sys

import paper

VOICE = os.environ.get("KALSEER_TTS_VOICE", "en-US-AndrewNeural")


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


def main():
    try:
        import edge_tts
    except ImportError:
        print("edge-tts not installed — skipping spoken brief "
              "(pip install edge-tts to enable)")
        return
    date, path = pick_brief(sys.argv[1] if len(sys.argv) > 1 else None)
    d = json.loads(path.read_text())
    # Prefer the ear-authored narrative; fall back to humanizing the
    # written one (tickers -> series names, symbols -> words).
    body = d.get("narrative_spoken") or humanize(md_to_text(d.get("narrative", "")))
    text = f"Kalseer morning brief, {date}.\n\n" + body
    out = paper.DATA / "public" / f"brief-{date}.mp3"
    out.parent.mkdir(parents=True, exist_ok=True)
    asyncio.run(edge_tts.Communicate(text, VOICE).save(str(out)))
    print(f"spoke {len(text)} chars -> {out} ({out.stat().st_size // 1024} KB, {VOICE})")


if __name__ == "__main__":
    main()
