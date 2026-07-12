// Read the current CSS custom-property values so ECharts (canvas) can use the
// same tokens as the DOM, and re-read them when the color scheme flips.
export function readTokens() {
  const s = getComputedStyle(document.documentElement)
  const v = (name) => s.getPropertyValue(name).trim()
  return {
    surface: v('--surface-1'),
    ink: v('--ink'),
    ink2: v('--ink-2'),
    muted: v('--muted'),
    grid: v('--grid'),
    axis: v('--axis'),
    series1: v('--series-1'),
    good: v('--good'),
    critical: v('--critical'),
  }
}

export function onSchemeChange(fn) {
  const mq = window.matchMedia('(prefers-color-scheme: dark)')
  mq.addEventListener('change', fn)
  return () => mq.removeEventListener('change', fn)
}
