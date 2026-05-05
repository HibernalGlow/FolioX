<script lang="ts">
  import { uploadFiles } from '$lib/api';
  import { activeDocId, activeDocFilename, pages, activePageNum, docs } from '$lib/stores';
  import { addToast, resetViewState } from '$lib/stores';

  let dragover = $state(false);
  let uploading = $state(false);

  function handleFiles(fileList: FileList | File[]) {
    if (fileList.length === 0) return;
    const files = Array.from(fileList);
    doUpload(files);
  }

  async function doUpload(files: File[]) {
    uploading = true;
    resetViewState();
    activeDocFilename.set(`Uploading ${files.length === 1 ? files[0].name : files.length + ' files'}...`);

    try {
      const res = await uploadFiles(files);
      if (!res.ok) {
        let msg = 'Upload failed';
        try {
          const err = await res.json();
          msg = typeof err.detail === 'string' ? err.detail : JSON.stringify(err.detail);
        } catch { msg = `HTTP ${res.status}`; }
        throw new Error(msg);
      }
      await handleUploadStream(res);
    } catch (e: any) {
      activeDocFilename.set('Upload failed: ' + e.message);
      addToast(e.message);
    } finally {
      uploading = false;
    }
  }

  async function handleUploadStream(res: Response) {
    const reader = res.body!.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split('\n\n');
      buffer = parts.pop()!;

      for (const part of parts) {
        const line = part.split('\n').find(l => l.startsWith('data: '));
        if (!line) continue;
        const evt = JSON.parse(line.slice(6));

        if (evt.type === 'init') {
          activeDocId.set(evt.doc_id);
          activeDocFilename.set(evt.filename);
          pages.set([]);
          activePageNum.set(null);
          docs.update(d => [{
            doc_id: evt.doc_id,
            filename: evt.filename,
            page_count: 0,
            ocr_count: 0,
            created_at: new Date().toISOString(),
          }, ...d]);
        } else if (evt.type === 'page') {
          pages.update(p => [...p, evt.page]);
          if ($pages.length === 1) activePageNum.set(evt.page.num);
        }
      }
    }
  }

  function handleDragOver(e: DragEvent) {
    e.preventDefault();
    dragover = true;
  }

  function handleDragLeave() {
    dragover = false;
  }

  function handleDrop(e: DragEvent) {
    e.preventDefault();
    dragover = false;
    if (e.dataTransfer?.files.length) handleFiles(e.dataTransfer.files);
  }

  function handleClick() {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.png,.jpg,.jpeg,.gif,.bmp,.pdf,.webp,.avif,.jxl';
    input.multiple = true;
    input.onchange = () => {
      if (input.files) handleFiles(input.files);
    };
    input.click();
  }
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div class="flex flex-col items-center justify-center px-10 py-16"
  ondragover={handleDragOver} ondragleave={handleDragLeave} ondrop={handleDrop}>

  <!-- svelte-ignore a11y_click_events_have_key_events -->
  <div class="flex max-w-[420px] w-4/5 flex-col items-center rounded-2xl border-2 border-dashed bg-white p-16 transition-all cursor-pointer
    {dragover ? 'border-accent bg-cream-dark' : 'border-warm-gray hover:border-accent hover:bg-cream'}"
    onclick={handleClick} role="button" tabindex={0}>

    <!-- Upload icon -->
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"
      class="mb-4 h-14 w-14 stroke-accent opacity-60">
      <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" />
      <polyline points="17 8 12 3 7 8" />
      <line x1="12" y1="3" x2="12" y2="15" />
    </svg>

    <p class="mb-1.5 text-[15px] text-charcoal">Click or drag files here</p>
    <small class="text-xs text-charcoal/40">Supports: PNG, JPG, GIF, BMP, PDF</small>
  </div>
</div>
