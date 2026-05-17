"""
studyfocus/pdf_preview.py — Panel podglądu PDF z zaawansowanym sterowaniem.
"""

from __future__ import annotations

import logging
import os
import threading
import tkinter as tk
from typing import Any, Optional, Tuple, Literal, Callable

import customtkinter as ctk
from PIL import Image, ImageTk

try:
    import fitz
except ImportError:
    fitz = None

logger = logging.getLogger("studyfocus.pdf_preview")

_BG_CANVAS = "#111111"
_CTRL_BG = "#161616"

ZoomMode = Literal["fit_page", "fit_width", "fixed_100", "fixed_200", "two_pages"]
ZOOM_OPTIONS_MAP = {
    "Dopasuj całą stronę": "fit_page",
    "Dopasuj do szerokości": "fit_width",
    "Zoom 100%": "fixed_100",
    "Zoom 200%": "fixed_200",
    "Dwie strony (obok siebie)": "two_pages",
}

class PdfPreviewPanel(ctk.CTkFrame):
    def __init__(self, parent: Any, **kwargs) -> None:
        super().__init__(parent, **kwargs)
        self.configure(fg_color="#0a0a0a")

        self._doc: Optional[fitz.Document] = None
        self._current_page_idx = 0
        self._total_pages = 0
        self._rotation = 0
        self._current_zoom_mode: ZoomMode = "fit_page"
        self._current_image_ref: Optional[ImageTk.PhotoImage] = None

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Canvas i Scrollbar
        mid_fr = ctk.CTkFrame(self, fg_color="transparent")
        mid_fr.grid(row=0, column=0, sticky="nsew")
        mid_fr.grid_columnconfigure(0, weight=1)
        mid_fr.grid_rowconfigure(0, weight=1)

        self._v_scroll = tk.Scrollbar(mid_fr, orient="vertical")
        self._v_scroll.grid(row=0, column=1, sticky="ns")

        self._canvas = tk.Canvas(mid_fr, bg=_BG_CANVAS, yscrollcommand=self._v_scroll.set, highlightthickness=0)
        self._canvas.grid(row=0, column=0, sticky="nsew")
        self._v_scroll.config(command=self._canvas.yview)
        self._canvas.bind("<Configure>", lambda e: self.after(100, self._render_current_view))

        # Pasek kontrolny
        self._ctrl = ctk.CTkFrame(self, fg_color=_CTRL_BG, height=50, corner_radius=0)
        self._ctrl.grid(row=1, column=0, sticky="ew")
        
        # Nawigacja (lewa)
        nav_fr = ctk.CTkFrame(self._ctrl, fg_color="transparent")
        nav_fr.pack(side="left", padx=10)

        self._btn_prev = self._create_btn(nav_fr, "←", self._load_prev_view)
        self._btn_prev.pack(side="left", padx=2)
        self._create_btn(nav_fr, "↺", lambda: self._rotate(-90)).pack(side="left", padx=2)
        self._create_btn(nav_fr, "↻", lambda: self._rotate(90)).pack(side="left", padx=2)
        self._btn_next = self._create_btn(nav_fr, "→", self._load_next_view)
        self._btn_next.pack(side="left", padx=2)

        # Info (środek)
        self._lbl_info = ctk.CTkLabel(self._ctrl, text="Brak dokumentu", font=ctk.CTkFont(size=13, weight="bold"))
        self._lbl_info.pack(side="left", expand=True)

        # Zoom (prawa)
        zoom_fr = ctk.CTkFrame(self._ctrl, fg_color="transparent")
        zoom_fr.pack(side="right", padx=10)

        self._zoom_choice = ctk.StringVar(value="Dopasuj całą stronę")
        self._zoom_menu = ctk.CTkOptionMenu(zoom_fr, variable=self._zoom_choice, values=list(ZOOM_OPTIONS_MAP.keys()),
                                            width=180, command=self._on_zoom_mode_changed)
        self._zoom_menu.pack(side="left")

    def _create_btn(self, parent: Any, text: str, cmd: Callable) -> ctk.CTkButton:
        return ctk.CTkButton(parent, text=text, width=40, height=32, fg_color="#222", command=cmd)

    def load_pdf(self, path: str, max_width: int) -> None:
        self._doc = None
        self._canvas.delete("all")
        if not path or not os.path.isfile(path) or fitz is None:
            self._lbl_info.configure(text="Błąd pliku")
            return

        def _worker():
            try:
                doc = fitz.open(path)
                self._doc = doc
                self._total_pages = len(doc)
                self._current_page_idx = 0
                self.after(10, self._render_current_view)
            except:
                self.after(10, lambda: self._lbl_info.configure(text="Błąd PDF"))
        threading.Thread(target=_worker, daemon=True).start()

    def _render_current_view(self) -> None:
        if not self._doc: return
        if self._current_zoom_mode == "two_pages":
            self._render_double()
        else:
            self._render_single()

    def _render_single(self) -> None:
        try:
            pil_img = self._get_page_image(self._current_page_idx)
            if pil_img:
                self._display(self._scale_pil(pil_img))
                self._lbl_info.configure(text=f"Strona {self._current_page_idx+1} / {self._total_pages}")
        except: pass
        self._update_btns()

    def _render_double(self) -> None:
        try:
            p1 = self._get_page_image(self._current_page_idx)
            p2 = self._get_page_image(self._current_page_idx+1) if self._current_page_idx+1 < self._total_pages else None
            
            w = p1.width + (p2.width if p2 else 0)
            h = max(p1.height, p2.height if p2 else 0)
            comp = Image.new("RGB", (w, h), _BG_CANVAS)
            comp.paste(p1, (0, (h-p1.height)//2))
            if p2: comp.paste(p2, (p1.width, (h-p2.height)//2))
            
            self._display(self._scale_pil(comp, force_fit=True))
            end = self._current_page_idx + (2 if p2 else 1)
            self._lbl_info.configure(text=f"Strony {self._current_page_idx+1}-{end} / {self._total_pages}")
        except: pass
        self._update_btns()

    def _get_page_image(self, idx: int) -> Image.Image:
        page = self._doc.load_page(idx)
        pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5).prerotate(self._rotation))
        return Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

    def _scale_pil(self, img: Image.Image, force_fit: bool = False) -> Image.Image:
        can_w = max(self._canvas.winfo_width() - 20, 600)
        can_h = max(self._canvas.winfo_height() - 20, 400)
        iw, ih = img.size
        mode = "fit_page" if force_fit else self._current_zoom_mode
        
        if mode == "fit_page": scale = min(can_w/iw, can_h/ih)
        elif mode == "fit_width": scale = can_w/iw
        elif mode == "fixed_100": scale = 0.66
        elif mode == "fixed_200": scale = 1.33
        else: scale = min(can_w/iw, can_h/ih)

        return img.resize((int(iw*scale), int(ih*scale)), Image.Resampling.LANCZOS)

    def _display(self, img: Image.Image) -> None:
        self._current_image_ref = ImageTk.PhotoImage(img)
        self._canvas.delete("all")
        self._canvas.create_image(self._canvas.winfo_width()//2, 0, image=self._current_image_ref, anchor="n")
        self._canvas.config(scrollregion=(0, 0, img.width, img.height))

    def _update_btns(self) -> None:
        step = 2 if self._current_zoom_mode == "two_pages" else 1
        self._btn_prev.configure(state="normal" if self._current_page_idx > 0 else "disabled")
        self._btn_next.configure(state="normal" if self._current_page_idx + step < self._total_pages else "disabled")

    def _load_prev_view(self) -> None:
        step = 2 if self._current_zoom_mode == "two_pages" else 1
        self._current_page_idx = max(0, self._current_page_idx - step)
        self._render_current_view()

    def _load_next_view(self) -> None:
        step = 2 if self._current_zoom_mode == "two_pages" else 1
        if self._current_page_idx + step < self._total_pages:
            self._current_page_idx += step
            self._render_current_view()

    def _rotate(self, deg: int) -> None:
        self._rotation = (self._rotation + deg) % 360
        self._render_current_view()

    def _on_zoom_mode_changed(self, choice: str) -> None:
        self._current_zoom_mode = ZOOM_OPTIONS_MAP.get(choice, "fit_page")
        self._canvas.yview_moveto(0)
        self._render_current_view()