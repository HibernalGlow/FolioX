<script lang="ts">
  import { currentPage, viewMode, activeDocId, layoutEnabled, layoutModelLoaded, searchQuery } from '$lib/stores';
  import { ocrPage, savePageText } from '$lib/api';
  import { addToast } from '$lib/stores';
  import { renderPreview, renderRegionBlocks, escHtml } from '$lib/utils';
  import type { OcrRegion } from '$lib/types';

  let editorText = $state('');
  let saveTimer: ReturnType<typeof setTimeout> | null = null;

  // Sync editor text when page changes
  $effect(() => {
    if ($currentPage) {
      editorText = $currentPage.ocr_text || '';
    }
  });

  // Auto-save on edit
  function handleInput() {
    if (!$activeDocId || !$currentPage) return;
    // Update local state immediately
    const pageNum = $currentPage.num;
    const text = editorText;

    if (saveTimer) clearTimeout(saveTimer);
    saveTimer = setTimeout(async () => {
      if ($activeDocId) {
        try {
          await savePageText($activeDocId, pageNum, text);
        } catch {
          addToast('Auto-save failed', 'warn');
        }
      }
    }, 800);
  }

  // View toggle
  function setViewMode(mode: 'edit' | 'preview') {
    // Save before switching
    if ($viewMode === 'edit' && $currentPage) {
      // Already saved via handleInput debounce
    }
    viewMode.set(mode);
  }

  // Copy current page
  async function copyPage() {
    if ($currentPage?.ocr_text) {
      await navigator.clipboard.writeText($currentPage.ocr_text);
      addToast('Copied!', 'success');
    }
  }

  // Re-scan
  async function rescanPage() {
    if (!$currentPage || !$activeDocId) return;
    try {
      const data = await ocrPage($activeDocId, $currentPage.num, $layoutEnabled, true);
      const { pages } = await import('$lib/stores');
      pages.update(p => p.map(pg => pg.num === data.page_num ? {
        ...pg, ocr_text: data.text, ocr_regions: data.regions, ocr_time: data.time
      } : pg));
      editorText = data.text;
    } catch (e: any) {
      addToast('Re-scan failed: ' + e.message);
    }
  }

  // Computed preview HTML
  let previewHtml = $derived.by(() => {
    const page = $currentPage;
    if (!page) return '';
    const q = $searchQuery;
    if (page.ocr_regions && page.ocr_regions.length > 0) {
      return renderRegionBlocks(page.ocr_regions, q);
    }
    return renderPreview(page.ocr_text || '', q);
  });

  // Highlight region from Preview
  let highlightedRegion = $state<number | null>(null);

  $effect(() => {
    const handler = (e: CustomEvent) => {
      highlightedRegion = e.detail;
      // Switch to preview mode if in edit
      if ($viewMode === 'edit') viewMode.set('preview');
    };
    window.addEventListener('highlight-region', handler as EventListener);
    return () => window.removeEventListener('highlight-region', handler as EventListener);
  });

  function handleRegionClick(e: MouseEvent) {
    const target = e.target as HTMLElement;
    const block = target.closest('.region-block') as HTMLElement | null;
    if (block?.dataset.idx) {
      const idx = parseInt(block.dataset.idx);
      highlightedRegion = idx;
      window.dispatchEvent(new CustomEvent('highlight-region', { detail: idx }));
    }
  }
</script>

<div class="flex h-full flex-col">
  <!-- Header -->
  <div class="flex flex-col gap-1.5 border-b border-cream-dark px-3.5 py-2">
    <div class="flex items-center gap-2">
      <span class="text-[11px] font-semibold uppercase tracking-wide text-charcoal/45">OCR Result</span>
      <span class="flex-1"></span>
      {#if $currentPage?.ocr_time != null}
        <span class="rounded-lg bg-cream-dark px-2 py-0.5 text-[11px] text-accent-dark">
          {$currentPage.ocr_time}s
        </span>
      {/if}
    </div>
    {#if $currentPage?.ocr_text != null}
      <div class="flex items-center gap-2">
        <div class="flex rounded-lg bg-cream-dark p-0.5 gap-0.5">
          <button onclick={() => setViewMode('edit')}
            class="rounded-md px-2.5 py-0.5 text-[11px] font-medium transition-all
              {$viewMode === 'edit' ? 'bg-white text-charcoal shadow-sm' : 'text-charcoal/50 hover:text-charcoal'}">
            Edit
          </button>
          <button onclick={() => setViewMode('preview')}
            class="rounded-md px-2.5 py-0.5 text-[11px] font-medium transition-all
              {$viewMode === 'preview' ? 'bg-white text-charcoal shadow-sm' : 'text-charcoal/50 hover:text-charcoal'}">
            Preview
          </button>
        </div>
        <span class="flex-1"></span>
        <button onclick={rescanPage}
          class="rounded-lg bg-warm-gray px-2 py-0.5 text-xs font-medium text-charcoal transition-colors hover:bg-cream-dark"
          title="Re-scan this page (ignore cache)">
          Re-scan
        </button>
        <button onclick={copyPage}
          class="rounded-lg bg-warm-gray px-2 py-0.5 text-xs font-medium text-charcoal transition-colors hover:bg-cream-dark">
          Copy
        </button>
      </div>
    {/if}
  </div>

  <!-- Body -->
  <div class="flex-1 overflow-y-auto">
    {#if !$currentPage}
      <div class="pt-16 text-center text-sm text-charcoal/30">Select a page to view OCR result</div>
    {:else if $currentPage.ocr_text == null}
      <div class="flex flex-col items-center pt-16 text-charcoal/50 text-[13px]">
        <div class="mb-3 h-8 w-8 animate-spin rounded-full border-[3px] border-warm-gray border-t-accent"></div>
        Loading...
      </div>
    {:else if $viewMode === 'edit'}
      <textarea bind:value={editorText} oninput={handleInput}
        placeholder="No text recognized"
        class="h-full w-full resize-none border-none bg-white p-4 font-mono text-sm leading-relaxed text-charcoal outline-none
          placeholder:text-charcoal/25 whitespace-pre-wrap break-all"></textarea>
    {:else}
      <!-- Preview mode -->
      <!-- svelte-ignore a11y_no_static_element_interactions a11y_click_events_have_key_events -->
      <div class="result-preview p-4 text-sm leading-relaxed text-charcoal whitespace-pre-line break-all"
        onclick={handleRegionClick}>
        {@html previewHtml}
      </div>
    {/if}
  </div>
</div>
