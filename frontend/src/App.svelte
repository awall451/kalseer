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
  const fmtSigned$ = (v) => (v < 0 ? '−$' : '+$') + Math.abs(Number(v)).toFixed(2)
  const cents = (v) => Math.round(v * 100) + '¢'
  // Tile tone: mark is quoted for OUR side, so mark above entry = winning.
  const tone = (delta) =>
    delta == null ? 'flat' : delta > 0.02 ? 'good' : delta < -0.02 ? 'bad' : 'flat'

  // Kalshi encodes one binary market per strike of a scalar event
  // (SERIES-EVENT-STRIKE). Group same-event entries so a researched
  // strike ladder reads as one event instead of near-duplicate tickers.
  function groupConsidered(list) {
    const groups = []
    const byEvent = new Map()
    for (const c of list) {
      const parts = c.ticker.split('-')
      const event = parts.length > 2 ? parts.slice(0, -1).join('-') : c.ticker
      const strike = parts.length > 2 ? parts[parts.length - 1] : ''
      if (!byEvent.has(event)) {
        const g = { event, series: parts[0], items: [] }
        byEvent.set(event, g)
        groups.push(g)
      }
      byEvent.get(event).items.push({ ...c, strike })
    }
    return groups
  }

  function seriesLabel(series) {
    const slug = slugs?.[series]
    return slug ? slug.replace(/-/g, ' ') : ''
  }

  async function getJson(path) {
    const r = await fetch(path, { cache: 'no-store' })
    if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`)
    return r.json()
  }

  // Spoken brief: the pipeline may publish brief-<date>.mp3 next to the
  // JSON (see kalshi/speak.py). Show the speaker only when it exists.
  let audioUrl = $state(null)
  let audioEl = $state(null)
  let playing = $state(false)

  async function checkAudio(date) {
    if (audioEl && !audioEl.paused) audioEl.pause()
    playing = false
    audioUrl = null
    try {
      const r = await fetch(`./data/brief-${date}.mp3`, { method: 'HEAD', cache: 'no-store' })
      if (r.ok) audioUrl = `./data/brief-${date}.mp3`
    } catch {}
  }

  function toggleAudio() {
    if (!audioEl) return
    if (audioEl.paused) audioEl.play()
    else audioEl.pause()
  }

  async function loadBrief(date) {
    selected = date
    // Date picks never persist into the URL — a refresh always lands on
    // the newest brief. (#/<date> still works as a one-shot deep link;
    // it's cleaned here after loading.)
    if (/^#\/?\d{4}-\d{2}-\d{2}$/.test(location.hash)) {
      history.replaceState(null, '', location.pathname + location.search)
    }
    checkAudio(date)
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
      await loadBrief(dates[0])
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
      <div class="brief-controls">
        {#if audioUrl}
          <button class="speak" onclick={toggleAudio} title={playing ? 'Pause' : 'Read the brief aloud'}
                  aria-label={playing ? 'Pause spoken brief' : 'Play spoken brief'}>
            {playing ? '⏸' : '🔊'}
          </button>
          <audio bind:this={audioEl} src={audioUrl} preload="none"
                 onended={() => (playing = false)} onpause={() => (playing = false)}
                 onplay={() => (playing = true)}></audio>
        {/if}
        <select
          value={selected}
          onchange={(e) => loadBrief(e.currentTarget.value)}
          aria-label="Brief date"
        >
          {#each dates as d}
            <option value={d}>{d}</option>
          {/each}
        </select>
      </div>
    </section>

    {#if brief && !brief.missing}
      {@const showLive = selected === dates[0] && agg?.open_positions?.length}
      {#if showLive || brief.trades_settled?.length}
        <section class="pos-grid">
          {#each brief.trades_settled ?? [] as t}
            <a class="pos-tile {t.won ? 'good' : 'bad'}" href={marketUrl(t.ticker, slugs)}
               target="_blank" rel="noopener">
              <div class="pos-title">{t.title || t.ticker}</div>
              <div class="pos-line">
                <span class="mono side">{(t.side ?? '').toUpperCase()}</span>
                <span class="chipw {t.won ? 'win' : 'loss'}">{t.won ? 'WIN' : 'LOSS'}</span>
                <span class="mono">{fmtSigned$(t.pnl)}</span>
              </div>
              <div class="muted pos-sub">settled {selected}</div>
            </a>
          {/each}
          {#if showLive}
            {#each agg.open_positions as p}
              {@const delta = p.mark != null ? p.mark - p.entry_price : null}
              {@const day = p.mark != null && p.mark_prev != null ? p.mark - p.mark_prev : null}
              <a class="pos-tile {tone(delta)}" href={marketUrl(p.ticker, slugs)}
                 target="_blank" rel="noopener">
                <div class="pos-title">{p.title || p.ticker}</div>
                <div class="pos-line">
                  <span class="mono side">{p.side.toUpperCase()}</span>
                  <span class="mono">{cents(p.entry_price)} → {p.mark != null ? cents(p.mark) : '—'}</span>
                  {#if day != null}
                    <span class="pos-arrow">{day > 0.005 ? '↑' : day < -0.005 ? '↓' : '→'}</span>
                  {/if}
                </div>
                <div class="muted pos-sub">
                  {#if delta != null}
                    {delta >= 0 ? '+' : '−'}{Math.abs(Math.round(delta * 100))}¢ vs entry ·
                    {fmtSigned$(delta * p.contracts)} at market
                  {:else}
                    no market mark yet
                  {/if}
                </div>
              </a>
            {/each}
          {/if}
        </section>
      {/if}

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
          {#each groupConsidered(brief.considered_but_passed) as g}
            {#if g.items.length > 1}
              <div class="passed-group">
                <div class="passed-head">
                  <a class="mono" href={marketUrl(g.items[0].ticker, slugs)} target="_blank"
                     rel="noopener">{g.event} ↗</a>
                  {#if seriesLabel(g.series)}
                    <span class="muted">{seriesLabel(g.series)} — one market per strike</span>
                  {/if}
                </div>
                {#each g.items as c}
                  <div class="passed strike-row">
                    <span class="mono strike">{c.strike}</span>
                    <span class="ink2">{c.why}</span>
                  </div>
                {/each}
              </div>
            {:else}
              <div class="passed">
                <div class="passed-head">
                  <a class="mono" href={marketUrl(g.items[0].ticker, slugs)} target="_blank"
                     rel="noopener">{g.items[0].ticker} ↗</a>
                  {#if seriesLabel(g.series)}
                    <span class="muted">{seriesLabel(g.series)}</span>
                  {/if}
                </div>
                <div class="ink2 passed-why">{g.items[0].why}</div>
              </div>
            {/if}
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
  .brief-controls { display: flex; align-items: center; gap: 10px; }
  .speak {
    background: var(--chip);
    color: var(--ink);
    border: 1px solid var(--border);
    border-radius: 7px;
    font-size: 16px;
    line-height: 1;
    padding: 6px 10px;
    cursor: pointer;
  }
  .speak:hover { border-color: var(--series-1); }
  select {
    background: var(--surface-1); color: var(--ink);
    border: 1px solid var(--border); border-radius: 8px;
    padding: 6px 10px; font-size: 14px; font-family: inherit;
  }
  .narrative :global(p) { margin: 0 0 12px; }
  .narrative :global(p:last-child) { margin-bottom: 0; }
  .sect { font-size: 15px; margin: 22px 0 4px; }
  .pos-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
    gap: 10px;
    margin-bottom: 12px;
  }
  .pos-tile {
    display: block;
    background: var(--surface-1);
    border: 1px solid var(--border);
    border-left: 3px solid var(--muted);
    border-radius: 9px;
    padding: 10px 12px;
    color: inherit;
    text-decoration: none;
  }
  .pos-tile.good { border-left-color: var(--good); }
  .pos-tile.bad { border-left-color: var(--critical); }
  .pos-tile.flat { border-left-color: var(--warning); }
  .pos-title {
    font-weight: 600;
    font-size: 13.5px;
    margin-bottom: 5px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .pos-line { display: flex; gap: 10px; align-items: baseline; }
  .pos-arrow { font-size: 15px; }
  .pos-sub { font-size: 12px; margin-top: 4px; }
  .side { color: var(--ink-2); }
  .chipw { border-radius: 5px; padding: 1px 7px; font-size: 12px; font-weight: 650; }
  .chipw.win { background: var(--series-1-soft); color: var(--good-text); }
  .chipw.loss { background: var(--series-1-soft); color: var(--critical); }
  .passed { padding: 6px 0; }
  .passed-group { padding: 6px 0; }
  .passed-head { display: flex; gap: 12px; align-items: baseline; flex-wrap: wrap; }
  .passed-why { margin-top: 2px; }
  /* chip column stays put; reasoning wraps within its own column */
  .strike-row {
    display: flex;
    gap: 12px;
    align-items: baseline;
    margin-left: 18px;
    padding: 4px 0;
  }
  .strike {
    background: var(--chip);
    border-radius: 5px;
    padding: 1px 7px;
    white-space: nowrap;
    flex-shrink: 0;
  }
  .sources { font-size: 12.5px; margin-top: 14px; }
</style>
