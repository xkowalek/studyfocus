"""Wieloetapowe potwierdzenie przedwczesnego zakończenia blokady."""

from __future__ import annotations

import random
from typing import Callable, Optional

import customtkinter as ctk

COUNTDOWN_SECONDS = 10
CONFIRM_CLICKS = 3


class EmergencyExitFlow:
    def __init__(
        self,
        lock_overlay: ctk.CTkToplevel,
        on_success: Callable[[], None],
        on_abort: Optional[Callable[[], None]] = None,
    ) -> None:
        self._lock = lock_overlay
        self._on_success = on_success
        self._on_abort = on_abort or (lambda: None)
        self._countdown_win: Optional[ctk.CTkToplevel] = None
        self._spot_win: Optional[ctk.CTkToplevel] = None
        self._remaining = COUNTDOWN_SECONDS
        self._step = 0
        self._closed = False

    def start(self) -> None:
        self._open_countdown()

    def _abort(self) -> None:
        if self._closed: return
        self._closed = True
        if self._countdown_win: self._countdown_win.destroy()
        if self._spot_win: self._spot_win.destroy()
        self._on_abort()

    def _open_countdown(self) -> None:
        w = ctk.CTkToplevel(self._lock)
        self._countdown_win = w
        w.overrideredirect(True)
        w.geometry(f"{self._lock.winfo_screenwidth()}x{self._lock.winfo_screenheight()}+0+0")
        w.configure(fg_color="#0a0a0a")
        w.attributes("-topmost", True)
        
        inner = ctk.CTkFrame(w, fg_color="transparent")
        inner.place(relx=0.5, rely=0.5, anchor="center")

        self._cd_label = ctk.CTkLabel(inner, text="", font=ctk.CTkFont(size=24, weight="bold"))
        self._cd_label.pack(pady=20)

        ctk.CTkButton(inner, text="WRÓĆ DO NAUKI", fg_color="#333", command=self._abort).pack()
        self._tick_countdown()

    def _tick_countdown(self) -> None:
        if self._closed or not self._countdown_win: return
        if self._remaining <= 0:
            self._countdown_win.destroy()
            self._open_spot_round()
            return
        self._cd_label.configure(text=f"Masz jeszcze: {self._remaining}s na przemyślenie czy na pewno chcesz wyjść!")
        self._remaining -= 1
        self._lock.after(1000, self._tick_countdown)

    def _open_spot_round(self) -> None:
        if self._closed: return
        self._step += 1
        if self._step > CONFIRM_CLICKS:
            self._on_success()
            return

        ww, wh = 360, 200
        x = random.randint(50, self._lock.winfo_screenwidth() - ww - 50)
        y = random.randint(50, self._lock.winfo_screenheight() - wh - 50)

        w = ctk.CTkToplevel(self._lock)
        self._spot_win = w
        w.overrideredirect(True)
        w.geometry(f"{ww}x{wh}+{x}+{y}")
        w.configure(fg_color="#111", border_width=2, border_color="#c0392b")
        w.attributes("-topmost", True)

        # Custom title bar
        ctk.CTkFrame(w, fg_color="#c0392b", height=5).pack(fill="x")
        
        ctk.CTkLabel(w, text=f"POTWIERDZENIE ({self._step}/{CONFIRM_CLICKS})", 
                     font=ctk.CTkFont(size=14, weight="bold"), text_color="#c0392b").pack(pady=15)
        
        ctk.CTkLabel(w, text="Kliknij przycisk poniżej,\naby kontynuować wychodzenie.").pack(pady=5)

        ctk.CTkButton(w, text="DALEJ", fg_color="#222", hover_color="#333", border_width=1,
                      command=lambda: [w.destroy(), self._open_spot_round()]).pack(pady=20, padx=40, fill="x")