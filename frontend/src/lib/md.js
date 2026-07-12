// Minimal markdown for brief narratives: paragraphs, **bold**, *em*, `code`.
export function renderMd(src) {
  const esc = (s) =>
    s.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')
  return esc(src || '')
    .split(/\n\s*\n/)
    .map((p) =>
      `<p>${p
        .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
        .replace(/\*(.+?)\*/g, '<em>$1</em>')
        .replace(/`(.+?)`/g, '<code>$1</code>')
        .replace(/\n/g, '<br/>')}</p>`,
    )
    .join('')
}
