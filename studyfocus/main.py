
from __future__ import annotations

import logging
import os
import sys
import socket
from tkinter import filedialog
from typing import List, Optional

import customtkinter as ctk

from studyfocus.discovery import StudyFocusDiscovery
from studyfocus.lock_overlay import LockOverlay
from studyfocus.pdf_thumbs import pdf_first_page_ctk_image
from studyfocus.ws_server import LockSignalingServer

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("studyfocus.main")

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

_DURATION_PRESETS: dict[str, int] = {
    "15 min": 15 * 60,
    "25 min": 25 * 60,
    "45 min": 45 * 60,
    "60 min": 60 * 60,
    "90 min": 90 * 60,
    "120 min": 120 * 60,
}


def _get_my_ip() -> str:
    """Dynamicznie pobiera aktualny adres IP komputera w sieci lokalnej."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("224.0.0.1", 1))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def _decode_dropped_paths(raw: object) -> List[str]:
    out: List[str] = []
    if raw is None:
        return out
    if isinstance(raw, (list, tuple)):
        items = raw
    else:
        items = [raw]
    for item in items:
        if isinstance(item, bytes):
            for enc in ("utf-8", sys.getfilesystemencoding() or "utf-8", "mbcs"):
                try:
                    out.append(item.decode(enc))
                    break
                except Exception:
                    continue
        elif isinstance(item, str):
            out.append(item)
    return out


class StudyFocusApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title("StudyFocus")
        try:
            self.iconbitmap("ikona.ico")
        except Exception:
            pass
        self.geometry("960x700")
        self.minsize(800, 560)

        self._pdf_paths: List[str] = []
        self._overlay: Optional[LockOverlay] = None
        self._thumb_refs: List[ctk.CTkImage] = []
        self.is_phone_connected = False
        self._alarm_win: Optional[ctk.CTkToplevel] = None
        self._blink_state = False  # Stan migania alarmu

        self._ws = LockSignalingServer(host="0.0.0.0", port=8765)
        
        self._ws.on_client_change = self._on_phone_status_change
        self._ws.on_message = self._on_phone_message
        
        self._ws.start()
        if not self._ws.wait_until_ready():
            logger.warning("Serwer WebSocket nie potwierdził startu.")

        bound = self._ws.port_bound
        self._discovery = StudyFocusDiscovery(bound)
        self._discovery.start()

        self._build_ui()
        self.after(150, self._setup_drag_drop)
        self.protocol("WM_DELETE_WINDOW", self._on_quit)
        self._on_duration_menu_change(self._dur_choice.get())

    def _on_phone_status_change(self, connected: bool) -> None:
        self.is_phone_connected = connected
        self.after(0, self._update_phone_status_ui)

    def _update_phone_status_ui(self) -> None:
        if self.is_phone_connected:
            self._phone_status_label.configure(
                text="🟢 Status: Telefon połączony i uzbrojony", 
                text_color="#2ecc71"
            )
        else:
            self._phone_status_label.configure(
                text="🔴 Status: Oczekiwanie na telefon (uruchom aplikację na telefonie)...", 
                text_color="#e74c3c"
            )

    def _on_phone_message(self, message: str) -> None:
        if message == "CHEAT_DETECTED":
            print("ALARM: Telefon poruszony!")
            self.after(0, self._trigger_cheat_alarm_ui)
        elif message == "ALARM_MUTED":
            print("INFO: Telefon uciszony, zamykam alarm na PC.")
            self.after(0, self._close_cheat_alarm_ui)

    def _trigger_cheat_alarm_ui(self) -> None:
        """Wyrzuca okno alarmu nad nakładką blokady i uruchamia miganie."""
        self._phone_status_label.configure(
            text="⚠️ ALARM: WYKRYTO RUCH TELEFONU!", 
            text_color="#e67e22"
        )
        
        if self._alarm_win and self._alarm_win.winfo_exists():
            return
            
        target = self._overlay if self._overlay else self
        
        self._alarm_win = ctk.CTkToplevel(target)
        self._alarm_win.title("ZŁAPANY!")
        self._alarm_win.configure(fg_color="#c0392b")
        self._alarm_win.attributes("-topmost", True)
        
        ww, wh = 600, 250
        sw = target.winfo_screenwidth()
        sh = target.winfo_screenheight()
        x = (sw - ww) // 2
        y = (sh - wh) // 2
        self._alarm_win.geometry(f"{ww}x{wh}+{x}+{y}")
        self._alarm_win.overrideredirect(True)

        self._alarm_label = ctk.CTkLabel(
            self._alarm_win, 
            text="⚠️ WYKRYTO RUCH TELEFONU! ⚠️\n\nNATYCHMIAST WRACAJ DO NAUKI!", 
            font=ctk.CTkFont(size=24, weight="bold"),
            text_color="white"
        )
        self._alarm_label.pack(expand=True)
        
        # Start pętli efektu migania
        self._blink_state = False
        self._blink_alarm()

    def _blink_alarm(self) -> None:
        """Pętla togglująca kolory tła popupu alarmowego."""
        if self._alarm_win and self._alarm_win.winfo_exists():
            self._blink_state = not self._blink_state
            # Zmiana między jasną a ciemną czerwienią co 350ms
            color = "#c0392b" if self._blink_state else "#5c1d15"
            self._alarm_win.configure(fg_color=color)
            self.after(350, self._blink_alarm)

    def _close_cheat_alarm_ui(self) -> None:
        if self._alarm_win and self._alarm_win.winfo_exists():
            self._alarm_win.destroy()
        self._alarm_win = None
        self._update_phone_status_ui()

    def _on_duration_menu_change(self, value: str) -> None:
        if value == "Własny (min)":
            self._dur_custom.pack(side="left", padx=(4, 0))
        else:
            self._dur_custom.pack_forget()

    def _lock_duration_seconds(self) -> int:
        key = self._dur_choice.get()
        if key == "Własny (min)":
            try:
                minutes = int(self._dur_custom.get().strip())
            except ValueError:
                minutes = 25
            return max(1, min(minutes, 600)) * 60
        return _DURATION_PRESETS.get(key, 25 * 60)

    def _build_ui(self) -> None:
        head = ctk.CTkFrame(self, fg_color="transparent")
        head.pack(fill="x", padx=20, pady=(16, 8))

        ctk.CTkLabel(head, text="StudyFocus", font=ctk.CTkFont(size=28, weight="bold")).pack(side="left")

        self._btn_start = ctk.CTkButton(
            head,
            text="Rozpocznij naukę!",
            width=160,
            height=40,
            font=ctk.CTkFont(size=15, weight="bold"),
            fg_color="#1f6f4a",
            hover_color="#145038",
            command=self._start_lock,
        )
        self._btn_start.pack(side="right", padx=(12, 0))

        phone_status_fr = ctk.CTkFrame(self, fg_color="#111", height=40, corner_radius=6)
        phone_status_fr.pack(fill="x", padx=20, pady=(4, 12))
        
        self._phone_status_label = ctk.CTkLabel(
            phone_status_fr, 
            text="🔴 Status: Oczekiwanie na podłączenie telefonu (uruchom aplikację na telefonie)...", 
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#e74c3c"
        )
        self._phone_status_label.pack(side="left", padx=12, pady=6)

        self._bypass_phone_chk = ctk.CTkCheckBox(
            phone_status_fr, 
            text="Nie chcę podłączać telefonu (tryb awaryjny)",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#aaa"
        )
        self._bypass_phone_chk.pack(side="right", padx=12, pady=6)

        dur = ctk.CTkFrame(self, fg_color="transparent")
        dur.pack(fill="x", padx=20, pady=(0, 6))
        ctk.CTkLabel(dur, text="Czas blokady:", font=ctk.CTkFont(size=14)).pack(side="left")
        self._dur_choice = ctk.StringVar(value="25 min")
        self._dur_menu = ctk.CTkOptionMenu(
            dur,
            variable=self._dur_choice,
            values=list(_DURATION_PRESETS.keys()) + ["Własny (min)"],
            width=140,
            command=self._on_duration_menu_change,
        )
        self._dur_menu.pack(side="left", padx=(10, 4))
        self._dur_custom = ctk.CTkEntry(dur, width=72, placeholder_text="min")
        self._dur_custom.insert(0, "40")

        tiles_fr = ctk.CTkFrame(self, fg_color="transparent")
        tiles_fr.pack(fill="both", expand=True, padx=20, pady=(20, 16))

        row_pdf = ctk.CTkFrame(tiles_fr, fg_color="transparent")
        row_pdf.pack(fill="x", pady=(0, 10))
        
        ctk.CTkLabel(
            row_pdf,
            text="Twoje materiały (Przeciągnij PDF poniżej):",
            font=ctk.CTkFont(size=15, weight="bold"),
        ).pack(side="left")

        ctk.CTkButton(
            row_pdf,
            text="Dodaj plik…",
            width=100,
            height=28,
            command=self._pick_pdfs,
        ).pack(side="right")

        self._tiles_scroll = ctk.CTkScrollableFrame(
            tiles_fr,
            fg_color="#151515",
            border_width=2,
            border_color="#333",
            orientation="horizontal",
        )
        self._tiles_scroll.pack(fill="both", expand=True)
        self._rebuild_pdf_tiles()

        # Dynamiczne wyświetlanie IP w stopce aplikacji
        my_ip = _get_my_ip()
        foot = ctk.CTkLabel(
            self,
            text=f"Adres IP komputera: {my_ip}  •  Serwer: Aktywny",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#888",
        )
        foot.pack(side="bottom", pady=10)

    def _setup_drag_drop(self) -> None:
        if sys.platform != "win32":
            return
        try:
            import windnd
        except ImportError:
            return

        def on_drop(files: object) -> None:
            self._add_pdf_paths(_decode_dropped_paths(files))

        windnd.hook_dropfiles(self._tiles_scroll, func=on_drop, force_unicode=True)

    def _rebuild_pdf_tiles(self) -> None:
        """Przebudowuje widok materiałów PDF: poprawne centrowanie stanu pustego i inteligentny scrollbar."""
        # Czyszczenie starych kafelków i napisów
        for w in self._tiles_scroll.winfo_children():
            w.destroy()
        self._thumb_refs.clear()
        
        # Dynamicznie pobieramy bieżącą szerokość okna przewijanego
        scroll_width = self._tiles_scroll.winfo_width()
        if scroll_width < 10:
            scroll_width = 920  # Bezpieczny fallback na start aplikacji
            
        if not self._pdf_paths:
            # Ukrywamy pasek przewijania, gdy okno jest całkowicie puste
            try:
                self._tiles_scroll._scrollbar.grid_remove()
            except Exception:
                pass
                
            # Rozciągamy etykietę na pełną szerokość tła, aby wycentrować napis
            ctk.CTkLabel(
                self._tiles_scroll,
                text="Brak plików. Przeciągnij PDF tutaj, aby dodać go do sesji.",
                font=ctk.CTkFont(size=14, weight="bold"),
                text_color="#555",
                width=scroll_width - 40,
            ).pack(expand=True, fill="both", pady=100)
            return

        # --- INTELIGENTNY SCROLLBAR: Obliczamy fizyczną szerokość kafelków ---
        # Każdy boks zajmuje 170px szerokości + 20px marginesów poziomej przestrzeni = 190px
        potrzebna_szerokosc = len(self._pdf_paths) * 190 + 20
        
        if potrzebna_szerokosc > scroll_width:
            # Pokaż scrollbar TYLKO wtedy, gdy pliki faktycznie nie mieszczą się w oknie
            try:
                self._tiles_scroll._scrollbar.grid()
            except Exception:
                pass
        else:
            # Ukryj scrollbar, jeśli wszystko ładnie się mieści i nie trzeba przewijać
            try:
                self._tiles_scroll._scrollbar.grid_remove()
            except Exception:
                pass

        # Główny kontener wiersza na pliki
        row = ctk.CTkFrame(self._tiles_scroll, fg_color="transparent")
        row.pack(fill="both", expand=True, padx=5, pady=5)

        for path in self._pdf_paths:
            # Sztywny box na kafelki (Rozmiar 170x230)
            tile = ctk.CTkFrame(row, fg_color="#1e1e1e", corner_radius=10, border_width=1, border_color="#333", width=170, height=230)
            tile.pack_propagate(False) 
            tile.pack(side="left", padx=10, pady=5)

            # Wewnętrzny kontener na elementy
            inner = ctk.CTkFrame(tile, fg_color="transparent")
            inner.pack(fill="both", expand=True, padx=10, pady=10)

            # Dopasowanie miniaturki z zachowaniem proporcji stron
            thumb = pdf_first_page_ctk_image(path, max_side=120)
            if thumb:
                ctk_img, _, _ = thumb
                self._thumb_refs.append(ctk_img)
                ctk.CTkLabel(inner, text="", image=ctk_img).pack(pady=(0, 5), anchor="center")
            else:
                ctk.CTkLabel(inner, text="📄", font=ctk.CTkFont(size=40)).pack(pady=(10, 5))

            # Nazwa pliku
            name = os.path.basename(path)
            short_name = name[:16] + "..." if len(name) > 18 else name
            ctk.CTkLabel(
                inner, 
                text=short_name, 
                font=ctk.CTkFont(size=12, weight="bold"), 
                wraplength=140,
                text_color="#eee"
            ).pack(pady=2, anchor="center")

            # Przycisk usuwania trzymany stabilnie na dole kafelka
            ctk.CTkButton(
                inner, 
                text="Usuń plik", 
                width=130, 
                height=26, 
                fg_color="#7b241c", 
                hover_color="#922b21",
                font=ctk.CTkFont(size=11, weight="bold"),
                command=lambda p=path: self._remove_pdf(p)
            ).pack(side="bottom", pady=(5, 0))

    def _remove_pdf(self, path: str) -> None:
        if path in self._pdf_paths:
            self._pdf_paths.remove(path)
            self._rebuild_pdf_tiles()

    def _add_pdf_paths(self, paths: List[str]) -> None:
        for p in paths:
            if p.lower().endswith(".pdf") and os.path.isfile(p) and p not in self._pdf_paths:
                self._pdf_paths.append(p)
        self._rebuild_pdf_tiles()

    def _pick_pdfs(self) -> None:
        paths = list(filedialog.askopenfilenames(filetypes=[("PDF", "*.pdf")]))
        if paths:
            self._add_pdf_paths(paths)

    def _start_lock(self) -> None:
        if self._overlay: return
        
        if not self.is_phone_connected and not self._bypass_phone_chk.get():
            self._phone_status_label.configure(
                text="❌ BŁĄD: Podłącz telefon lub zaznacz 'Tryb awaryjny', aby wystartować!",
                text_color="#e74c3c"
            )
            return

        self._ws.set_locked(True)
        self._overlay = LockOverlay(
            self,
            duration_seconds=self._lock_duration_seconds(),
            pdf_paths=list(self._pdf_paths) if self._pdf_paths else None,
            on_close=self._on_overlay_closed,
        )
        self._btn_start.configure(state="disabled")

    def _on_overlay_closed(self) -> None:
        self._ws.set_locked(False)
        self._overlay = None
        self._btn_start.configure(state="normal")
        self._close_cheat_alarm_ui()

    def _on_quit(self) -> None:
        self._close_cheat_alarm_ui()
        self._discovery.stop()
        self._ws.stop()
        self.destroy()


def main() -> None:
    StudyFocusApp().mainloop()


if __name__ == "__main__":
    main()