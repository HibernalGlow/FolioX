/** Escape HTML special characters */
export function escHtml(s: string): string {
  return (s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

/** Format seconds remaining */
export function formatEta(seconds: number): string {
  if (seconds < 60) return Math.round(seconds) + 's';
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return m + 'm' + (s > 0 ? s.toString().padStart(2, '0') + 's' : '');
}

/** Simple markdown → HTML conversion (headings, bold, italic, tables) */
export function markdownToHtml(text: string): string {
  let html = '';
  const lines = text.split('\n');
  let inTable = false;
  let tableRows: string[] = [];

  function flushTable() {
    if (tableRows.length === 0) return;
    html += '<table>';
    for (let i = 0; i < tableRows.length; i++) {
      const cleanCells = tableRows[i].replace(/^\||\|$/g, '').split('|').map(c => c.trim());
      if (cleanCells.every(c => /^[-:]+$/.test(c))) continue;
      const tag = i === 0 ? 'th' : 'td';
      html += '<tr>' + cleanCells.map(c => `<${tag}>${escHtml(c)}</${tag}>`).join('') + '</tr>';
    }
    html += '</table>';
    tableRows = [];
    inTable = false;
  }

  for (const line of lines) {
    const trimmed = line.trim();

    if (trimmed.includes('|') && (trimmed.startsWith('|') || trimmed.match(/\w\s*\|/))) {
      inTable = true;
      tableRows.push(trimmed);
      continue;
    }

    if (inTable) flushTable();

    if (trimmed.startsWith('### ')) {
      html += `<h3>${escHtml(trimmed.slice(4))}</h3>`;
    } else if (trimmed.startsWith('## ')) {
      html += `<h2>${escHtml(trimmed.slice(3))}</h2>`;
    } else if (trimmed.startsWith('# ')) {
      html += `<h1>${escHtml(trimmed.slice(2))}</h1>`;
    } else if (trimmed === '') {
      html += '<br>';
    } else {
      let s = escHtml(trimmed);
      s = s.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
      s = s.replace(/\*(.+?)\*/g, '<em>$1</em>');
      html += `<p>${s}</p>`;
    }
  }
  if (inTable) flushTable();
  return html;
}

/** Render preview HTML from OCR text + optional search query */
export function renderPreview(text: string, searchQuery = ''): string {
  if (!text) return '<span style="color:rgba(45,45,45,0.3)">No text recognized</span>';

  const parts = text.split(/(<table[\s\S]*?<\/table>)/gi);
  let html = '';

  for (const part of parts) {
    if (part.match(/^<table[\s\S]*<\/table>$/i)) {
      html += searchQuery ? highlightHtml(part, searchQuery) : part;
    } else {
      let rendered = markdownToHtml(part);
      if (searchQuery) rendered = highlightHtml(rendered, searchQuery);
      html += rendered;
    }
  }
  return html;
}

/** Render region blocks for preview */
export function renderRegionBlocks(regions: { idx: number; text: string }[], searchQuery = ''): string {
  return regions
    .filter(r => r.text && r.text.trim())
    .map(r => {
      const rendered = renderPreview(r.text || '', searchQuery);
      return `<div class="region-block" data-idx="${r.idx}">${rendered}</div>`;
    })
    .join('');
}

/** Highlight search matches in rendered HTML (text nodes only) */
export function highlightHtml(html: string, query: string): string {
  if (!query) return html;
  const parts = html.split(/(<[^>]+>)/g);
  const esc = query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const re = new RegExp(`(${esc})`, 'gi');
  for (let i = 0; i < parts.length; i++) {
    if (!parts[i].startsWith('<')) {
      parts[i] = parts[i].replace(re, '<mark>$1</mark>');
    }
  }
  return parts.join('');
}

/** Build Markdown content from pages */
export function buildMarkdown(pages: { num: number; ocr_text: string | null }[], filename: string | null): string {
  const pagesWithText = pages.filter(p => p.ocr_text);
  if (pagesWithText.length === 0) return '';
  const title = filename || 'Document';

  if (pagesWithText.length === 1 && pages.length === 1) {
    return pagesWithText[0].ocr_text!;
  }

  let md = `# ${title}\n\n`;
  for (const p of pages) {
    md += `## Page ${p.num}\n\n`;
    md += (p.ocr_text || '*(not recognized)*') + '\n\n';
  }
  return md.trim();
}

/** Build plain text content from pages */
export function buildPlainText(pages: { num: number; ocr_text: string | null }[]): string {
  const pagesWithText = pages.filter(p => p.ocr_text);
  if (pagesWithText.length === 0) return '';
  if (pages.length === 1) return pages[0].ocr_text || '';

  return pages.map(p => {
    const text = p.ocr_text || '(not recognized)';
    return `--- Page ${p.num} ---\n\n${text}`;
  }).join('\n\n\n');
}

/** Class name merge utility */
export function cn(...classes: (string | false | null | undefined)[]): string {
  return classes.filter(Boolean).join(' ');
}
