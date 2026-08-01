<script>
  let { stats = {} } = $props()

  const fmt$ = (v) => (v == null ? '—' : '$' + Number(v).toFixed(2))
  const pct = (v) => (v == null ? '—' : Math.round(v * 100) + '%')

  const signed$ = (v) => (v == null ? '—' : (v >= 0 ? '+' : '') + fmt$(v))
  const dir = (v) => (v > 0 ? 'up' : v < 0 ? 'down' : null)

  let tiles = $derived([
    { label: 'Realized P&L', value: fmt$(stats.total_pnl), delta: dir(stats.total_pnl),
      sub: `${stats.settled ?? 0} settled` },
    { label: 'Unrealized P&L', value: signed$(stats.unrealized_pnl),
      delta: dir(stats.unrealized_pnl),
      sub: `${stats.open_positions ?? 0} open at market` },
    { label: 'Win rate', value: pct(stats.win_rate),
      sub: stats.settled ? `${stats.wins}/${stats.settled} settled` : 'no settles yet' },
    // Two denominators that used to share one ambiguous "ROI" tile and so
    // appeared to contradict the hero equity number.
    { label: 'Return on capital staked', value: pct(stats.roi_staked),
      sub: stats.staked == null ? 'settled trades' : `${fmt$(stats.staked)} staked, settled only` },
    { label: 'Return on fund', value: pct(stats.return_total),
      sub: `realized + unrealized vs ${fmt$(stats.starting_bankroll)}` },
    { label: 'At risk', value: fmt$(stats.exposure),
      sub: `${stats.open_positions ?? 0} open position${stats.open_positions === 1 ? '' : 's'} at cost` },
    { label: 'Fees paid', value: fmt$(stats.fees_paid) },
    { label: 'Brier score', value: stats.brier == null ? '—' : stats.brier.toFixed(3),
      sub: stats.brier_baseline == null
        ? 'lower = better calibrated'
        : `vs ${stats.brier_baseline.toFixed(3)} for no skill` },
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
