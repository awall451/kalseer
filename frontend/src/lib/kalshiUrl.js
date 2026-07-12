// kalshi.com deep link: /markets/<series>/<series-slug>/<event-ticker>
// Ticker anatomy: SERIES-EVENT...-STRIKE (strike segment dropped for the event
// ticker). Falls back to the series page when the slug isn't known.
export function marketUrl(ticker, slugs = {}) {
  if (!ticker) return 'https://kalshi.com/markets'
  const parts = ticker.split('-')
  const series = parts[0]
  const event = parts.length > 2 ? parts.slice(0, -1).join('-') : ticker
  const slug = slugs[series]
  const base = `https://kalshi.com/markets/${series.toLowerCase()}`
  return slug ? `${base}/${slug}/${event.toLowerCase()}` : base
}
