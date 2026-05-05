# -*- coding: utf-8 -*-
"""Layout detection — public API: detect_layout()."""
from PIL import Image

from .model import detect_raw, is_loaded
from .columns import sort_by_columns, fill_column_gaps
from ..config import logger


def detect_layout(img: Image.Image) -> list[dict]:
    """Detect document layout regions using PP-DocLayoutV3.
    Returns [{label, bbox: [x1,y1,x2,y2], score}] sorted by reading order.
    """
    regions = detect_raw(img)

    # Sort by column-aware reading order
    regions = sort_by_columns(regions, img.size[0])

    # Fill gaps between full-width bottom and each column's first region
    regions = fill_column_gaps(regions, img.size[0])

    logger.info(f"[layout] Detected {len(regions)} regions")
    return regions
