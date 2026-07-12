<script>
  let { stats = {} } = $props()

  const fmt$ = (v) => (v == null ? '—' : '$' + Number(v).toFixed(2))
  const pct = (v) => (v == null ? '—' : Math.round(v * 100) + '%')

  let tiles = $derived([
    { label: 'Total P&L', value: fmt$(stats.total_pnl),
      delta: stats.total_pnl > 0 ? 'up' : stats.total_pnl < 0 ? 'down' : null },
    { label: 'Win rate', value: pct(stats.win_rate),
      sub: stats.settled ? `${stats.wins}/${stats.settled} settled` : 'no settles yet' },
    { label: 'ROI after fees', value: pct(stats.roi) },
    { label: 'At risk', value: fmt$(stats.exposure),
      sub: `${stats.open_positions ?? 0} open position${stats.open_positions === 1 ? '' : 's'}` },
    { label: 'Fees paid', value: fmt$(stats.fees_paid) },
    { label: 'Brier score', value: stats.brier == null ? '—' : stats.brier.toFixed(3),
      sub: 'lower = better calibrated' },
  ])
</script>

<div class="tiles">
  {#each tiles as t}
    <div class="tile card">
      <div class="label">{t.label}</div>
      <div class="value" class:up={t.delta === 'up'} class:down={t.delta === 'down'}>
        {t.value}
      </div>
      {#if t.sub}<div class="sub muted">{t.sub}</div>{/if}
    </div>
  {/each}
</div>

<style>
  .tiles {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
    gap: 12px;
  }
  .tile { padding: 14px 16px; }
  .label { font-size: 12.5px; color: var(--ink-2); }
  .value { font-size: 26px; font-weight: 650; margin-top: 2px; }
  .value.up { color: var(--good-text); }
  .value.down { color: var(--critical); }
  .sub { font-size: 12px; margin-top: 2px; }
</style>
