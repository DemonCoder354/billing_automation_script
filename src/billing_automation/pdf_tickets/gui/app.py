"""PDF Tickets main window."""
from __future__ import annotations

import queue
import tkinter as tk
from tkinter import ttk

from ..config import APP_TITLE
from ..workers import Services
from .check_tab import CheckTab
from .ocr_tab import OcrTab
from .purge_tab import PurgeTab
from .reconcile_tab import ReconcileTab
from .saver_tab import SaverTab


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.minsize(640, 520)
        self.calls = queue.Queue()  # actions from background threads -> executed in the window thread
        self.services = Services(lambda s: self.post(self._service_log, s))

        # large tabs so that they are visible right away
        style = ttk.Style(self)
        style.configure("TNotebook.Tab", padding=(18, 8), font=("Segoe UI", 11, "bold"))
        ttk.Label(self, text="Choose a tab: saving -> check -> OCR -> cleanup",
                  foreground="#666").pack(anchor="w", padx=10, pady=(8, 0))
        tabs = ttk.Notebook(self)
        tabs.pack(fill="both", expand=True, padx=8, pady=(4, 8))
        self.saver = SaverTab(tabs, self)
        self.check = CheckTab(tabs, self)
        self.ocr = OcrTab(tabs, self)
        self.purge = PurgeTab(tabs, self)
        self.reconcile = ReconcileTab(tabs, self)
        tabs.add(self.saver, text="1. Saving")
        tabs.add(self.check, text="2. Check")
        tabs.add(self.ocr, text="3. OCR")
        tabs.add(self.reconcile, text="CarePortal reconciliation")
        tabs.add(self.purge, text="4. Cleanup")
        tabs.bind("<<NotebookTabChanged>>",
                  lambda e: self.purge.refresh() if tabs.select() == str(self.purge) else None)

        self._f9_down = False
        self.after(50, self._poll_f9)
        self.after(200, self._drain)

    def post(self, func, *args):
        """Calls func(*args) in the window thread (tkinter must not be touched from other threads)."""
        self.calls.put((func, args))

    def _service_log(self, text):
        self.ocr.log.write(text)

    def _drain(self):
        while not self.calls.empty():
            func, args = self.calls.get()
            func(*args)
        self.saver.tick()
        self.check.tick()
        self.ocr.tick()
        self.after(200, self._drain)

    def _poll_f9(self):
        """F9 in any window: start / pause saving."""
        import ctypes
        down = bool(ctypes.windll.user32.GetAsyncKeyState(0x78) & 0x8000)  # VK_F9
        if down and not self._f9_down:
            self.saver.toggle()
        self._f9_down = down
        self.after(50, self._poll_f9)
