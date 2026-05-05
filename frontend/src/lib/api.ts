import type { StatusResponse, OcrResponse, DocItem, DocDetail } from './types';

const BASE = '';  // Same origin in production; Vite proxy in dev

function fetchT(url: string, opts: RequestInit = {}, timeoutMs = 15000): Promise<Response> {
  const controller = new AbortController();
  const existing = opts.signal;
  if (existing) {
    existing.addEventListener('abort', () => controller.abort());
  }
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  return fetch(BASE + url, { ...opts, signal: controller.signal })
    .finally(() => clearTimeout(timer));
}

export async function checkStatus(): Promise<StatusResponse> {
  const res = await fetchT('/api/status', {}, 5000);
  return res.json();
}

export async function loadModel(): Promise<{ success: boolean }> {
  const res = await fetchT('/api/load-model', { method: 'POST' }, 180000);
  if (!res.ok) throw new Error('Load failed');
  return res.json();
}

export async function uploadFiles(files: File[]): Promise<Response> {
  const formData = new FormData();
  for (const f of files) formData.append('files', f);
  return fetchT('/api/upload', { method: 'POST', body: formData }, 120000);
}

export async function ocrPage(docId: string, pageNum: number, layout = true, force = false): Promise<OcrResponse> {
  const res = await fetchT(
    `/api/ocr/${docId}/${pageNum}?layout=${layout}${force ? '&force=true' : ''}`,
    { method: 'POST' },
    120000,
  );
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || 'OCR failed');
  }
  return res.json();
}

export async function savePageText(docId: string, pageNum: number, text: string): Promise<void> {
  await fetchT(
    `/api/pages/${docId}/${pageNum}/text`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
    },
    10000,
  );
}

export async function listDocuments(): Promise<DocItem[]> {
  const res = await fetchT('/api/documents', {}, 10000);
  return res.json();
}

export async function getDocument(docId: string): Promise<DocDetail> {
  const res = await fetchT(`/api/documents/${docId}`, {}, 10000);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

export async function deleteDocument(docId: string): Promise<void> {
  await fetchT(`/api/documents/${docId}`, { method: 'DELETE' }, 10000);
}

export async function exportDocx(
  docId: string,
  pages: { num: number; text: string }[],
  title?: string | null,
): Promise<Blob> {
  const res = await fetchT(
    `/api/export/${docId}`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pages, title: title || null }),
    },
    60000,
  );
  if (!res.ok) throw new Error(`Export failed: HTTP ${res.status}`);
  return res.blob();
}

export function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
