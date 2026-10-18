<script>
  // Shadow execution (kalshi/shadow.py): the limit order a live executor
  // would have sent for each paper trade, scored against the real order book.
  // Nothing is ever sent. Hidden until the pipeline publishes shadow.json.
  import { onMount } from 'svelte'
  import { marketUrl } from './kalshiUrl.js'

  let { slugs = {} } = $props()
  let data = $state(null)

  onMount(async () => {
    try {
      const r = await fetch('./data/shadow.json', { cache: 'no-store' })
      if (r.ok) data = await r.json()
    } catch {}
  })

  const cents = (v) => (v == null ? '—' : Math.round(Number(v) * 100) + '¢')
  const signed$ = (v) => (v < 0 ? '−$' : '+$') + Math.abs(Number(v)).toFixed(2)
  const day = (iso) =>
    new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
  const STATUS = {
    filled: 'filled',
    partial: 'part filled, rest resting',
    resting: 'resting, nothing filled',
    expired: 'expired unfilled',
    error: 'book read failed',
  }

  let s = $derived(data?.summary)
  let recent = $derived((data?.orders ?? []).slice(0, 8))
</script>

{#if s && s.orders}
  <section class="shadow card">
    <div class="head">
      <h3>Shadow execution <span class="muted tag">no money — nothing is sent</span></h3>
    </div>
    <p class="muted lede">
      Each paper trade is also built as the real limit order and checked against Kalshi's live
      order book: did it actually fill, and at what price?
    </p>
    <div class="stats">
      <div><span class="big mono">{Math.round(s.fill_rate * 100)}%</span>
        <span class="muted">filled ({s.filled} of {s.requested} contracts)</span></div>
      <div><span class="big mono">{s.orders}</span><span class="muted">shadow orders</span></div>
      {#if s.settled.length}
        <div><span class="big mono">{signed$(s.shadow_pnl)}</span>
          <span class="muted">shadow P&L vs paper {signed$(s.paper_pnl)} (settled)</span></div>
      {/if}
    </div>
    <div class="rows">
      {#each recent as o}
        <a class="row" href={marketUrl(o.ticker, slugs)} target="_blank" rel="noopener">
          <span class="muted">{day(o.created)}</span>
          <span class="mono tick">{o.ticker}</span>
          <span class="mono">{o.order.action.toUpperCase()} {o.side.toUpperCase()}
            {o.count} @ {cents(o.paper_price)}</span>
          <span class="mono">{o.filled_now + o.filled_later}/{o.count}
            {#if o.vwap_now != null}<span class="muted">vwap {cents(o.vwap_now)}</span>{/if}</span>
          <span class="st st-{o.status}">{STATUS[o.status] ?? o.status}</span>
        </a>
      {/each}
    </div>
  </section>
{/if}

<style>
  .shadow { margin-top: 14px; padding: 14px 16px; }
  .head h3 { font-size: 14px; margin: 0 0 4px; }
  .tag { font-size: 12px; font-weight: 400; margin-left: 6px; }
  .lede { font-size: 13px; margin: 0 0 10px; }
  .stats { display: flex; flex-wrap: wrap; gap: 8px 28px; margin-bottom: 10px; }
  .stats > div { display: grid; }
  .big { font-size: 20px; font-weight: 700; }
  .stats .muted { font-size: 12px; }
  .rows { display: grid; gap: 2px; }
  .row {
    display: grid;
    grid-template-columns: 56px minmax(0, 1.4fr) minmax(0, 1fr) minmax(0, 0.9fr) minmax(0, 1fr);
    gap: 10px;
    align-items: baseline;
    padding: 6px 4px;
    border-top: 1px solid var(--border);
    color: inherit;
    text-decoration: none;
    font-size: 13px;
  }
  .row:hover { background: var(--chip); }
  .tick { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .st { font-size: 12px; }
  .st-filled { color: var(--good-text); }
  .st-partial, .st-resting { color: var(--ink-2); }
  .st-expired, .st-error { color: var(--critical); }
  @media (max-width: 640px) {
    .row { grid-template-columns: 48px 1fr; }
    .row > :nth-child(n + 3) { grid-column: 2; }
  }
</style>
