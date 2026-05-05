# -*- coding: utf-8 -*-
"""Route registration — include all routers."""
from fastapi import APIRouter

from .status import router as status_router
from .upload import router as upload_router
from .ocr import router as ocr_router
from .documents import router as documents_router
from .export import router as export_router

# Collect all routers for app inclusion
all_routers = [
    status_router,
    upload_router,
    ocr_router,
    documents_router,
    export_router,
]
