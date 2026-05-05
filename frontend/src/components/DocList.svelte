<script lang="ts">
  import { docs, activeDocId } from '$lib/stores';
  import { deleteDocument as apiDeleteDoc, getDocument } from '$lib/api';
  import { addToast, resetViewState, pages, activePageNum, activeDocFilename } from '$lib/stores';
  import { escHtml } from '$lib/utils';
  import type { DocItem } from '$lib/types';

  let collapsed = $state(false);

  let showList = $derived($docs.length > 1);

  async function switchDoc(docId: string) {
    try {
      const detail = await getDocument(docId);
      activeDocId.set(detail.doc_id);
      activeDocFilename.set(detail.filename);
      pages.set(detail.pages);
      if (detail.pages.length > 0) activePageNum.set(detail.pages[0].num);
    } catch {
      addToast('Failed to load document');
    }
  }

  async function deleteDoc(doc: DocItem) {
    if (!confirm(`Delete "${doc.filename}"?`)) return;
    try {
      await apiDeleteDoc(doc.doc_id);
    } catch {
      addToast('Delete failed');
      return;
    }
    docs.update(d => d.filter(x => x.doc_id !== doc.doc_id));
    if (doc.doc_id === $activeDocId) {
      const remaining = $docs;
      if (remaining.length > 0) {
        await switchDoc(remaining[0].doc_id);
      } else {
        resetViewState();
      }
    }
  }
</script>

{#if showList}
  <div class="flex flex-col {collapsed ? '' : 'max-h-[45%]'} flex-shrink-0">
    <!-- Header -->
    <!-- svelte-ignore a11y_no_static_element_interactions a11y_click_events_have_key_events -->
    <div class="flex cursor-pointer items-center gap-1.5 border-b border-cream-dark px-3.5 py-3 text-[11px] font-semibold uppercase tracking-wide text-charcoal/45 select-none"
      onclick={() => collapsed = !collapsed}>
      <span>Documents</span>
      <span class="text-[10px] font-medium text-charcoal/35">{$docs.length ? `(${$docs.length})` : ''}</span>
      <span class="flex-1"></span>
      <button class="rounded px-1 py-0.5 text-[10px] text-charcoal/35 transition-all hover:bg-cream hover:text-charcoal"
        onclick={(e) => { e.stopPropagation(); collapsed = !collapsed; }}>
        {collapsed ? '▼' : '▲'}
      </button>
    </div>

    <!-- List -->
    {#if !collapsed}
      <div class="overflow-y-auto px-2 py-1">
        {#each $docs as doc (doc.doc_id)}
          <!-- svelte-ignore a11y_no_static_element_interactions a11y_click_events_have_key_events -->
          <div class="group flex cursor-pointer items-center gap-2 rounded-xl px-2 py-1.5 transition-colors
            {doc.doc_id === $activeDocId ? 'bg-cream-dark outline-2 outline-accent' : 'hover:bg-cream'}"
            onclick={() => doc.doc_id !== $activeDocId && switchDoc(doc.doc_id)}>

            <div class="min-w-0 flex-1">
              <div class="truncate text-xs font-medium text-charcoal" title={doc.filename}>
                {doc.filename}
              </div>
              <div class="mt-0.5 flex items-center gap-1.5 text-[10px] text-charcoal/40">
                <span>{doc.page_count} page{doc.page_count !== 1 ? 's' : ''}</span>
                {#if doc.page_count > 0}
                  <span class="rounded bg-cream-dark px-1.5 text-[10px] font-medium text-accent-dark">
                    {doc.ocr_count}/{doc.page_count}
                  </span>
                {/if}
              </div>
            </div>

            <button onclick={(e) => { e.stopPropagation(); deleteDoc(doc); }}
              class="flex-shrink-0 rounded p-0.5 text-charcoal/25 opacity-0 transition-all hover:bg-red-50 hover:text-red-600 group-hover:opacity-100">
              ×
            </button>
          </div>
        {/each}
      </div>
    {/if}
  </div>
{/if}
