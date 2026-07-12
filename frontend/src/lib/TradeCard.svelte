<script>
  import { marketUrl } from './kalshiUrl.js'

  let { trade, slugs = {} } = $props()

  const fmtc = (v) => Math.round(v * 100) + '¢'
</script>

<div class="card trade">
  <div class="head">
    <span class="side" class:no={trade.side === 'no'}>{trade.side.toUpperCase()}</span>
    <a class="mono ticker" href={marketUrl(trade.ticker, slugs)}
       target="_blank" rel="noopener">{trade.ticker} ↗</a>
    {#if trade.result}
      <span class="result" class:won={trade.won} class:lost={!trade.won}>
        {trade.won ? '✓ WIN' : '✗ LOSS'}
        {#if trade.pnl != null}
          <span class="pnl">{trade.pnl >= 0 ? '+' : ''}${trade.pnl.toFixed(2)}</span>
        {/if}
      </span>
    {/if}
  </div>
  {#if trade.title}<div class="title">{trade.title}</div>{/if}
  <div class="chips">
    <span class="chip">{trade.qty ?? trade.contracts}x @ {fmtc(trade.price ?? trade.entry_price)}</span>
    <span class="chip">fair {fmtc(trade.fair ?? trade.fair_value)}</span>
    <span class="chip">edge {((trade.edge ?? trade.edge_at_entry) >= 0 ? '+' : '')}{Math.round((trade.edge ?? trade.edge_at_entry) * 100)}¢</span>
  </div>
  <p class="why ink2">{trade.reasoning}</p>
</div>

<style>
  .trade { margin-top: 12px; }
  .head { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
  .side {
    font-size: 11.5px; font-weight: 700; letter-spacing: 0.04em;
    padding: 2px 8px; border-radius: 99px;
    background: var(--series-1-soft); color: var(--series-1);
  }
  .side.no { background: var(--chip); color: var(--ink-2); }
  .ticker { color: var(--ink-2); text-decoration: none; }
  .ticker:hover { color: var(--series-1); text-decoration: underline; }
  .title { font-weight: 600; margin-top: 6px; }
  .result { font-size: 12.5px; font-weight: 700; margin-left: auto; }
  .result.won { color: var(--good-text); }
  .result.lost { color: var(--critical); }
  .pnl { margin-left: 6px; }
  .chips { display: flex; gap: 8px; margin-top: 8px; flex-wrap: wrap; }
  .chip {
    background: var(--chip); border-radius: 6px; padding: 2px 8px;
    font-size: 12.5px; color: var(--ink-2);
  }
  .why { margin: 10px 0 0; font-size: 14px; }
</style>
