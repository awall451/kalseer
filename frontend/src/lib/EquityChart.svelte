<script>
  import Chart from './Chart.svelte'

  let { curve = [] } = $props()

  const fmt$ = (v) => '$' + Number(v).toFixed(2)

  function buildOption(t) {
    const data = curve.map((p) => [p.t, p.equity, p.label, p.pnl])
    return {
      backgroundColor: 'transparent',
      grid: { left: 56, right: 20, top: 18, bottom: 28 },
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'line', lineStyle: { color: t.axis, width: 1 } },
        backgroundColor: t.surface,
        borderColor: t.grid,
        textStyle: { color: t.ink, fontSize: 12 },
        formatter: (params) => {
          const [time, equity, label, pnl] = params[0].data
          const when = time ? new Date(time).toLocaleString() : ''
          const pnlLine =
            pnl == null ? '' : `<br/>trade P&amp;L: ${pnl >= 0 ? '+' : ''}${fmt$(pnl)}`
          return `<b>${fmt$(equity)}</b> equity<br/>` +
                 `<span style="opacity:.75">${label}</span>${pnlLine}<br/>` +
                 `<span style="opacity:.6">${when}</span>`
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
          type: 'line',
          data,
          lineStyle: { width: 2, color: t.series1, cap: 'round', join: 'round' },
          itemStyle: {
            color: t.series1,
            borderColor: t.surface, // 2px surface ring on markers
            borderWidth: 2,
          },
          symbol: 'circle',
          symbolSize: 8,
          areaStyle: { color: t.series1, opacity: 0.1 },
          emphasis: { scale: 1.4 },
        },
      ],
    }
  }
</script>

<Chart {buildOption} height={240} />
