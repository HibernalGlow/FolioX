# -*- coding: utf-8 -*-
"""OCR postprocessing — markdown cleanup, LaTeX conversion, dedup."""
import re
from html.parser import HTMLParser

from ..config import logger, LATEX_SIMPLE, LATEX_FRACTIONS, CIRCLED


def postprocess(text: str) -> str:
    """Strip markdown fences and convert LaTeX to Unicode."""
    text = re.sub(r'^```\w*\n?', '', text.strip())
    text = re.sub(r'\n?```$', '', text.strip())
    text = flatten_simple_tables(text)
    text = remove_duplicate_display_math(text)
    text = latex_to_unicode(text)
    text = dedup_lines(text)
    return text.strip()


def flatten_simple_tables(text: str) -> str:
    """Convert simple HTML tables (text-only cells) into plain text."""
    def _replace_table(m):
        html = m.group(0)
        if '<table' in html[7:] or '<img' in html.lower():
            return html
        parser = TableParser()
        parser.feed(html)
        if not parser.rows:
            return html
        lines = []
        for row in parser.rows:
            cells = [c for c in row if c.strip()]
            if cells:
                lines.append(" ".join(cells))
        return "\n".join(lines)

    return re.sub(r'<table[\s\S]*?</table>', _replace_table, text, flags=re.IGNORECASE)


def remove_duplicate_display_math(text: str) -> str:
    """Remove $$...$$ display math lines that duplicate $...$ inline math content."""
    lines = text.split('\n')
    inline_contents = set()
    for line in lines:
        for m in re.finditer(r'\$([^$]+)\$', line):
            normalized = re.sub(r'\s+', '', m.group(1))
            inline_contents.add(normalized)

    result = []
    for line in lines:
        stripped = line.strip()
        m = re.match(r'^\$\$(.+)\$\$$', stripped)
        if m:
            normalized = re.sub(r'\s+', '', m.group(1))
            if normalized in inline_contents:
                continue
        result.append(line)
    return '\n'.join(result)


def dedup_lines(text: str) -> str:
    """Remove lines whose normalized content is a substring of any earlier line."""
    lines = text.split('\n')
    if len(lines) <= 1:
        return text

    result = [lines[0]]
    seen_norms = [re.sub(r'\s+', '', lines[0])]

    for line in lines[1:]:
        curr_norm = re.sub(r'\s+', '', line)
        if not curr_norm:
            result.append(line)
            continue

        is_dup = False
        for prev_norm in seen_norms:
            if curr_norm == prev_norm:
                is_dup = True
                break
            if len(curr_norm) > 2 and curr_norm in prev_norm:
                is_dup = True
                break
        if is_dup:
            continue

        result.append(line)
        seen_norms.append(curr_norm)

    return '\n'.join(result)


def latex_to_unicode(text: str) -> str:
    """Replace LaTeX notation with Unicode characters."""
    # 1. \textcircled{N} → ①②③...
    text = re.sub(
        r'\$\\textcircled\{(\d+)\}\$',
        lambda m: CIRCLED.get(m.group(1), m.group(0)),
        text,
    )

    # 2. \frac{a}{b} → Unicode fraction or a/b
    def _replace_frac(m):
        num, den = m.group(1), m.group(2)
        key = f"{num}/{den}"
        return LATEX_FRACTIONS.get(key, f"{num}/{den}")

    text = re.sub(r'\$\\frac\{([^}]+)\}\{([^}]+)\}\$', _replace_frac, text)

    # 3. Inline math $...$ and display math $$...$$
    text = re.sub(r'\$\$(.+?)\$\$', lambda m: _convert_math_interior(m.group(1)), text, flags=re.DOTALL)
    text = re.sub(r'\$(.+?)\$', lambda m: _convert_math_interior(m.group(1)), text)

    # 4. Simple $\command$ → Unicode (longest match first)
    for latex_cmd, unicode_char in LATEX_SIMPLE:
        token = f"${latex_cmd}$"
        if token in text:
            text = text.replace(token, unicode_char)

    # 5. Remaining bare $\command$ — unwrap delimiters
    text = re.sub(r'\$\\([a-zA-Z]+)\$', lambda m: '\\' + m.group(1), text)

    return text


def _convert_math_interior(math: str) -> str:
    """Convert LaTeX math content to Unicode plain text."""
    s = math.strip()

    s = re.sub(r'\^\{\\circ\}', '°', s)
    s = re.sub(r'\^\\circ', '°', s)

    s = re.sub(r'\^\{([^}]+)\}', lambda m: m.group(1), s)
    s = re.sub(r'\^(\d)', lambda m: m.group(1), s)

    s = re.sub(r'_\{([^}]+)\}', lambda m: m.group(1), s)
    s = re.sub(r'_(\d)', lambda m: m.group(1), s)

    for latex_cmd, unicode_char in LATEX_SIMPLE:
        if latex_cmd in s:
            s = s.replace(latex_cmd, unicode_char)

    s = s.replace('{', '').replace('}', '')
    s = re.sub(r'(\d)\s+(\d)', r'\1\2', s)
    s = re.sub(r' {2,}', ' ', s)

    return s.strip()


class TableParser(HTMLParser):
    """Extract rows/cells from an HTML <table>."""
    def __init__(self):
        super().__init__()
        self.rows: list[list[str]] = []
        self._in_cell = False
        self._cell_text = ""
        self._current_row: list[str] = []
        self._is_header_row = False
        self.header_row_indices: set[int] = set()

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag == "tr":
            self._current_row = []
            self._is_header_row = False
        elif tag in ("td", "th"):
            self._in_cell = True
            self._cell_text = ""
            if tag == "th":
                self._is_header_row = True

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in ("td", "th"):
            self._in_cell = False
            self._current_row.append(self._cell_text.strip())
        elif tag == "tr":
            if self._current_row:
                if self._is_header_row:
                    self.header_row_indices.add(len(self.rows))
                self.rows.append(self._current_row)

    def handle_data(self, data):
        if self._in_cell:
            self._cell_text += data
