<script lang="ts">
  import TopBar from './components/TopBar.svelte';
  import DocList from './components/DocList.svelte';
  import PageList from './components/PageList.svelte';
  import UploadZone from './components/UploadZone.svelte';
  import Preview from './components/Preview.svelte';
  import ResizeHandle from './components/ResizeHandle.svelte';
  import OcrResult from './components/OcrResult.svelte';
  import ProgressBar from './components/ProgressBar.svelte';
  import ToastContainer from './components/ToastContainer.svelte';
  import BatchPanel from './components/BatchPanel.svelte';
  import { activeDocId, batchActive } from '$lib/stores';

  let rightPanelWidth = $state(480);
  let showDoc = $derived($activeDocId !== null);
  let showBatch = $derived($batchActive || showBatchPanel);
  let showBatchPanel = $state(false);
</script>

<div class="flex h-screen flex-col overflow-hidden">
  <!-- Top Bar -->
  <TopBar bind:showBatchPanel={showBatchPanel} />

  <!-- Progress Bar -->
  <ProgressBar />

  <!-- Main 3-Column Layout -->
  <div class="flex flex-1 overflow-hidden">
    <!-- Left: Doc List + Page List OR Batch Panel -->
    {#if showBatch}
      <div class="flex w-[280px] flex-shrink-0 flex-col border-r border-warm-gray bg-white">
        <BatchPanel />
      </div>
    {:else if showDoc}
      <div class="flex w-[200px] flex-shrink-0 flex-col border-r border-warm-gray bg-white">
        <DocList />
        <div class="h-px bg-warm-gray"></div>
        <PageList />
      </div>
    {/if}

    <!-- Center: Upload / Preview -->
    <div class="relative flex flex-1 items-center justify-center overflow-hidden bg-cream">
      {#if showDoc}
        <Preview />
      {:else}
        <UploadZone />
      {/if}
    </div>

    <!-- Resize Handle + Right Panel -->
    {#if showDoc}
      <ResizeHandle bind:panelWidth={rightPanelWidth} />
      <div class="flex flex-shrink-0 flex-col border-l border-warm-gray bg-white" style="width: {rightPanelWidth}px">
        <OcrResult />
      </div>
    {/if}
  </div>
</div>

<ToastContainer />
