<script>
  import Chart from './Chart.svelte'

  let { calibration = [] } = $props()

  const pct = (v) => Math.round(v * 100) + '%'

  function buildOption(t) {
    const cats = calibration.map((b) => `${pct(b.lo)}–${pct(b.hi)}`)
    return {
      backgroundColor: 'transparent',
      grid: { left: 46, right: 20, top: 44, bottom: 28 },
      legend: {
        top: 4,
        left: 0,
        icon: 'circle',
        itemWidth: 10,
        textStyle: { color: t.ink2, fontSize: 12 },
        data: ['Actual win rate', 'Predicted (avg)'],
      },
      tooltip: {
        trigger: 'axis',
        backgroundColor: t.surface,
        borderColor: t.grid,
        textStyle: { color: t.ink, fontSize: 12 },
        formatter: (params) => {
          const i = params[0].dataIndex
          const b = calibration[i]
          return `<b>said ${pct(b.lo)}–${pct(b.hi)}</b> (n=${b.n})<br/>` +
                 `happened: <b>${pct(b.actual)}</b><br/>predicted avg: ${pct(b.predicted)}`
        },
      },
      xAxis: {
        type: 'category',
        data: cats,
        axisLine: { lineStyle: { color: t.axis } },
        axisTick: { show: false },
        axisLabel: { color: t.muted, fontSize: 11 },
      },
      yAxis: {
        type: 'value',
        min: 0,
        max: 1,
        axisLabel: { color: t.muted, fontSize: 11, formatter: pct },
        splitLine: { lineStyle: { color: t.grid, width: 1, type: 'solid' } },
      },
      series: [
        {
          name: 'Actual win rate',
          type: 'bar',
          data: calibration.map((b) => b.actual),
          barMaxWidth: 24,
          itemStyle: { color: t.series1, borderRadius: [4, 4, 0, 0] },
        },
        {
          name: 'Predicted (avg)',
          type: 'scatter',
          data: calibration.map((b) => b.predicted),
          symbol: 'diamond',
          symbolSize: 10,
          itemStyle: { color: t.ink2, borderColor: t.surface, borderWidth: 2 },
        },
      ],
    }
  }
</script>

{#if calibration.length === 0}
  <div class="empty muted">
    No settled trades yet — calibration appears once positions resolve.
  </div>
{:else}
  <Chart {buildOption} height={240} />
{/if}

<style>
  .empty {
    height: 240px;
    display: grid;
    place-items: center;
    font-size: 14px;
  }
</style>
