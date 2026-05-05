<script lang="ts">
  import { pages, activePageNum, activeDocId, layoutEnabled, layoutModelLoaded, isLoadingModel } from '$lib/stores';
  import { ocrPage } from '$lib/api';
  import { addToast } from '$lib/stores';

  async function selectPage(num: number) {
    // Save current editor before switching
    activePageNum.set(num);
    const page = $pages.find(p => p.num === num);
    if (!page) return;

    // If no OCR yet, run it
    if (page.ocr_text == null) {
      await runOcrForPage(page);
    }
  }

  async function runOcrForPage(page: { num: number }) {
    if (!$layoutModelLoaded) {
      const { ensureModelsLoaded } = await import('./TopBar.svelte');
      // Directly load model
      const ok = await loadModel();
      if (!ok) return;
    }

    try {
      const data = await ocrPage($activeDocId!, page.num, $layoutEnabled);
      pages.update(p => p.map(pg => pg.num === data.page_num ? {
        ...pg, ocr_text: data.text, ocr_regions: data.regions, ocr_time: data.time
      } : pg));
    } catch (e: any) {
      addToast('OCR failed: ' + e.message);
    }
  }

  async function loadModel(): Promise<boolean> {
    if ($layoutModelLoaded) return true;
    $isLoadingModel = true;
    try {
      await api.loadModel();
      layoutModelLoaded.set(true);
      return true;
    } catch {
      return false;
    } finally {
      isLoadingModel.set(false);
    }
  }

  function pageStatus(page: { ocr_text: string | null; ocr_time: number | null }): { cls: string; label: string } {
    if (page.ocr_text != null) return { cls: 'text-[#6DBF7B]', label: `Done (${page.ocr_time}s)` };
    return { cls: 'text-charcoal/40', label: 'Pending' };
  }

  // Keyboard navigation
  function handleKeydown(e: KeyboardEvent) {
    if (e.target instanceof HTMLTextAreaElement || e.target instanceof HTMLInputElement) return;
    if (!$activeDocId || $pages.length === 0) return;

    const idx = $pages.findIndex(p => p.num === $activePageNum);
    if ((e.key === 'ArrowUp' || e.key === 'ArrowLeft') && idx > 0) {
      e.preventDefault();
      selectPage($pages[idx - 1].num);
    } else if ((e.key === 'ArrowDown' || e.key === 'ArrowRight') && idx < $pages.length - 1) {
      e.preventDefault();
      selectPage($pages[idx + 1].num);
    }
  }
</script>

<svelte:window onkeydown={handleKeydown} />

<!-- Pages Header -->
<div class="flex-shrink-0 border-b border-cream-dark px-3.5 py-3 text-[11px] font-semibold uppercase tracking-wide text-charcoal/45">
  Pages
</div>

<!-- Page List -->
<div class="flex-1 overflow-y-auto p-2">
  {#each $pages as page (page.num)}
    {@const status = pageStatus(page)}
    <button
      class="flex w-full items-center gap-2 rounded-xl px-1.5 py-1.5 text-left transition-colors
        {page.num === $activePageNum ? 'bg-cream-dark outline-2 outline-accent' : 'hover:bg-cream'}"
      onclick={() => selectPage(page.num)}>
      <img src={page.image_url} alt="Page {page.num}" loading="lazy"
        class="h-12 w-12 flex-shrink-0 rounded-lg object-cover bg-cream" />
      <div class="min-w-0 flex-1">
        <div class="text-[13px] font-medium text-charcoal">Page {page.num}</div>
        <div class="mt-0.5 text-[11px] {status.cls}">{status.label}</div>
      </div>
    </button>
  {/each}
</div>
