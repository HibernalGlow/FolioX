import { writable, derived } from 'svelte/store';
import type { Page, DocItem, OcrRegion, SearchMatch, Toast } from './types';

// --- Core app state ---
export const activeDocId = writable<string | null>(null);
export const activeDocFilename = writable<string | null>(null);
export const pages = writable<Page[]>([]);
export const activePageNum = writable<number | null>(null);
export const docs = writable<DocItem[]>([]);

// --- Model status ---
export const modelLoaded = writable(false);
export const layoutModelLoaded = writable(false);
export const isLoadingModel = writable(false);

// --- OCR state ---
export const ocrRunning = writable(false);
export const ocrAbort = writable(false);
export const ocrProgress = writable({ done: 0, total: 0, elapsed: 0 });

// --- View state ---
export const viewMode = writable<'edit' | 'preview'>('preview');
export const layoutEnabled = writable(true);

// --- Search state ---
export const searchQuery = writable('');
export const searchMatches = writable<SearchMatch[]>([]);
export const searchIdx = writable(-1);

// --- Toast notifications ---
let _toastId = 0;
export const toasts = writable<Toast[]>([]);

export function addToast(message: string, type: Toast['type'] = 'error', duration = 3500) {
  const id = ++_toastId;
  toasts.update(t => [...t, { id, message, type }]);
  setTimeout(() => {
    toasts.update(t => t.filter(x => x.id !== id));
  }, duration);
}

// --- Derived: current page ---
export const currentPage = derived(
  [pages, activePageNum],
  ([$pages, $activePageNum]) => $pages.find(p => p.num === $activePageNum) ?? null,
);

// --- Derived: OCR count ---
export const ocrDoneCount = derived(pages, $pages => $pages.filter(p => p.ocr_text != null).length);

// --- Helper: reset view state ---
export function resetViewState() {
  activeDocId.set(null);
  activeDocFilename.set(null);
  pages.set([]);
  activePageNum.set(null);
  searchQuery.set('');
  searchMatches.set([]);
  searchIdx.set(-1);
}

// --- Batch OCR state ---
export const batchActive = writable(false);
export const batchId = writable<string | null>(null);
export const batchStatus = writable<'idle' | 'running' | 'completed' | 'cancelled' | 'error'>('idle');
export const batchTotal = writable(0);
export const batchDone = writable(0);
export const batchCurrent = writable('');
export const batchElapsed = writable(0);
export const batchResults = writable<any[]>([]);
export const batchOutputPath = writable('');
