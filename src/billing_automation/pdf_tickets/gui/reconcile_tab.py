"""CarePortal reconciliation tab."""
from __future__ import annotations

import threading
import time
import tkinter as tk
from tkinter import ttk

from ..reconcile import reconcile
from ..storage import append_log


class ReconcileTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, padding=10)
        self.app = app
        ttk.Label(self, text="Reconciles the CarePortal records in the week folder on the desktop with the tickets from pdf_text:\n"
                             "finds records of 'unknown people', records in the wrong folder and tickets without records.").pack(anchor="w")
        top = ttk.Frame(self)
        top.pack(fill="x", pady=8)
        self.btn = ttk.Button(top, text="Reconcile", command=self._start)
        self.btn.pack(side="left")
        self.status = ttk.Label(top, foreground="#666")
        self.status.pack(side="left", padx=10)
        self.report = tk.Text(self, wrap="none", height=20)
        self.report.pack(fill="both", expand=True)

    def _start(self):
        self.btn["state"] = "disabled"
        self.status["text"] = "Reconciling…"
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        try:
            text = reconcile()
            append_log("reconcile_log.txt", f"===== {time.strftime('%Y-%m-%d %H:%M:%S')}\n{text}\n")
        except Exception as e:  # noqa: BLE001
            text = f"Error: {e}"
        self.app.post(self._show, text)

    def _show(self, text):
        self.report.delete("1.0", "end")
        self.report.insert("1.0", text)
        self.status["text"] = ""
        self.btn["state"] = "normal"
