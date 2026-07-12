// In-app wiki: raw-glob-imports markdown from src/content and renders it
// sanitized, with MkDocs-style admonitions, auto table-of-contents, stable
// heading anchors, and {{token}} fills from live dashboard stats.
import { marked } from 'marked'
import DOMPurify from 'dompurify'

const rawFiles = import.meta.glob('/src/content/**/*.md', {
  query: '?raw',
  import: 'default',
  eager: true,
})

const manifestFiles = import.meta.glob('/src/content/manifest.json', {
  eager: true,
  import: 'default',
})

/** [{id, label, items: [{slug, title}]}] */
export const manifest = Object.values(manifestFiles)[0] ?? []

export function getDocSource(slug) {
  return rawFiles[`/src/content/${slug}.md`] ?? null
}

export function titleFor(slug) {
  for (const g of manifest) for (const it of g.items) if (it.slug === slug) return it.title
  return slug
}

marked.setOptions({ gfm: true, breaks: true })

export function slugify(s) {
  return s.toLowerCase().replace(/[^\w]+/g, '-').replace(/^-+|-+$/g, '')
}

// ── Admonitions (`!!! warning "Title"` + 4-space-indented body) ──────────────
const ADMONITIONS = {
  note: { cls: 'note', icon: '✎', label: 'Note' },
  info: { cls: 'info', icon: 'ℹ', label: 'Info' },
  tip: { cls: 'tip', icon: '★', label: 'Tip' },
  important: { cls: 'tip', icon: '★', label: 'Important' },
  success: { cls: 'success', icon: '✓', label: 'Success' },
  question: { cls: 'question', icon: '?', label: 'Question' },
  warning: { cls: 'warning', icon: '⚠', label: 'Warning' },
  caution: { cls: 'warning', icon: '⚠', label: 'Caution' },
  danger: { cls: 'danger', icon: '⚡', label: 'Danger' },
  example: { cls: 'example', icon: '✎', label: 'Example' },
  quote: { cls: 'quote', icon: '“', label: 'Quote' },
}

const admonitionExtension = {
  name: 'admonition',
  level: 'block',
  start(src) {
    return src.match(/^!!![ \t]/m)?.index
  },
  tokenizer(src) {
    const rule = /^!!![ \t]+(\w+)(?:[ \t]+"([^"]*)")?[ \t]*\n((?:(?:[ ]{4}|\t).*(?:\n|$)|[ \t]*(?:\n|$))*)/
    const m = rule.exec(src)
    if (!m) return undefined
    const body = m[3].replace(/^(?:[ ]{4}|\t)/gm, '').replace(/\s+$/, '')
    const token = { type: 'admonition', raw: m[0], atype: m[1].toLowerCase(), title: m[2] ?? '', tokens: [] }
    this.lexer.blockTokens(body, token.tokens)
    return token
  },
  renderer(token) {
    const style = ADMONITIONS[token.atype] ?? ADMONITIONS.note
    const label = token.title || style.label
    const inner = this.parser.parse(token.tokens)
    return `<div class="admonition admonition-${style.cls}"><div class="admonition-title"><span aria-hidden="true">${style.icon}</span>${label}</div><div class="admonition-body">${inner}</div></div>`
  },
}
marked.use({ extensions: [admonitionExtension] })

const ID_MARKER = /\{\{#id:([\w-]+)\}\}/
const TOKEN_RE = /\{\{\s*([A-Za-z_][\w.]*)\s*\}\}/g

/** Stamp headings (outside code fences) with stable, deduped `{{#id:…}}` ids. */
function stampHeadingIds(md) {
  const used = new Map()
  const lines = md.split('\n')
  let inFence = false
  for (let i = 0; i < lines.length; i++) {
    if (/^```/.test(lines[i])) inFence = !inFence
    if (inFence) continue
    const m = /^(#{1,6})(\s+)(.+?)\s*$/.exec(lines[i])
    if (!m) continue
    const base = slugify(m[3].replace(TOKEN_RE, '$1').replace(/[`*_]/g, ''))
    const n = used.get(base) ?? 0
    used.set(base, n + 1)
    const id = n === 0 ? base : `${base}-${n}`
    lines[i] = `${m[1]}${m[2]}${m[3]} {{#id:${id}}}`
  }
  return lines.join('\n')
}

function collectHeadings(md) {
  const heads = []
  let inFence = false
  for (const line of md.split('\n')) {
    if (/^```/.test(line)) inFence = !inFence
    if (inFence) continue
    const m = /^(#{2,3})\s+(.+?)\s*$/.exec(line)
    if (!m) continue
    const idm = ID_MARKER.exec(m[2])
    const text = m[2].replace(ID_MARKER, '').replace(/[`*_]/g, '').trim()
    heads.push({ level: m[1].length, text, id: idm ? idm[1] : slugify(text) })
  }
  return heads
}

function escapeHtml(s) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
}

function tocHtml(heads) {
  if (!heads.length) return ''
  const items = heads
    .map((h) => `<li class="toc-l${h.level}"><a href="#${h.id}">${escapeHtml(h.text)}</a></li>`)
    .join('')
  return `<details class="wiki-toc" open><summary class="wiki-toc-title">Contents</summary><ul>${items}</ul></details>`
}

/** `[[_TOC_]]` replaced in place; else auto-insert before first h2/h3 when ≥3. */
function insertToc(md) {
  const heads = collectHeadings(md)
  const html = tocHtml(heads)
  if (/^[ \t]*\[\[_TOC_\]\][ \t]*$/m.test(md)) {
    return md.replace(/^[ \t]*\[\[_TOC_\]\][ \t]*$/gm, html)
  }
  if (heads.length < 3) return md
  const lines = md.split('\n')
  let inFence = false
  for (let i = 0; i < lines.length; i++) {
    if (/^```/.test(lines[i])) inFence = !inFence
    if (inFence) continue
    if (/^#{2,3}\s/.test(lines[i])) {
      lines.splice(i, 0, html, '')
      return lines.join('\n')
    }
  }
  return md
}

const headingRenderer = new marked.Renderer()
headingRenderer.heading = function ({ tokens, depth }) {
  const text = this.parser.parseInline(tokens)
  const raw = tokens.map((t) => ('raw' in t ? t.raw : '')).join('')
  const idm = ID_MARKER.exec(raw) ?? ID_MARKER.exec(text)
  const id = idm ? idm[1] : slugify(raw || text.replace(/<[^>]+>/g, ''))
  const shown = text.replace(/\s*\{\{#id:[\w-]+\}\}/, '')
  return `<h${depth} id="${id}">${shown}</h${depth}>`
}
marked.use({ renderer: headingRenderer })

/** Replace {{token}} with live values; unknown tokens render a visible ⚠. */
export function fillTokens(md, tokens) {
  return md.replace(TOKEN_RE, (full, name) =>
    Object.hasOwn(tokens, name) ? tokens[name] : `⚠${full}`,
  )
}

export function renderMarkdown(md, tokens = {}) {
  const html = marked.parse(fillTokens(insertToc(stampHeadingIds(md)), tokens), { async: false })
  return DOMPurify.sanitize(html, { ADD_ATTR: ['id', 'open', 'target'] })
}

/** Live token values from the dashboard's aggregates stats. */
export function statsTokens(stats) {
  if (!stats) return {}
  const $ = (v) => (v == null ? '—' : '$' + Number(v).toFixed(2))
  const pct = (v) => (v == null ? '—' : Math.round(v * 100) + '%')
  return {
    bankroll: $(stats.bankroll),
    equity: $(stats.equity),
    exposure: $(stats.exposure),
    starting_bankroll: $(stats.starting_bankroll),
    total_pnl: $(stats.total_pnl),
    fees_paid: $(stats.fees_paid),
    win_rate: pct(stats.win_rate),
    roi: pct(stats.roi),
    settled: String(stats.settled ?? 0),
    open_positions: String(stats.open_positions ?? 0),
  }
}
