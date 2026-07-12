<script>
  import * as echarts from 'echarts'
  import { onMount } from 'svelte'
  import { readTokens, onSchemeChange } from './tokens.js'

  // buildOption(tokens) -> echarts option; re-invoked on theme change
  let { buildOption, height = 260 } = $props()

  let el
  let chart

  function render() {
    if (!chart) return
    chart.setOption(buildOption(readTokens()), true)
  }

  onMount(() => {
    chart = echarts.init(el, null, { renderer: 'canvas' })
    render()
    const ro = new ResizeObserver(() => chart.resize())
    ro.observe(el)
    const offScheme = onSchemeChange(render)
    return () => {
      ro.disconnect()
      offScheme()
      chart.dispose()
    }
  })

  $effect(() => {
    buildOption
    render()
  })
</script>

<div bind:this={el} style="width:100%; height:{height}px"></div>
