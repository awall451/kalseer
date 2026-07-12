<script>
  import { manifest, getDocSource, titleFor, renderMarkdown, statsTokens } from './wiki.js'
  import { buildIndex, searchIndex } from './wikiSearch.js'

  let { slug = 'kalshi-101', stats = null } = $props()

  let query = $state('')

  let tokens = $derived(statsTokens(stats))
  let index = $derived(buildIndex(tokens))
  let results = $derived(searchIndex(index, query))
  let hasResults = $derived(results.titles.length + results.content.length > 0)

  let html = $derived.by(() => {
    const src = getDocSource(slug)
    if (!src) return null
    return renderMarkdown(src, tokens)
  })

  function go(s) {
    query = ''
    location.hash = `#/wiki/${s}`
  }
</script>

<div class="wiki">
  <aside class="side">
    <input
      class="search"
      type="search"
      placeholder="Search wiki…"
      bind:value={query}
      aria-label="Search wiki"
    />
    {#if query.trim().length >= 2}
      <div class="results card">
        {#if !hasResults}
          <div class="muted nores">No matches for “{query}”.</div>
        {/if}
        {#each [...results.titles, ...results.content] as hit}
          <button class="hit" onclick={() => go(hit.slug)}>
            <span class="hit-title">{hit.title}</span>
            <span class="hit-group muted">{hit.group}</span>
            {#if hit.snippet}
              <span class="hit-snippet ink2">{@html hit.snippet}</span>
            {/if}
          </button>
        {/each}
      </div>
    {:else}
      <nav>
        {#each manifest as group}
          <div class="group">
            <div class="group-label muted">{group.label}</div>
            {#each group.items as item}
              <a
                class="nav-item"
                class:active={item.slug === slug}
                href={`#/wiki/${item.slug}`}>{item.title}</a
              >
            {/each}
          </div>
        {/each}
      </nav>
    {/if}
  </aside>

  <article class="prose card">
    {#if html}
      {@html html}
    {:else}
      <p class="muted">No page named “{slug}”. Pick one from the sidebar.</p>
    {/if}
  </article>
</div>

<style>
  .wiki {
    display: grid;
    grid-template-columns: 220px 1fr;
    gap: 16px;
    align-items: start;
  }
  @media (max-width: 760px) {
    .wiki { grid-template-columns: 1fr; }
  }

  .side { position: sticky; top: 16px; }
  @media (max-width: 760px) { .side { position: static; } }

  .search {
    width: 100%;
    background: var(--surface-1);
    color: var(--ink);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 7px 10px;
    font-size: 14px;
    font-family: inherit;
    margin-bottom: 10px;
  }

  .group { margin-bottom: 14px; }
  .group-label {
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    margin-bottom: 4px;
  }
  .nav-item {
    display: block;
    padding: 5px 8px;
    border-radius: 6px;
    color: var(--ink-2);
    text-decoration: none;
    font-size: 14px;
  }
  .nav-item:hover { background: var(--chip); color: var(--ink); }
  .nav-item.active {
    background: var(--series-1-soft);
    color: var(--series-1);
    font-weight: 600;
  }

  .results { padding: 8px; display: grid; gap: 2px; }
  .nores { font-size: 13px; padding: 6px; }
  .hit {
    display: grid;
    gap: 2px;
    text-align: left;
    background: none;
    border: 0;
    border-radius: 6px;
    padding: 7px 8px;
    cursor: pointer;
    font: inherit;
    color: inherit;
  }
  .hit:hover { background: var(--chip); }
  .hit-title { font-size: 13.5px; font-weight: 600; }
  .hit-group { font-size: 11px; }
  .hit-snippet { font-size: 12px; line-height: 1.45; }
  .hit-snippet :global(mark) {
    background: var(--series-1-soft);
    color: var(--series-1);
    border-radius: 2px;
    padding: 0 1px;
  }

  .prose { padding: 26px 30px; max-width: 780px; min-width: 0; }
</style>
