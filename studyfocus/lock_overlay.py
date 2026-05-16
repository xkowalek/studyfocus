"""Pełnoekranowa nakładka blokady: odliczanie, Sesja/PDF, nieprzezroczyste tło, strażnik fokusu."""

from __future__ import annotations

import os
import sys
import threading
import tkinter as tk
from typing import Any, Callable, List, Optional

import customtkinter as ctk

from studyfocus.calc_allow import (
    apply_overlay_topmost_win32,
    calc_support_available,
    clear_calculator_topmost,
    clear_overlay_topmost_win32,
    launch_calculator,
    should_refocus_study_overlay,
    start_calc_elevator,
)
from studyfocus.emergency_exit import EmergencyExitFlow
from studyfocus.pdf_preview import PdfPreviewPanel

_BG = "#040404"
_BG_PANEL = "#0a0a0a"

class LockOverlay(ctk.CTkToplevel):
    def __init__(
        self,
        master: ctk.CTk,
        duration_seconds: int,
        pdf_paths: Optional[List[str]] = None,
        on_close: Optional[Callable[[], None]] = None,
    ) -> None:
        super().__init__(master)
        self._on_close = on_close
        self._pdf_paths = list(pdf_paths or [])
        
        # PRZYWRÓCONA LOGIKA KALKULATORA
        self._elev_stop = threading.Event()
        self._elev_thread: Optional[threading.Thread] = None
        self._overlay_tk_hwnd = 0
        self._overlay_root_hwnd = 0
        self._focus_guard_id: Any = None
        self._emergency_active = False

        self._remaining = max(0, int(duration_seconds))
        self._finished = False
        self._tick_after_id: Any = None

        self.title("StudyFocus — blokada")
        self.configure(fg_color=_BG)
        self.protocol("WM_DELETE_WINDOW", self._request_early_exit)

        # Ustawienia pełnego ekranu i wierzchu
        self.attributes("-fullscreen", True)
        self.attributes("-topmost", True)

        # GŁÓWNY KONTENER
        outer = ctk.CTkFrame(self, fg_color=_BG)
        outer.pack(fill="both", expand=True)

        # PRZYCISK WYJŚCIA NA SAMYM DOLE (Zmiana wizualna)
        end_row = ctk.CTkFrame(outer, fg_color=_BG)
        end_row.pack(side="bottom", fill="x", pady=20)
        ctk.CTkButton(
            end_row,
            text="PRZERWIJ SESJĘ",
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#333",
            hover_color="#c0392b",
            width=200,
            command=self._request_early_exit,
        ).pack()

        self._tabs: Optional[ctk.CTkTabview] = None
        self._pdf_tab_name: Optional[str] = None

        if self._pdf_paths:
            self._tabs = ctk.CTkTabview(
                outer,
                fg_color=_BG_PANEL,
                segmented_button_selected_color="#1f6f4a",
                segmented_button_unselected_color="#252525",
            )
            self._tabs.pack(side="top", fill="both", expand=True, padx=16, pady=12)

            tab_session = self._tabs.add("Sesja")
            self._pdf_tab_name = "Materiały PDF"
            tab_pdf = self._tabs.add(self._pdf_tab_name)

            self._build_session_tab(tab_session, show_pdf_jump=True)
            self._build_pdf_tab(tab_pdf)
            self.after(0, self._enlarge_tab_buttons)
        else:
            body = ctk.CTkFrame(outer, fg_color=_BG)
            body.pack(side="top", fill="both", expand=True, padx=16, pady=12)
            self._build_session_tab(body, show_pdf_jump=False)

        # Uruchomienie logiki i strażników
        if sys.platform == "win32":
            self.after(100, self._sync_win32_topmost)

        self._tick()

        if calc_support_available():
            self.after(500, self._start_elevator)

        self.lift()
        self.focus_force()

    def _enlarge_tab_buttons(self) -> None:
        if not self._tabs: return
        try:
            self._tabs._segmented_button.configure(height=50, font=ctk.CTkFont(size=18, weight="bold"))
        except Exception: pass

    def _sync_win32_topmost(self) -> None:
        if self._finished or sys.platform != "win32": return
        try:
            self.update_idletasks()
            self._overlay_tk_hwnd = int(self.winfo_id())
            self._overlay_root_hwnd = apply_overlay_topmost_win32(self._overlay_tk_hwnd)
        except Exception: pass

    def _build_session_tab(self, parent: Any, *, show_pdf_jump: bool) -> None:
        ctk.CTkLabel(parent, text="POZOSTAŁY CZAS", font=ctk.CTkFont(size=16), text_color="#555").pack(pady=(60, 5))

        self._timer_label = ctk.CTkLabel(parent, text="--:--", font=ctk.CTkFont(size=100, weight="bold"))
        self._timer_label.pack(pady=10)

        btn_fr = ctk.CTkFrame(parent, fg_color="transparent")
        btn_fr.pack(pady=50)

        ctk.CTkButton(btn_fr, text="KALKULATOR", width=220, height=60, font=ctk.CTkFont(size=16, weight="bold"),
                      command=launch_calculator).pack(side="left", padx=15)

        if show_pdf_jump:
            ctk.CTkButton(btn_fr, text="MOJE NOTATKI", width=220, height=60, fg_color="#1f6f4a",
                          font=ctk.CTkFont(size=16, weight="bold"),
                          command=lambda: self._tabs.set(self._pdf_tab_name)).pack(side="left", padx=15)

    def _build_pdf_tab(self, parent: Any) -> None:
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(1, weight=1)

        # PRZYWRÓCONE MENU WYBORU PDF
        head = ctk.CTkFrame(parent, fg_color=_BG_PANEL)
        head.grid(row=0, column=0, sticky="ew", padx=10, pady=10)

        if len(self._pdf_paths) > 1:
            labels = [os.path.basename(p) for p in self._pdf_paths]
            self._pdf_selector = ctk.CTkOptionMenu(head, values=labels, width=300,
                                                   command=lambda c: self._load_overlay_pdf(self._pdf_paths[labels.index(c)]))
            self._pdf_selector.pack(side="left", padx=10, pady=5)

        self._pdf_panel = PdfPreviewPanel(parent)
        self._pdf_panel.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0,10))
        self._load_overlay_pdf(self._pdf_paths[0])

    def _load_overlay_pdf(self, path: str) -> None:
        if hasattr(self, "_pdf_panel"):
            self._pdf_panel.load_pdf(path, max_width=self.winfo_screenwidth()-120)

    def _format_time(self, sec: int) -> str:
        m, s = divmod(max(0, sec), 60)
        return f"{m:02d}:{s:02d}"

    def _tick(self) -> None:
        if self._finished: return

        if not self._emergency_active:
            self._remaining -= 1
            if self._remaining <= 0:
                self._finish_impl()
                return

            if hasattr(self, "_timer_label"):
                self._timer_label.configure(text=self._format_time(self._remaining))

        self._tick_after_id = self.after(1000, self._tick)

    # PRZYWRÓCONE STRAŻNIKI KALKULATORA
    def _run_focus_guard(self) -> None:
        if self._finished: return
        if sys.platform == "win32" and should_refocus_study_overlay(self._overlay_root_hwnd):
            self.lift()
        self._focus_guard_id = self.after(1500, self._run_focus_guard)

    def _start_elevator(self) -> None:
        if not calc_support_available(): return
        self._sync_win32_topmost()
        self._elev_stop.clear()
        self._elev_thread = start_calc_elevator(self._elev_stop, self._overlay_tk_hwnd)
        self._run_focus_guard()

    def _request_early_exit(self) -> None:
        if self._finished or self._emergency_active: return
        self._emergency_active = True
        EmergencyExitFlow(self, self._finish_impl, self._abort_exit).start()

    def _abort_exit(self) -> None:
        self._emergency_active = False

    def _finish_impl(self) -> None:
        self._finished = True
        self._elev_stop.set()
        if calc_support_available():
            clear_calculator_topmost()
            if sys.platform == "win32": clear_overlay_topmost_win32(self._overlay_tk_hwnd)
        self.destroy()
        if self._on_close: self._on_close()