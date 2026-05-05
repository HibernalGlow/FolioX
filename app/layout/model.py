# -*- coding: utf-8 -*-
"""Layout detection model — lazy loading and inference."""
import time

from ..config import logger, LAYOUT_MODEL_NAME, LAYOUT_THRESHOLD, LAYOUT_SKIP_LABELS

# Module-level model state (lazy loaded)
_processor = None
_model = None


def ensure_model():
    """Lazy-load torch + transformers + layout model on first use."""
    global _processor, _model
    if _model is not None:
        return
    import torch
    from transformers import RTDetrImageProcessor, AutoModelForObjectDetection
    t0 = time.time()
    logger.info(f"[layout] Loading {LAYOUT_MODEL_NAME}...")
    _processor = RTDetrImageProcessor.from_pretrained(LAYOUT_MODEL_NAME)
    _model = AutoModelForObjectDetection.from_pretrained(LAYOUT_MODEL_NAME)
    if torch.cuda.is_available():
        _model.to("cuda")
        logger.info(f"[layout] Model loaded on CUDA: {time.time() - t0:.2f}s")
    else:
        logger.info(f"[layout] Model loaded on CPU: {time.time() - t0:.2f}s")
    _model.eval()


def is_loaded() -> bool:
    """Return True if the layout model has been loaded."""
    return _model is not None


def detect_raw(img):
    """Run layout detection on a PIL Image.
    Returns [{label, bbox: [x1,y1,x2,y2], score}] (unsorted, unfiltered).
    """
    import torch
    ensure_model()
    device = next(_model.parameters()).device
    inputs = _processor(images=img, return_tensors="pt")
    inputs = {k: v.to(device) for k, v in inputs.items()}

    with torch.no_grad():
        outputs = _model(**inputs)

    target_sizes = torch.tensor([img.size[::-1]], device=device)  # (height, width)
    results = _processor.post_process_object_detection(
        outputs, target_sizes=target_sizes, threshold=LAYOUT_THRESHOLD
    )[0]

    regions = []
    id2label = _model.config.id2label
    for score, label_id, box in zip(results["scores"], results["labels"], results["boxes"]):
        label = id2label[label_id.item()]
        if label in LAYOUT_SKIP_LABELS:
            continue
        bbox = [round(c) for c in box.tolist()]
        regions.append({"label": label, "bbox": bbox, "score": round(score.item(), 3)})

    return regions
