<script lang="ts">
  import { activeDocId, activeDocFilename, modelLoaded, layoutModelLoaded, isLoadingModel, layoutEnabled, ocrRunning, viewMode, currentPage, pages } from '$lib/stores';
  import * as api from '$lib/api';
  import { addToast } from '$lib/stores';

  let statusText = $state('Checking...');
  let statusType = $state<'online' | 'loading' | 'error'>('loading');
  let showExportMenu = $state(false);
  let showSearch = $state(false);
  let searchInputValue = $state('');
  let loadBtnText = $state('Load Model');

  let showDoc = $derived($activeDocId !== null);

  // --- Status polling ---
  let statusInterval: ReturnType<typeof setInterval>;

  async function checkStatus() {
    try {
      const data = await api.checkStatus();
      modelLoaded.set(data.model_loaded);
      layoutModelLoaded.set(data.layout_loaded);
      if ($isLoadingModel) return;
      if (!data.model_loaded) {
        statusType = 'error';
        statusText = 'OCR model not found';
      } else if (!data.layout_loaded) {
        statusType = 'loading';
        statusText = 'Layout not loaded';
      } else {
        statusType = 'online';
        statusText = 'Ready';
      }
    } catch {
      statusType = 'error';
      statusText = 'Offline';
    }
  }

  $effect(() => {
    checkStatus();
    statusInterval = setInterval(checkStatus, 3000);
    return () => clearInterval(statusInterval);
  });

  // Auto-load models on startup if not already loaded
  $effect(() => {
    if (!$modelLoaded || $layoutModelLoaded || $isLoadingModel) return;
    // Ollama is online but layout model not loaded — auto trigger
    ensureModelsLoaded();
  });

  // --- Load model ---
  let _modelLoadPromise: Promise<boolean> | null = null;

  async function ensureModelsLoaded(): Promise<boolean> {
    if ($layoutModelLoaded) return true;
    if (_modelLoadPromise) return _modelLoadPromise;

    _modelLoadPromise = (async () => {
      isLoadingModel.set(true);
      loadBtnText = 'Loading...';
      statusType = 'loading';
      statusText = 'Loading model...';
      const t0 = Date.now();
      const timer = setInterval(() => {
        const s = Math.round((Date.now() - t0) / 1000);
        statusText = `Loading model... ${s}s`;
        loadBtnText = `Loading... ${s}s`;
      }, 1000);

      try {
        await api.loadModel();
        const elapsed = ((Date.now() - t0) / 1000).toFixed(1);
        layoutModelLoaded.set(true);
        statusType = 'online';
        statusText = `Ready (loaded ${elapsed}s)`;
        return true;
      } catch {
        statusType = 'error';
        statusText = 'Load failed';
        return false;
      } finally {
        clearInterval(timer);
        isLoadingModel.set(false);
        loadBtnText = 'Load Model';
        _modelLoadPromise = null;
      }
    })();
    return _modelLoadPromise;
  }

  // --- Export ---
  function closeExportMenu() { showExportMenu = false; }

  async function handleExport(fmt: string) {
    showExportMenu = false;
    const { buildMarkdown, buildPlainText } = await import('$lib/utils');

    const baseName = ($activeDocFilename || 'document').replace(/\.[^.]+$/, '');

    if (fmt === 'docx') {
      const pageList = $pages.map(p => ({ num: p.num, text: p.ocr_text || '' }));
      if (pageList.every(p => !p.text)) return;
      const firstPage = $pages[0];
      const titleRegion = firstPage?.ocr_regions?.find(r => r.label === 'title');
      const docTitle = titleRegion ? titleRegion.text.trim() : null;
      try {
        const blob = await api.exportDocx($activeDocId!, pageList, docTitle);
        api.downloadBlob(blob, baseName + '.docx');
      } catch (err: any) {
        addToast('DOCX export failed: ' + err.message);
      }
      return;
    }

    let blob: Blob | null = null;
    let ext = '';

    if (fmt === 'md') {
      const md = buildMarkdown($pages, $activeDocFilename);
      if (!md) return;
      blob = new Blob([md], { type: 'text/markdown;charset=utf-8' });
      ext = '.md';
    } else if (fmt === 'txt') {
      const txt = buildPlainText($pages);
      if (!txt) return;
      blob = new Blob([txt], { type: 'text/plain;charset=utf-8' });
      ext = '.txt';
    }

    if (blob) api.downloadBlob(blob, baseName + ext);
  }

  // --- Search ---
  function handleSearchToggle() {
    showSearch = !showSearch;
  }

  function handleSearchInput(e: Event) {
    const target = e.target as HTMLInputElement;
    searchInputValue = target.value;
  }

  function handleSearchKeydown(e: KeyboardEvent) {
    if (e.key === 'Escape') {
      showSearch = false;
      searchInputValue = '';
    }
  }

  // --- Global keyboard shortcuts ---
  function handleKeydown(e: KeyboardEvent) {
    if ((e.ctrlKey || e.metaKey) && e.key === 'f' && showDoc) {
      e.preventDefault();
      showSearch = true;
    }
  }

  // --- OCR All ---
  let ocrAllBtnText = $state('OCR All Pages');
  let ocrAllDanger = $state(false);

  // Re-scan current page
  async function handleRescan() {
    const page = $currentPage;
    if (!page || !$activeDocId) return;
    try {
      const data = await api.ocrPage($activeDocId, page.num, $layoutEnabled, true);
      pages.update(p => p.map(pg => pg.num === data.page_num ? {
        ...pg, ocr_text: data.text, ocr_regions: data.regions, ocr_time: data.time
      } : pg));
    } catch (e: any) {
      addToast('Re-scan failed: ' + e.message);
    }
  }

  // --- Copy All ---
  async function handleCopyAll() {
    const { buildMarkdown } = await import('$lib/utils');
    const md = buildMarkdown($pages, $activeDocFilename);
    if (md) {
      await navigator.clipboard.writeText(md);
      addToast('Copied!', 'success');
    }
  }
</script>

<svelte:window onkeydown={handleKeydown} onclick={closeExportMenu} />

<!-- Top Bar -->
<div class="flex h-[52px] flex-shrink-0 items-center gap-4 bg-charcoal px-5 text-cream" onclick={(e) => e.stopPropagation()}>
  <!-- Brand -->
  <span class="text-lg font-bold tracking-tight text-accent">Folio-OCR</span>

  <!-- GitHub -->
  <a href="https://github.com/vorojar/Folio-OCR" target="_blank" rel="noopener"
    class="flex items-center text-white/40 transition-colors hover:text-white">
    <svg width="18" height="18" viewBox="0 0 16 16" fill="currentColor">
      <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27s1.36.09 2 .27c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0016 8c0-4.42-3.58-8-8-8z"/>
    </svg>
  </a>

  <!-- Divider -->
  <div class="h-6 w-px bg-white/15"></div>

  <!-- Filename -->
  <span class="min-w-0 overflow-hidden text-ellipsis whitespace-nowrap text-sm opacity-70">
    {$activeDocFilename || 'No document'}
  </span>

  <!-- Spacer -->
  <div class="flex-1"></div>

  <!-- Search -->
  {#if showDoc}
    <div class="flex items-center gap-1">
      <button onclick={handleSearchToggle}
        class="rounded p-1 transition-colors {showSearch ? 'text-accent' : 'text-white/50 hover:text-white'}">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
        </svg>
      </button>
      {#if showSearch}
        <input type="text" placeholder="Search..." bind:value={searchInputValue}
          onkeydown={handleSearchKeydown}
          class="w-40 rounded-lg bg-white/10 px-2.5 py-1 text-[13px] text-white outline-none placeholder:text-white/40" />
      {/if}
    </div>
  {/if}

  <!-- Status -->
  <div class="flex items-center gap-1.5 whitespace-nowrap text-xs opacity-60">
    <span class="h-2 w-2 flex-shrink-0 rounded-full
      {statusType === 'online' ? 'bg-[#6DBF7B]' : statusType === 'loading' ? 'bg-accent animate-pulse' : 'bg-red-600'}">
    </span>
    <span>{statusText}</span>
  </div>

  <!-- Load Model Button -->
  {#if !$layoutModelLoaded && $modelLoaded}
    <button onclick={ensureModelsLoaded} disabled={$isLoadingModel}
      class="rounded-xl bg-white/10 px-3.5 py-1.5 text-[13px] font-medium text-white/80 transition-all hover:bg-white/18 hover:text-white disabled:opacity-40">
      {loadBtnText}
    </button>
  {/if}

  <!-- Upload -->
  <button onclick={() => document.getElementById('fileInput')?.click()}
    class="rounded-xl bg-white/10 px-3.5 py-1.5 text-[13px] font-medium text-white/80 transition-all hover:bg-white/18 hover:text-white">
    Upload
  </button>

  {#if showDoc}
    <!-- Layout Toggle -->
    <div class="flex items-center gap-1.5 text-xs text-white/60">
      <button onclick={() => layoutEnabled.update(v => !v)}
        class="relative h-[18px] w-[32px] rounded-full transition-colors {$layoutEnabled ? 'bg-accent' : 'bg-white/15'}">
        <span class="absolute top-[2px] left-[2px] h-[14px] w-[14px] rounded-full bg-white transition-transform
          {$layoutEnabled ? 'translate-x-[14px]' : ''}"></span>
      </button>
      <span>Layout</span>
    </div>

    <!-- OCR All -->
    <button
      class="rounded-xl px-3.5 py-1.5 text-[13px] font-medium transition-all
        {ocrAllDanger ? 'bg-red-600 text-white hover:bg-red-700' : 'bg-accent text-white hover:bg-accent-dark'}">
      {ocrAllBtnText}
    </button>

    <!-- Export -->
    <div class="relative">
      <button onclick={() => showExportMenu = !showExportMenu}
        class="rounded-xl bg-white/10 px-3.5 py-1.5 text-[13px] font-medium text-white/80 transition-all hover:bg-white/18 hover:text-white">
        Export
      </button>
      {#if showExportMenu}
        <div class="absolute right-0 top-full z-50 mt-1.5 min-w-[170px] rounded-xl bg-white py-1 shadow-xl"
          onclick={(e) => e.stopPropagation()}>
          <button onclick={() => handleExport('md')}
            class="w-full px-3.5 py-2 text-left text-[13px] text-charcoal transition-colors hover:bg-cream">
            .md &nbsp; Markdown
          </button>
          <button onclick={() => handleExport('txt')}
            class="w-full px-3.5 py-2 text-left text-[13px] text-charcoal transition-colors hover:bg-cream">
            .txt &nbsp; Plain Text
          </button>
          <button onclick={() => handleExport('docx')}
            class="w-full px-3.5 py-2 text-left text-[13px] text-charcoal transition-colors hover:bg-cream">
            .docx &nbsp; Word
          </button>
        </div>
      {/if}
    </div>

    <!-- Copy All -->
    <button onclick={handleCopyAll}
      class="rounded-xl bg-white/10 px-3.5 py-1.5 text-[13px] font-medium text-white/80 transition-all hover:bg-white/18 hover:text-white">
      Copy All
    </button>
  {/if}
</div>
