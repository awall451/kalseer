<script>
  import { onMount } from 'svelte'
  import StatTiles from './lib/StatTiles.svelte'
  import EquityChart from './lib/EquityChart.svelte'
  import CalibrationChart from './lib/CalibrationChart.svelte'
  import TradeCard from './lib/TradeCard.svelte'
  import Wiki from './lib/Wiki.svelte'
  import { renderMd } from './lib/md.js'
  import { marketUrl } from './lib/kalshiUrl.js'

  let dates = $state([])
  let slugs = $state({})
  let agg = $state(null)
  let status = $state(null)
  let brief = $state(null)
  let selected = $state(null)
  let loadError = $state(null)
  let view = $state('brief') // 'brief' | 'wiki'
  let wikiSlug = $state('kalshi-101')

  function routeFromHash() {
    const h = location.hash.replace(/^#\/?/, '')
    if (h.startsWith('wiki')) {
      view = 'wiki'
      const s = h.replace(/^wiki\/?/, '')
      if (s) wikiSlug = s
    } else if (h === '' || /^\d{4}-\d{2}-\d{2}$/.test(h)) {
      view = 'brief'
      if (dates.includes(h) && h !== selected) loadBrief(h)
    }
    // anything else is an in-page heading anchor — leave the view alone
  }

  const fmt$ = (v) => '$' + Number(v).toFixed(2)

  async function getJson(path) {
    const r = await fetch(path, { cache: 'no-store' })
    if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`)
    return r.json()
  }

  async function loadBrief(date, updateHash = true) {
    selected = date
    if (updateHash) location.hash = `#/${date}`
    brief = null
    try {
      brief = await getJson(`./data/brief-${date}.json`)
    } catch {
      brief = { missing: true, date }
    }
  }

  let staleHours = $derived.by(() => {
    if (!status?.last_success) return null
    return (Date.now() - new Date(status.last_success).getTime()) / 3.6e6
  })

  onMount(async () => {
    try {
      const m = await getJson('./data/manifest.json')
      dates = m.dates
      agg = await getJson('./data/aggregates.json')
    } catch (e) {
      loadError = String(e)
      return
    }
    try {
      status = await getJson('./data/status.json')
    } catch {
      status = null // first run: daily.sh hasn't written one yet
    }
    try {
      slugs = await getJson('./data/series.json')
    } catch {
      slugs = {}
    }
    const fromHash = location.hash.replace(/^#\//, '')
    if (fromHash.startsWith('wiki')) {
      await loadBrief(dates[0], false)
      routeFromHash()
    } else {
      await loadBrief(dates.includes(fromHash) ? fromHash : dates[0])
    }
    window.addEventListener('hashchange', routeFromHash)
  })
</script>

<div class="wrap">
  <header>
    <div>
      <h1>Kalseer</h1>
      <div class="muted subtitle">Kalshi paper trading · Claude researches, hard caps enforce discipline</div>
    </div>
    {#if agg}
      <div class="hero">
        <div class="hero-label ink2">Equity</div>
        <div class="hero-value">{fmt$(agg.stats.equity)}</div>
        <div class="hero-sub muted">
          {fmt$(agg.stats.bankroll)} cash · started {fmt$(agg.stats.starting_bankroll)}
        </div>
      </div>
    {/if}
  </header>

  {#if status && status.ok === false}
    <div class="banner bad">
      ⚠ Morning run failed at step: <b>{status.failed_step}</b>
      ({new Date(status.finished_at).toLocaleString()}) — data below may be stale.
    </div>
  {:else if staleHours != null && staleHours > 36}
    <div class="banner stale">
      ◌ Last successful run was {Math.round(staleHours)}h ago — data may be stale.
    </div>
  {/if}

  <nav class="tabs" aria-label="Views">
    <a class="tab" class:active={view === 'brief'} href={`#/${selected ?? ''}`}>Brief</a>
    <a class="tab" class:active={view === 'wiki'} href={`#/wiki/${wikiSlug}`}>Wiki</a>
  </nav>

  {#if loadError}
    <div class="banner bad">Failed to load dashboard data: {loadError}</div>
  {:else if view === 'wiki'}
    <Wiki slug={wikiSlug} stats={agg?.stats} />
  {:else if agg}
    <StatTiles stats={agg.stats} />

    <div class="charts">
      <section class="card">
        <h3>Equity over time</h3>
        <EquityChart curve={agg.equity_curve} />
      </section>
      <section class="card">
        <h3>Calibration — said vs happened</h3>
        <CalibrationChart calibration={agg.calibration} />
      </section>
    </div>

    <section class="brief-head">
      <h2>Daily brief</h2>
      <select
        value={selected}
        onchange={(e) => loadBrief(e.currentTarget.value)}
        aria-label="Brief date"
      >
        {#each dates as d}
          <option value={d}>{d}</option>
        {/each}
      </select>
    </section>

    {#if brief && !brief.missing}
      <section class="card narrative">
        {@html renderMd(brief.narrative)}
      </section>

      {#if brief.trades_opened?.length}
        <h3 class="sect">Opened ({brief.trades_opened.length})</h3>
        {#each brief.trades_opened as t}
          <TradeCard trade={t} {slugs} />
        {/each}
      {/if}

      {#if brief.trades_settled?.length}
        <h3 class="sect">Settled</h3>
        {#each brief.trades_settled as t}
          <TradeCard trade={{ ...t, result: t.result ?? 'settled' }} {slugs} />
        {/each}
      {/if}

      {#if brief.considered_but_passed?.length}
        <h3 class="sect">Considered, passed</h3>
        <div class="card">
          {#each brief.considered_but_passed as c}
            <div class="passed">
              <a class="mono" href={marketUrl(c.ticker, slugs)} target="_blank"
                 rel="noopener">{c.ticker} ↗</a>
              <span class="ink2">{c.why}</span>
            </div>
          {/each}
        </div>
      {/if}

      {#if brief.sources_checked?.length}
        <div class="muted sources">Sources: {brief.sources_checked.join(' · ')}</div>
      {/if}
    {:else if brief?.missing}
      <div class="card muted">No brief file for {brief.date}.</div>
    {/if}

    {#if agg.open_positions?.length}
      <h3 class="sect">All open positions</h3>
      {#each agg.open_positions as t}
        <TradeCard trade={t} {slugs} />
      {/each}
    {/if}
  {:else}
    <div class="muted">Loading…</div>
  {/if}
</div>

<style>
  header {
    display: flex; justify-content: space-between; align-items: flex-start;
    gap: 16px; margin-bottom: 18px; flex-wrap: wrap;
  }
  .subtitle { font-size: 13px; margin-top: 3px; }
  .hero { text-align: right; }
  .hero-label { font-size: 12.5px; }
  .hero-value { font-size: 48px; font-weight: 700; line-height: 1.1; }
  .hero-sub { font-size: 12.5px; }

  .banner {
    padding: 10px 14px; border-radius: 8px; margin-bottom: 14px;
    font-size: 14px; border: 1px solid var(--border);
  }
  .banner.bad { background: rgba(208, 59, 59, 0.12); color: var(--ink); }
  .banner.stale { background: var(--chip); color: var(--ink-2); }

  .tabs {
    display: flex; gap: 4px; margin-bottom: 16px;
    border-bottom: 1px solid var(--border); padding-bottom: 0;
  }
  .tab {
    padding: 7px 16px; font-size: 14px; font-weight: 600;
    color: var(--ink-2); text-decoration: none;
    border-bottom: 2px solid transparent; margin-bottom: -1px;
  }
  .tab:hover { color: var(--ink); }
  .tab.active { color: var(--series-1); border-bottom-color: var(--series-1); }

  .charts {
    display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 12px;
  }
  @media (max-width: 760px) { .charts { grid-template-columns: 1fr; } }
  .charts h3 { font-size: 14px; margin-bottom: 6px; }

  .brief-head {
    display: flex; align-items: center; justify-content: space-between;
    margin: 26px 0 10px;
  }
  select {
    background: var(--surface-1); color: var(--ink);
    border: 1px solid var(--border); border-radius: 8px;
    padding: 6px 10px; font-size: 14px; font-family: inherit;
  }
  .narrative :global(p) { margin: 0 0 12px; }
  .narrative :global(p:last-child) { margin-bottom: 0; }
  .sect { font-size: 15px; margin: 22px 0 4px; }
  .passed { display: flex; gap: 12px; padding: 6px 0; flex-wrap: wrap; }
  .sources { font-size: 12.5px; margin-top: 14px; }
</style>
