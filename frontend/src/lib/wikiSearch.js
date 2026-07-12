// Client-side wiki search. Every doc is glob-imported into the bundle (see
// wiki.js), so title + content search run fully in-browser. Index fills
// {{tokens}} first so live numbers match.
import { manifest, getDocSource, fillTokens } from './wiki.js'

function toPlain(md) {
  return md
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/`[^`]*`/g, ' ')
    .replace(/!\[[^\]]*\]\([^)]*\)/g, ' ')
    .replace(/\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/^\s{0,3}[#>]+\s*/gm, '')
    .replace(/^\s*\|/gm, ' ')
    .replace(/\|/g, ' ')
    .replace(/[*_~`]/g, '')
    .replace(/\s+/g, ' ')
    .trim()
}

function escapeHtml(s) {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

/** Escape + wrap case-insensitive matches of q in <mark>, entity-safe. */
function markPlain(slice, q) {
  if (!q) return escapeHtml(slice)
  const lower = slice.toLowerCase()
  let out = ''
  let pos = 0
  for (let i = lower.indexOf(q); i >= 0; i = lower.indexOf(q, i + q.length)) {
    out += escapeHtml(slice.slice(pos, i)) + `<mark>${escapeHtml(slice.slice(i, i + q.length))}</mark>`
    pos = i + q.length
  }
  return out + escapeHtml(slice.slice(pos))
}

export function buildIndex(tokens) {
  const out = []
  for (const g of manifest) {
    for (const it of g.items) {
      const src = getDocSource(it.slug)
      const plain = src ? toPlain(fillTokens(src, tokens)) : ''
      out.push({ slug: it.slug, title: it.title, group: g.label, plain, lower: plain.toLowerCase() })
    }
  }
  return out
}

const SNIPPET_BEFORE = 48
const SNIPPET_AFTER = 96

function snippetFor(entry, q) {
  const i = entry.lower.indexOf(q)
  if (i < 0) return ''
  let start = Math.max(0, i - SNIPPET_BEFORE)
  let end = Math.min(entry.plain.length, i + q.length + SNIPPET_AFTER)
  if (start > 0) {
    const sp = entry.plain.indexOf(' ', start)
    if (sp >= 0 && sp < i) start = sp + 1
  }
  if (end < entry.plain.length) {
    const sp = entry.plain.lastIndexOf(' ', end)
    if (sp > i + q.length) end = sp
  }
  const slice = entry.plain.slice(start, end)
  return (start > 0 ? '… ' : '') + markPlain(slice, q) + (end < entry.plain.length ? ' …' : '')
}

/** Title hits first (exact → prefix → substring), then content-only hits. */
export function searchIndex(index, rawQuery) {
  const q = rawQuery.trim().toLowerCase()
  if (q.length < 2) return { titles: [], content: [] }

  const exact = []
  const prefix = []
  const substr = []
  for (const e of index) {
    const t = e.title.toLowerCase()
    if (t === q) exact.push(e)
    else if (t.startsWith(q)) prefix.push(e)
    else if (t.includes(q) || e.slug.toLowerCase().includes(q)) substr.push(e)
  }
  const titleEntries = [...exact, ...prefix, ...substr]
  const titleSlugs = new Set(titleEntries.map((e) => e.slug))
  const titles = titleEntries.map((e) => ({
    slug: e.slug, title: e.title, group: e.group, titleMatch: true, snippet: snippetFor(e, q),
  }))

  const content = []
  for (const e of index) {
    if (titleSlugs.has(e.slug)) continue
    if (e.lower.includes(q)) {
      content.push({ slug: e.slug, title: e.title, group: e.group, titleMatch: false, snippet: snippetFor(e, q) })
    }
  }
  return { titles, content }
}
