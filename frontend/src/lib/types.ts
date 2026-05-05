export interface Page {
  num: number;
  filename: string;
  image_url: string;
  ocr_text: string | null;
  ocr_regions: OcrRegion[] | null;
  ocr_time: number | null;
}

export interface OcrRegion {
  idx: number;
  label: string;
  bbox: number[]; // [x1, y1, x2, y2]
  text: string;
  score?: number;
}

export interface DocItem {
  doc_id: string;
  filename: string;
  page_count: number;
  ocr_count: number;
  created_at: string;
}

export interface DocDetail {
  doc_id: string;
  filename: string;
  created_at: string;
  pages: Page[];
}

export interface StatusResponse {
  status: string;
  model_loaded: boolean;
  layout_loaded: boolean;
  device: string;
  gpu: { name: string } | null;
}

export interface OcrResponse {
  doc_id: string;
  page_num: number;
  text: string;
  regions: OcrRegion[];
  time: number;
  cached: boolean;
}

export interface SearchMatch {
  pageNum: number;
  count: number;
}

export interface Toast {
  id: number;
  message: string;
  type: 'error' | 'warn' | 'success';
}
