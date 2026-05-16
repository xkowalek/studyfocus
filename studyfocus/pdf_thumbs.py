"""Miniaturka pierwszej strony PDF jako CTkImage."""

from __future__ import annotations

import io
from typing import Optional, Tuple

import customtkinter as ctk
import fitz
from PIL import Image


def pdf_first_page_ctk_image(path: str, max_side: int = 108) -> Optional[Tuple[ctk.CTkImage, int, int]]:
    try:
        doc = fitz.open(path)
        try:
            page = doc.load_page(0)
            rect = page.rect
            scale = max_side / max(rect.width, rect.height, 1)
            if scale > 2.0:
                scale = 2.0
            mat = fitz.Matrix(scale, scale)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            img = Image.open(io.BytesIO(pix.tobytes("png")))
        finally:
            doc.close()
        w, h = img.size
        ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=(w, h))
        return (ctk_img, w, h)
    except Exception:
        return None
