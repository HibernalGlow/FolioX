<script lang="ts">
  import { batchActive, batchId, batchStatus, batchTotal, batchDone, batchCurrent, batchElapsed, batchResults, batchOutputPath } from '$lib/stores';
  import * as api from '$lib/api';
  import { addToast } from '$lib/stores';
  import { formatEta } from '$lib/utils';

  // --- Browse state ---
  let pathInput = $state('D:\\');
  let browseData: api.BrowseResult | null = $state(null);
  let browsing = $state(false);
  let showOptions = $state(false);

  // --- Options ---
  let optImages = $state(false);
  let optLayout = $state(true);
  let optIncremental = $state(false);

  // --- Progress listener ---
  let eventSource: EventSource | null = null;

  // Progress percentage
  let pct = $derived($batchTotal > 0 ? Math.round(($batchDone / $batchTotal) * 100) : 0);
  let eta = $derived.by(() => {
    if ($batchDone === 0 || $batchTotal === 0) return '';
    const rate = $batchDone / $batchElapsed;
    if (rate === 0) return '';
    const remaining = ($batchTotal - $batchDone) / rate;
    return formatEta(remaining);
  });

  // --- Browse directory ---
  async function browse() {
    if (!pathInput.trim()) return;
    browsing = true;
    try {
      browseData = await api.browseDirectory(pathInput);
    } catch (e: any) {
      addToast(e.message || 'Browse failed');
      browseData = null;
    } finally {
      browsing = false;
    }
  }

  function navigateTo(subpath: string) {
    pathInput = subpath;
    browse();
  }

  function navigateUp() {
    if (browseData) {
      pathInput = browseData.parent;
      browse();
    }
  }

  // --- Start batch ---
  async function startBatch() {
    if (!pathInput.trim()) return;

    try {
      const result = await api.startBatch(
        pathInput,
        '.zip,.rar,.7z,.tar,.gz,.pdf',
        optImages,
        optLayout,
        optIncremental,
      );

      batchId.set(result.batch_id);
      batchTotal.set(result.total);
      batchDone.set(0);
      batchCurrent.set('');
      batchElapsed.set(0);
      batchResults.set([]);
      batchStatus.set('running');
      batchActive.set(true);

      if (result.skipped > 0) {
        addToast(`Skipped ${result.skipped} already-processed file(s)`, 'success');
      }

      // Listen to SSE progress
      listenProgress(result.batch_id);

    } catch (e: any) {
      addToast(e.message || 'Failed to start batch');
    }
  }

  function listenProgress(id: string) {
    if (eventSource) eventSource.close();
    eventSource = new EventSource(api.batchProgressUrl(id));

    eventSource.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data);

        batchStatus.set(data.status);
        batchDone.set(data.done || 0);
        batchTotal.set(data.total || 0);
        batchCurrent.set(data.current || '');
        batchElapsed.set(data.elapsed || 0);

        if (data.new_results) {
          batchResults.update(r => [...r, ...data.new_results]);
        }

        if (data.latest_texts) {
          // Can display latest result text
        }

        if (data.output_path) {
          batchOutputPath.set(data.output_path);
        }

        if (data.status === 'completed' || data.status === 'cancelled' || data.status === 'error') {
          eventSource?.close();
          eventSource = null;

          if (data.status === 'completed') {
            const totalChars = data.total_chars || 0;
            const totalErrors = data.total_errors || 0;
            addToast(
              `Batch complete: ${data.done} docs, ${totalChars} chars` + (totalErrors > 0 ? `, ${totalErrors} errors` : ''),
              totalErrors > 0 ? 'warn' : 'success',
              5000,
            );
          } else if (data.status === 'error') {
            addToast('Batch failed: ' + (data.error || 'Unknown error'));
          }

          batchActive.set(false);
        }
      } catch (err) {
        console.error('SSE parse error:', err);
      }
    };

    eventSource.onerror = () => {
      eventSource?.close();
      eventSource = null;
    };
  }

  // --- Cancel ---
  async function cancelBatch() {
    const id = $batchId;
    if (!id) return;
    try {
      await api.cancelBatch(id);
      addToast('Batch cancelled', 'warn');
    } catch {
      addToast('Cancel failed');
    }
  }

  // --- Reset ---
  function resetBatch() {
    batchActive.set(false);
    batchId.set(null);
    batchStatus.set('idle');
    batchTotal.set(0);
    batchDone.set(0);
    batchCurrent.set('');
    batchElapsed.set(0);
    batchResults.set([]);
    batchOutputPath.set('');
    if (eventSource) {
      eventSource.close();
      eventSource = null;
    }
  }

  // Cleanup on unmount
  $effect(() => {
    return () => {
      if (eventSource) {
        eventSource.close();
        eventSource = null;
      }
    };
  });
</script>

<div class="flex h-full flex-col">
  <!-- Header -->
  <div class="flex items-center gap-2 border-b border-cream-dark px-3.5 py-2.5">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
      class="h-4 w-4 text-accent">
      <path d="M3 7V5a2 2 0 012-2h2" /><path d="M17 3h2a2 2 0 012 2v2" />
      <path d="M21 17v2a2 2 0 01-2 2h-2" /><path d="M7 21H5a2 2 0 01-2-2v-2" />
      <rect x="7" y="7" width="10" height="10" rx="1" />
    </svg>
    <span class="text-[11px] font-semibold uppercase tracking-wide text-charcoal/45">Batch OCR</span>
    <span class="flex-1"></span>
    {#if $batchStatus === 'running'}
      <button onclick={cancelBatch}
        class="rounded-lg bg-red-50 px-2 py-0.5 text-[11px] font-medium text-red-600 transition-colors hover:bg-red-100">
        Cancel
      </button>
    {:else if $batchStatus !== 'idle'}
      <button onclick={resetBatch}
        class="rounded-lg bg-cream-dark px-2 py-0.5 text-[11px] font-medium text-charcoal/60 transition-colors hover:bg-cream">
        Reset
      </button>
    {/if}
  </div>

  <!-- Path input + browse -->
  <div class="border-b border-cream-dark px-3.5 py-2.5">
    <div class="flex gap-1.5">
      <input type="text" bind:value={pathInput} placeholder="Enter directory path..."
        disabled={$batchActive}
        onkeydown={(e) => e.key === 'Enter' && browse()}
        class="flex-1 rounded-lg border border-warm-gray bg-white px-2.5 py-1.5 text-[12px] text-charcoal outline-none transition-colors
          focus:border-accent disabled:opacity-50 placeholder:text-charcoal/30" />
      <button onclick={browse} disabled={browsing || $batchActive}
        class="rounded-lg bg-accent px-3 py-1.5 text-[12px] font-medium text-white transition-colors hover:bg-accent-dark disabled:opacity-50">
        {browsing ? '...' : 'Browse'}
      </button>
    </div>

    <!-- Options toggle -->
    {#if !$batchActive}
      <button onclick={() => showOptions = !showOptions}
        class="mt-1.5 text-[11px] text-charcoal/40 transition-colors hover:text-charcoal/60">
        {$showOptions ? '▾' : '▸'} Options
      </button>
      {#if showOptions}
        <div class="mt-1.5 flex flex-col gap-1">
          <label class="flex items-center gap-1.5 text-[11px] text-charcoal/60">
            <input type="checkbox" bind:checked={optImages} class="accent-accent" />
            Include standalone images
          </label>
          <label class="flex items-center gap-1.5 text-[11px] text-charcoal/60">
            <input type="checkbox" bind:checked={optLayout} class="accent-accent" />
            Layout detection
          </label>
          <label class="flex items-center gap-1.5 text-[11px] text-charcoal/60">
            <input type="checkbox" bind:checked={optIncremental} class="accent-accent" />
            Incremental (skip processed)
          </label>
        </div>
      {/if}
    {/if}
  </div>

  <!-- Directory browser -->
  {#if browseData && !$batchActive}
    <div class="max-h-[180px] overflow-y-auto border-b border-cream-dark px-3.5 py-2">
      <!-- Navigate up -->
      <button onclick={navigateUp}
        class="flex w-full items-center gap-1.5 rounded-lg px-2 py-1 text-[11px] text-charcoal/50 transition-colors hover:bg-cream hover:text-charcoal">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="h-3 w-3">
          <path d="M15 18l-6-6 6-6" />
        </svg>
        ..
      </button>

      <!-- Subdirectories -->
      {#each browseData.subdirs as dir}
        <button onclick={() => navigateTo(dir.path)}
          class="flex w-full items-center gap-1.5 rounded-lg px-2 py-1 text-[11px] text-charcoal/70 transition-colors hover:bg-cream">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="h-3 w-3 text-accent/60">
            <path d="M22 19a2 2 0 01-2 2H4a2 2 0 01-2-2V5a2 2 0 012-2h5l2 3h9a2 2 0 012 2z" />
          </svg>
          {dir.name}
        </button>
      {/each}

      <!-- File counts -->
      <div class="mt-1.5 flex items-center gap-2 text-[10px] text-charcoal/40">
        {#if browseData.archives.length > 0}
          <span class="rounded bg-cream px-1.5 py-0.5">{browseData.archives.length} archives</span>
        {/if}
        {#if browseData.pdfs.length > 0}
          <span class="rounded bg-cream px-1.5 py-0.5">{browseData.pdfs.length} PDFs</span>
        {/if}
        {#if browseData.images.length > 0}
          <span class="rounded bg-cream px-1.5 py-0.5">{browseData.images.length} images</span>
        {/if}
        {#if browseData.total_files === 0}
          <span>No matching files</span>
        {/if}
      </div>

      <!-- Start button -->
      {#if browseData.total_files > 0}
        <button onclick={startBatch}
          class="mt-2 w-full rounded-lg bg-accent py-1.5 text-[12px] font-medium text-white transition-colors hover:bg-accent-dark">
          Start Batch ({browseData.total_files} files)
        </button>
      {/if}
    </div>
  {/if}

  <!-- Progress -->
  {#if $batchStatus === 'running'}
    <div class="border-b border-cream-dark px-3.5 py-3">
      <!-- Progress bar -->
      <div class="mb-2 h-2 overflow-hidden rounded-full bg-cream-dark">
        <div class="h-full rounded-full bg-accent transition-all duration-500"
          style="width: {pct}%"></div>
      </div>
      <div class="flex items-center justify-between text-[11px] text-charcoal/50">
        <span>{$batchDone} / {$batchTotal}</span>
        <span>{pct}%</span>
        <span>{eta ? `~${eta}` : ''}</span>
      </div>

      <!-- Current file -->
      {#if $batchCurrent}
        <div class="mt-2 flex items-center gap-1.5">
          <div class="h-3 w-3 animate-spin rounded-full border-2 border-warm-gray border-t-accent"></div>
          <span class="truncate text-[11px] text-charcoal/60">{$batchCurrent}</span>
        </div>
      {/if}
    </div>
  {/if}

  <!-- Completed summary -->
  {#if $batchStatus === 'completed'}
    <div class="border-b border-cream-dark px-3.5 py-3">
      <div class="flex items-center gap-1.5 text-[11px] text-emerald-600">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="h-3.5 w-3.5">
          <path d="M22 11.08V12a10 10 0 11-5.93-9.14" /><polyline points="22 4 12 14.01 9 11.01" />
        </svg>
        <span class="font-medium">Completed: {$batchDone} docs in {formatEta($batchElapsed)}</span>
      </div>
      {#if $batchOutputPath}
        <div class="mt-1 text-[10px] text-charcoal/40">
          Output: {$batchOutputPath}
        </div>
      {/if}
    </div>
  {/if}

  <!-- Results list -->
  {#if $batchResults.length > 0}
    <div class="flex-1 overflow-y-auto px-3.5 py-2">
      <div class="mb-1.5 text-[10px] font-medium uppercase tracking-wide text-charcoal/30">Results</div>
      {#each $batchResults as result, i}
        <div class="mb-1.5 rounded-lg border {result.error ? 'border-red-200 bg-red-50' : 'border-cream-dark bg-white'} px-2.5 py-1.5">
          <div class="flex items-center gap-1.5">
            {#if result.error}
              <span class="text-[10px] text-red-500">✗</span>
            {:else}
              <span class="text-[10px] text-emerald-500">✓</span>
            {/if}
            <span class="min-w-0 flex-1 truncate text-[11px] font-medium text-charcoal">{result.source}</span>
            <span class="flex-shrink-0 text-[10px] text-charcoal/35">
              {result.total_chars || 0} chars
            </span>
          </div>
          {#if result.error}
            <div class="mt-0.5 text-[10px] text-red-400">{result.error}</div>
          {/if}
        </div>
      {/each}
    </div>
  {/if}
</div>
