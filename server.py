# -*- coding: utf-8 -*-
"""
Folio-OCR Server — entry point.
Usage: python server.py
"""
import os
import uvicorn
from app import app

if __name__ == "__main__":
    port = int(os.environ.get("FOLIO_PORT", 3000))
    uvicorn.run(app, host="0.0.0.0", port=port)
