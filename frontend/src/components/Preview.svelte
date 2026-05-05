<script lang="ts">
  import { currentPage, layoutEnabled } from '$lib/stores';
  import type { OcrRegion } from '$lib/types';

  let imgEl: HTMLImageElement | undefined = $state();
  let regions = $derived($currentPage?.ocr_regions || []);
  let highlightedIdx = $state<number | null>(null);

  // Re-render bbox when page or regions change
  let imgLoaded = $state(false);

  function onImgLoad() {
    imgLoaded = true;
  }

  // Scale factors for bbox overlay
  let scaleX = $derived(imgEl && imgLoaded ? imgEl.clientWidth / (imgEl.naturalWidth || 1) : 0);
  let scaleY = $derived(imgEl && imgLoaded ? imgEl.clientHeight / (imgEl.naturalHeight || 1) : 0);

  function highlightRegion(idx: number) {
    highlightedIdx = idx;
    // Dispatch custom event for OcrResult to listen to
    window.dispatchEvent(new CustomEvent('highlight-region', { detail: idx }));
  }

  // Listen for highlight from OcrResult
  $effect(() => {
    const handler = (e: CustomEvent) => {
      highlightedIdx = e.detail;
    };
    window.addEventListener('highlight-region', handler as EventListener);
    return () => window.removeEventListener('highlight-region', handler as EventListener);
  });
</script>

{#if $currentPage}
  <div class="flex h-full w-full items-center justify-center overflow-auto p-4">
    <div class="relative inline-block max-h-full max-w-full">
      <img bind:this={imgEl} src={$currentPage.image_url} alt="Preview"
        class="block max-h-[calc(100vh-100px)] max-w-full rounded-xl object-contain shadow-lg"
        onload={onImgLoad} />

      <!-- BBox overlay -->
      {#if $layoutEnabled && regions.length > 0 && imgLoaded && imgEl}
        <div class="pointer-events-none absolute inset-0">
          {#each regions as region (region.idx)}
            {@const [x1, y1, x2, y2] = region.bbox}
            <!-- svelte-ignore a11y_no_static_element_interactions a11y_click_events_have_key_events -->
            <div class="pointer-events-auto absolute cursor-pointer rounded border-2 border-accent transition-all
              {highlightedIdx === region.idx ? 'opacity-80 bg-accent/15 !border-[3px]' : 'opacity-0 hover:opacity-50 hover:bg-accent/10'}"
              style="left: {x1 * scaleX}px; top: {y1 * scaleY}px; width: {(x2 - x1) * scaleX}px; height: {(y2 - y1) * scaleY}px;"
              onclick={() => highlightRegion(region.idx)}>
            </div>
          {/each}
        </div>
      {/if}
    </div>
  </div>
{/if}
