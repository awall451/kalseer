<script>
  import Chart from './Chart.svelte'

  let { curve = [] } = $props()

  const fmt$ = (v) => '$' + Number(v).toFixed(2)
  const signed$ = (v) => (v >= 0 ? '+' : '') + fmt$(v)

  // Days where something settled — worth a marker, since the line now moves
  // for two different reasons (a settlement, or the book repricing).
  let settleDays = $derived(curve.filter((p) => p.events?.length))

  function buildOption(t) {
    const data = curve.map((p) => [p.t, p.equity, p])
    const cash = curve.map((p) => [p.t, p.cash])
    return {
      backgroundColor: 'transparent',
      grid: { left: 56, right: 20, top: 34, bottom: 28 },
      legend: {
        top: 0,
        left: 0,
        icon: 'circle',
        itemWidth: 10,
        textStyle: { color: t.ink2, fontSize: 12 },
        data: ['Equity (marked to market)', 'Cash'],
      },
      tooltip: {
        trigger: 'axis',
        // keep the tooltip inside the chart box — near the edges ECharts
        // flips it to the other side of the cursor instead of clipping
        confine: true,
        axisPointer: { type: 'line', lineStyle: { color: t.axis, width: 1 } },
        backgroundColor: t.surface,
        borderColor: t.grid,
        textStyle: { color: t.ink, fontSize: 12 },
        formatter: (params) => {
          const row = params.find((p) => p.data?.[2])?.data?.[2]
          if (!row) return ''
          const when = new Date(row.t).toLocaleDateString()
          const evts = (row.events ?? [])
            .map(
              (e) =>
                `<br/><span style="opacity:.75">settled ${e.title || e.ticker}</span> ` +
                `<b>${signed$(e.pnl)}</b>`,
            )
            .join('')
          return (
            `<b>${fmt$(row.equity)}</b> equity<br/>` +
            `<span style="opacity:.6">${when}</span><br/>` +
            `cash ${fmt$(row.cash)} · ${row.open_n} open<br/>` +
            `realized ${signed$(row.realized)} · unrealized ${signed$(row.unrealized)}` +
            evts
          )
        },
      },
      xAxis: {
        type: 'time',
        axisLine: { lineStyle: { color: t.axis } },
        axisTick: { show: false },
        axisLabel: { color: t.muted, fontSize: 11, hideOverlap: true },
        splitLine: { show: false },
      },
      yAxis: {
        type: 'value',
        scale: true,
        axisLabel: { color: t.muted, fontSize: 11, formatter: (v) => '$' + v },
        splitLine: { lineStyle: { color: t.grid, width: 1, type: 'solid' } },
      },
      series: [
        {
          name: 'Equity (marked to market)',
          type: 'line',
          data,
          lineStyle: { width: 2, color: t.series1, cap: 'round', join: 'round' },
          itemStyle: { color: t.series1 },
          symbol: 'circle',
          symbolSize: 4,
          areaStyle: { color: t.series1, opacity: 0.1 },
          emphasis: { scale: 2 },
          markPoint: {
            symbol: 'pin',
            symbolSize: 28,
            silent: true,
            data: settleDays.map((p) => {
              const net = p.events.reduce((s, e) => s + e.pnl, 0)
              return {
                coord: [p.t, p.equity],
                value: net >= 0 ? '+' : '−',
                itemStyle: { color: net >= 0 ? t.good : t.critical },
              }
            }),
            label: { color: t.surface, fontSize: 12, fontWeight: 700 },
          },
        },
        {
          name: 'Cash',
          type: 'line',
          data: cash,
          lineStyle: { width: 1.5, color: t.ink2, type: 'dashed' },
          itemStyle: { color: t.ink2 },
          symbol: 'none',
          emphasis: { disabled: true },
        },
      ],
    }
  }
</script>

{#if curve.length === 0}
  <div class="empty muted">No trades yet — the curve starts with the first position.</div>
{:else}
  <Chart {buildOption} height={240} />
  <p class="note muted">
    Open positions are valued at the last market quote, not at cost. Pins mark days
    something settled.
  </p>
{/if}

<style>
  .empty {
    height: 240px;
    display: grid;
    place-items: center;
    font-size: 14px;
  }
  .note {
    margin: 8px 0 0;
    font-size: 12px;
  }
</style>
