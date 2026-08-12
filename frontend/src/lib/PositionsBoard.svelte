<script>
  import { marketUrl } from './kalshiUrl.js'

  let { open = [], settled = [], slugs = {} } = $props()

  const cents = (v) => Math.round(v * 100) + '¢'
  const fmtSigned$ = (v) => (v < 0 ? '−$' : '+$') + Math.abs(Number(v)).toFixed(2)
  const day = (iso) =>
    iso ? new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) : null
  // Tile tone: mark is quoted for OUR side, so mark above entry = winning.
  const tone = (delta) =>
    delta == null ? 'flat' : delta > 0.02 ? 'good' : delta < -0.02 ? 'bad' : 'flat'

  let recent = $derived(settled.slice(0, 8))
</script>

<section class="board">
  <div class="board-head">
    <h3>Open positions {open.length ? `(${open.length})` : ''}</h3>
  </div>
  {#if open.length}
    <div class="grid">
      {#each open as p}
        {@const delta = p.mark != null ? p.mark - p.entry_price : null}
        {@const dayMove = p.mark != null && p.mark_prev != null ? p.mark - p.mark_prev : null}
        <a class="tile {tone(delta)}" href={marketUrl(p.ticker, slugs)} target="_blank"
           rel="noopener">
          <div class="title">{p.title || p.ticker}</div>
          <div class="line">
            <span class="mono side">{p.side.toUpperCase()}</span>
            <span class="mono">{cents(p.entry_price)} → {p.mark != null ? cents(p.mark) : '—'}</span>
            {#if dayMove != null}
              <span class="arrow">{dayMove > 0.005 ? '↑' : dayMove < -0.005 ? '↓' : '→'}</span>
            {/if}
            {#if delta != null}
              <span class="mono pnl {delta >= 0 ? 'up' : 'down'}">{fmtSigned$(delta * p.contracts)}</span>
            {/if}
          </div>
          <div class="muted sub">
            opened {day(p.opened)}{#if p.closes}&nbsp;· resolves {day(p.closes)}{/if}
            · {p.contracts}x · said {Math.round(p.fair_value * 100)}%
          </div>
        </a>
      {/each}
    </div>
  {:else}
    <div class="muted empty">Nothing in play — all cash, waiting for an edge.</div>
  {/if}

  {#if recent.length}
    <div class="board-head settled-head">
      <h3>Recently settled</h3>
    </div>
    <div class="rows card">
      {#each recent as t}
        <a class="row" href={marketUrl(t.ticker, slugs)} target="_blank" rel="noopener">
          <span class="chipw {t.won ? 'win' : 'loss'}">{t.won ? 'WIN' : 'LOSS'}</span>
          <span class="row-title">{t.title || t.ticker}</span>
          <span class="mono side">{(t.side ?? '').toUpperCase()}</span>
          <span class="mono pnl {t.pnl >= 0 ? 'up' : 'down'}">{fmtSigned$(t.pnl)}</span>
          <span class="muted mono when">{day(t.settled)}</span>
        </a>
      {/each}
    </div>
  {/if}
</section>

<style>
  .board { margin-top: 12px; }
  .board-head h3 { font-size: 14px; margin-bottom: 6px; }
  .settled-head { margin-top: 14px; }
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
    gap: 10px;
  }
  .tile {
    display: block;
    background: var(--surface-1);
    border: 1px solid var(--border);
    border-left: 3px solid var(--muted);
    border-radius: 9px;
    padding: 10px 12px;
    color: inherit;
    text-decoration: none;
  }
  .tile.good { border-left-color: var(--good); }
  .tile.bad { border-left-color: var(--critical); }
  .tile.flat { border-left-color: var(--warning); }
  .title { font-weight: 600; font-size: 13.5px; margin-bottom: 5px; }
  .line { display: flex; gap: 10px; align-items: baseline; flex-wrap: wrap; }
  .arrow { font-size: 15px; }
  .sub { font-size: 12px; margin-top: 4px; }
  .side { color: var(--ink-2); font-size: 12.5px; }
  .pnl.up { color: var(--good-text); }
  .pnl.down { color: var(--critical); }
  .empty {
    font-size: 13.5px;
    padding: 12px 14px;
    background: var(--surface-1);
    border: 1px dashed var(--border);
    border-radius: 9px;
  }
  .rows { padding: 4px 12px; }
  .row {
    display: flex;
    gap: 12px;
    align-items: baseline;
    padding: 7px 0;
    color: inherit;
    text-decoration: none;
    border-bottom: 1px solid var(--border);
    font-size: 13.5px;
  }
  .row:last-child { border-bottom: none; }
  .row:hover .row-title { color: var(--series-1); }
  .row-title {
    font-weight: 600;
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .chipw {
    border-radius: 5px; padding: 1px 7px; font-size: 11.5px; font-weight: 650;
    flex-shrink: 0; width: 40px; text-align: center;
  }
  .chipw.win { background: var(--series-1-soft); color: var(--good-text); }
  .chipw.loss { background: var(--series-1-soft); color: var(--critical); }
  .when { font-size: 12px; flex-shrink: 0; }
  @media (max-width: 560px) {
    .row { flex-wrap: wrap; }
    .row-title { flex-basis: 100%; white-space: normal; }
  }
</style>
