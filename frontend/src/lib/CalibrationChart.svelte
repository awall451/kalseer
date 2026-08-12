<script>
  import Chart from './Chart.svelte'

  let { calibration = [] } = $props()

  const pct = (v) => Math.round(v * 100) + '%'

  let total = $derived(calibration.reduce((s, b) => s + b.n, 0))

  function buildOption(t) {
    const cats = calibration.map((b) => `${pct(b.lo)}–${pct(b.hi)}`)
    // 95% Wilson interval as a vertical whisker. At n=1 it spans nearly the
    // whole axis, which is exactly the message: one trade proves nothing.
    const intervals = calibration.map((b, i) => [i, b.lo95 ?? 0, b.hi95 ?? 1])
    return {
      backgroundColor: 'transparent',
      grid: { left: 46, right: 20, top: 44, bottom: 42 },
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
        confine: true,
        backgroundColor: t.surface,
        borderColor: t.grid,
        textStyle: { color: t.ink, fontSize: 12 },
        formatter: (params) => {
          const i = params[0].dataIndex
          const b = calibration[i]
          return (
            `<b>said ${pct(b.lo)}–${pct(b.hi)}</b> (n=${b.n})<br/>` +
            `happened: <b>${pct(b.actual)}</b><br/>` +
            `95% range: ${pct(b.lo95 ?? 0)}–${pct(b.hi95 ?? 1)}<br/>` +
            `predicted avg: ${pct(b.predicted)}`
          )
        },
      },
      xAxis: {
        type: 'category',
        data: cats,
        axisLine: { lineStyle: { color: t.axis } },
        axisTick: { show: false },
        axisLabel: {
          color: t.muted,
          fontSize: 10.5,
          lineHeight: 14,
          interval: 0, // every bucket labelled; n is the point of the chart
          formatter: (v, i) => `${v}\nn=${calibration[i].n}`,
        },
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
          data: calibration.map((b) => ({
            value: b.actual,
            // Faint while the sample is thin — at n=1 the bar is the least
            // trustworthy mark on the chart.
            itemStyle: { opacity: Math.min(1, 0.3 + 0.7 * (b.n / 10)) },
          })),
          barMaxWidth: 24,
          itemStyle: { color: t.series1, borderRadius: [4, 4, 0, 0] },
          z: 1,
        },
        {
          name: '95% interval',
          type: 'custom',
          data: intervals,
          silent: true,
          z: 3,
          renderItem: (params, api) => {
            const x = api.coord([api.value(0), 0])[0]
            const lo = api.coord([api.value(0), api.value(1)])[1]
            const hi = api.coord([api.value(0), api.value(2)])[1]
            const cap = 5
            const line = (x1, y1, x2, y2) => ({
              type: 'line',
              shape: { x1, y1, x2, y2 },
              style: { stroke: t.ink2, lineWidth: 1.5, opacity: 0.85 },
            })
            return {
              type: 'group',
              children: [
                line(x, lo, x, hi),
                line(x - cap, lo, x + cap, lo),
                line(x - cap, hi, x + cap, hi),
              ],
            }
          },
        },
        {
          name: 'Predicted (avg)',
          type: 'scatter',
          data: calibration.map((b) => b.predicted),
          symbol: 'diamond',
          symbolSize: 10,
          itemStyle: { color: t.ink2, borderColor: t.surface, borderWidth: 2 },
          z: 4,
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
  <p class="note" class:warn={total < 20}>
    {#if total < 20}
      ⚠ Only {total} settled {total === 1 ? 'trade' : 'trades'}. Whiskers are 95%
      ranges and they span most of the chart — nothing here is a signal yet.
    {:else}
      Whiskers are 95% ranges. Bars should sit near the diamonds if the
      fair-value estimates are honest.
    {/if}
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
    color: var(--muted);
  }
  .note.warn {
    color: var(--ink-2);
  }
</style>
