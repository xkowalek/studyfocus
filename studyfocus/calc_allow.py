"""
Windows: kalkulator nad nakładką — Win32 Z-order + TOPMOST.
"""

from __future__ import annotations
import os
import subprocess
import sys
import threading

try:
    import win32api
    import win32con
    import win32gui
    import win32process
except ImportError:
    win32api = None
    win32con = None
    win32gui = None
    win32process = None

def calc_support_available() -> bool:
    """Sprawdza, czy biblioteki win32 są dostępne (wymagane przez lock_overlay)."""
    return win32gui is not None

def _is_calc_window(hwnd: int) -> bool:
    if win32gui is None: return False
    if not win32gui.IsWindowVisible(hwnd): return False
    
    title = win32gui.GetWindowText(hwnd).lower()
    cls = win32gui.GetClassName(hwnd)
    
    # Obsługa standardowego kalkulatora Windows 10/11
    if "calc" in title or "kalkulator" in title or cls == "ApplicationFrameWindow":
        if "kalkulator" in title or "calculator" in title:
            return True
    return False

def _raise_calc_windows(overlay_tk_hwnd: int) -> None:
    if win32gui is None or not overlay_tk_hwnd: return
    
    def enum_cb(hwnd: int, _: object) -> None:
        if _is_calc_window(hwnd):
            # Ustawiamy kalkulator jako TOPMOST, by nie uciekł pod nakładkę
            win32gui.SetWindowPos(
                hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0,
                win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE
            )
    win32gui.EnumWindows(enum_cb, None)

def start_calc_elevator(stop_event: threading.Event, overlay_tk_hwnd: int) -> threading.Thread:
    def run() -> None:
        while not stop_event.wait(0.8): 
            _raise_calc_windows(overlay_tk_hwnd)
    t = threading.Thread(target=run, daemon=True, name="StudyFocus-CalcElevator")
    t.start()
    return t

def launch_calculator() -> None:
    """Uruchamia kalkulator systemowy."""
    subprocess.Popen("calc.exe", shell=True)

def should_refocus_study_overlay(overlay_hwnd: int) -> bool:
    if not win32gui: return False
    fg = win32gui.GetForegroundWindow()
    if fg == 0: return True
    if fg == overlay_hwnd: return False
    if _is_calc_window(fg): return False
    return True

def apply_overlay_topmost_win32(tk_id: int) -> int:
    if not win32gui or not win32con: return 0
    try:
        hwnd = win32gui.GetAncestor(tk_id, win32con.GA_ROOT)
        win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0, 
                              win32con.SWP_NOMOVE | win32con.SWP_NOSIZE)
        return hwnd
    except: return 0

def clear_overlay_topmost_win32(tk_id: int) -> None:
    if not win32gui or not win32con: return
    try:
        hwnd = win32gui.GetAncestor(tk_id, win32con.GA_ROOT)
        win32gui.SetWindowPos(hwnd, win32con.HWND_NOTOPMOST, 0, 0, 0, 0, 
                              win32con.SWP_NOMOVE | win32con.SWP_NOSIZE)
    except: pass

def clear_calculator_topmost() -> None:
    if not win32gui or not win32con: return
    def enum_cb(hwnd: int, _: object) -> None:
        if _is_calc_window(hwnd):
            win32gui.SetWindowPos(hwnd, win32con.HWND_NOTOPMOST, 0, 0, 0, 0,
                                  win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE)
    win32gui.EnumWindows(enum_cb, None)