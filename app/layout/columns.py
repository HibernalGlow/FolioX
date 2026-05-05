# -*- coding: utf-8 -*-
"""Column detection, sorting, gap filling, and region merging."""
import re

from ..config import logger, LAYOUT_SOLO_LABELS


def detect_columns(regions: list[dict], img_width: int) -> list[list[dict]]:
    """Detect multi-column layout by clustering region x-centers.
    Returns list of columns (each a list of regions), left-to-right.
    Full-width regions are returned as a special first "column".
    """
    if not regions:
        return []

    FULL_WIDTH_RATIO = 0.6
    FULL_WIDTH_LABELS = {"doc_title", "paragraph_title", "title", "section_title"}
    full_width = []
    narrow = []

    img_center = img_width / 2
    CENTER_TOLERANCE = 0.15
    MAX_SUBTITLE_HEIGHT = 50

    for r in regions:
        x1, y1, x2, y2 = r["bbox"]
        width = x2 - x1
        if width > img_width * FULL_WIDTH_RATIO or r["label"] in FULL_WIDTH_LABELS:
            full_width.append(r)
        else:
            narrow.append(r)

    has_titles = any(r["label"] in FULL_WIDTH_LABELS for r in full_width)
    if has_titles:
        still_narrow = []
        for r in narrow:
            x1, y1, x2, y2 = r["bbox"]
            width = x2 - x1
            height = y2 - y1
            cx = (x1 + x2) / 2
            is_centered = abs(cx - img_center) < img_width * CENTER_TOLERANCE
            is_single_line = height <= MAX_SUBTITLE_HEIGHT
            if is_centered and width < img_width * 0.45 and is_single_line:
                full_width.append(r)
            else:
                still_narrow.append(r)
        narrow = still_narrow

    if not narrow:
        return [full_width] if full_width else []

    centers = [(r["bbox"][0] + r["bbox"][2]) / 2 for r in narrow]
    columns = _cluster_columns(narrow, centers, img_width)
    columns.sort(key=lambda col: sum((r["bbox"][0] + r["bbox"][2]) / 2 for r in col) / len(col))

    for col in columns:
        col.sort(key=lambda r: r["bbox"][1])

    if full_width:
        full_width.sort(key=lambda r: r["bbox"][1])
        for r in full_width:
            r["_column"] = 0

    for ci, col in enumerate(columns):
        for r in col:
            r["_column"] = ci + (1 if full_width else 0)

    result = []
    if full_width:
        result.append(full_width)
    result.extend(columns)
    return result


def _cluster_columns(regions: list[dict], centers: list[float], img_width: int) -> list[list[dict]]:
    """Simple 1D clustering of regions into columns by x-center."""
    GAP_RATIO = 0.15
    gap_threshold = img_width * GAP_RATIO

    indexed = sorted(enumerate(regions), key=lambda t: centers[t[0]])
    columns: list[list[dict]] = []
    current_col: list[dict] = [indexed[0][1]]
    prev_center = centers[indexed[0][0]]

    for idx, region in indexed[1:]:
        c = centers[idx]
        if c - prev_center > gap_threshold:
            columns.append(current_col)
            current_col = [region]
        else:
            current_col.append(region)
        prev_center = c

    columns.append(current_col)
    return columns


def sort_by_columns(regions: list[dict], img_width: int) -> list[dict]:
    """Sort regions by column-aware reading order."""
    columns = detect_columns(regions, img_width)

    if len(columns) <= 1:
        regions.sort(key=lambda r: (r["bbox"][1], r["bbox"][0]))
        return regions

    sorted_regions = []
    for col in columns:
        sorted_regions.extend(col)

    logger.info(
        f"[layout] Detected {len(columns)} columns "
        f"({', '.join(str(len(c)) + ' regions' for c in columns)})"
    )
    return sorted_regions


def fill_column_gaps(regions: list[dict], img_width: int) -> list[dict]:
    """Insert synthetic regions to cover gaps between the full-width area bottom
    and each column's first detected region.
    """
    if not regions:
        return regions

    has_fullwidth = any(
        r.get("_column") == 0
        and (
            r.get("label") in {"doc_title", "paragraph_title", "title", "section_title"}
            or (r["bbox"][2] - r["bbox"][0]) > img_width * 0.6
        )
        for r in regions
    )
    fullwidth_bottom = 0
    if has_fullwidth:
        for r in regions:
            if r.get("_column") == 0:
                fullwidth_bottom = max(fullwidth_bottom, r["bbox"][3])

    if fullwidth_bottom == 0:
        return regions

    col_regions: dict[int, list[dict]] = {}
    for r in regions:
        col = r.get("_column")
        if col is not None and col > 0:
            col_regions.setdefault(col, []).append(r)

    gap_regions = []
    MIN_GAP = 15

    for col_id, col_regs in col_regions.items():
        first = col_regs[0]
        first_y = first["bbox"][1]

        if first_y - fullwidth_bottom > MIN_GAP:
            x1 = min(r["bbox"][0] for r in col_regs)
            x2 = max(r["bbox"][2] for r in col_regs)
            gap_bbox = [x1, fullwidth_bottom, x2, first_y]
            gap_region = {
                "label": "text",
                "bbox": gap_bbox,
                "score": 0.5,
                "_column": col_id,
                "_synthetic": True,
            }
            gap_regions.append(gap_region)
            logger.info(f"[layout] Filled gap in column {col_id}: y={fullwidth_bottom}-{first_y}")

    if not gap_regions:
        return regions

    result = []
    inserted_cols = set()
    for r in regions:
        col = r.get("_column")
        if col is not None and col > 0 and col not in inserted_cols:
            for gr in gap_regions:
                if gr["_column"] == col:
                    result.append(gr)
            inserted_cols.add(col)
        result.append(r)

    return result


def merge_adjacent_regions(raw_regions: list[dict]) -> list[list[dict]]:
    """Group adjacent non-solo regions into merge groups.
    Returns list of groups, where each group is a list of raw regions.
    """
    groups: list[list[dict]] = []
    current: list[dict] = []

    for region in raw_regions:
        if region["label"] in LAYOUT_SOLO_LABELS:
            if current:
                groups.append(current)
                current = []
            groups.append([region])
        else:
            if current and current[-1].get("_column") != region.get("_column"):
                groups.append(current)
                current = []
            current.append(region)

    if current:
        groups.append(current)
    return groups


def group_bbox(regions: list[dict]) -> list[int]:
    """Compute the bounding box that encompasses all regions."""
    x1 = min(r["bbox"][0] for r in regions)
    y1 = min(r["bbox"][1] for r in regions)
    x2 = max(r["bbox"][2] for r in regions)
    y2 = max(r["bbox"][3] for r in regions)
    return [x1, y1, x2, y2]


def dedup_regions(regions: list[dict]) -> list[dict]:
    """Remove regions whose text is entirely contained in another region's text."""
    if len(regions) <= 1:
        return regions
    norms = [re.sub(r'\s+', '', r.get('text', '')) for r in regions]
    keep = []
    for i, region in enumerate(regions):
        if not norms[i]:
            continue
        is_dup = False
        for j, other_norm in enumerate(norms):
            if i == j or not other_norm:
                continue
            if len(norms[i]) < len(other_norm) and norms[i] in other_norm:
                is_dup = True
                break
        if not is_dup:
            keep.append(region)
    for i, r in enumerate(keep):
        r['idx'] = i
    return keep
