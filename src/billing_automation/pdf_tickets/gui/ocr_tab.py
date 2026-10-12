"""Tab 3 - OCR: image PDFs -> PDFs with a text layer."""
from __future__ import annotations

import os
import tkinter as tk
from tkinter import filedialog, ttk

from ..config import DEFAULT_OCR_DST, DEFAULT_OCR_SRC, PDF_ROOT, WORKERS
from ..storage import load_json, save_json
from ..workers import OcrWorker
from .widgets import LogBox


class OcrTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, padding=10)
        self.app = app
        cfg = load_json("ocr_settings.json", {})
        self.src_var = tk.StringVar(value=cfg.get("src") or DEFAULT_OCR_SRC)
        self.dst_var = tk.StringVar(value=cfg.get("dst") or DEFAULT_OCR_DST)
        self.paths = (self.src_var.get(), self.dst_var.get())

        pad = {"padx": 8, "pady": 4}
        box = ttk.LabelFrame(self, text="Folders")
        box.pack(fill="x")
        box.columnconfigure(1, weight=1)
        for row, (label, var) in enumerate((("Source (image PDFs):", self.src_var),
                                            ("Destination (PDFs with text):", self.dst_var))):
            ttk.Label(box, text=label).grid(row=row, column=0, sticky="w", **pad)
            ttk.Entry(box, textvariable=var).grid(row=row, column=1, sticky="ew", **pad)
            ttk.Button(box, text="Browse…", command=lambda v=var: self._browse(v)).grid(row=row, column=2, **pad)

        act = ttk.Frame(self)
        act.pack(fill="x", pady=5)
        self.start_btn = ttk.Button(act, text="Start", command=self._toggle)
        self.start_btn.pack(side="left")
        ttk.Button(act, text="Open result", command=self._open_dst).pack(side="right")

        self.log = LogBox(self, "ocr_log.txt", height=12)
        self.log.pack(fill="both", expand=True)
        for v in (self.src_var, self.dst_var):
            v.trace_add("write", lambda *_: self._changed())

        self.worker = OcrWorker(app.services, lambda: self.paths,
                                lambda s: app.post(self.log.write, s))
        self.worker.start()
        self.announced = False

    def _changed(self):
        cfg = {"src": self.src_var.get().strip(), "dst": self.dst_var.get().strip()}
        self.paths = (cfg["src"] or DEFAULT_OCR_SRC, cfg["dst"] or DEFAULT_OCR_DST)
        try:
            save_json("ocr_settings.json", cfg)
        except OSError as e:
            self.log.write(f"Could not save the settings: {e}")

    def _browse(self, var):
        path = filedialog.askdirectory(initialdir=var.get() or PDF_ROOT)
        if path:
            var.set(os.path.normpath(path))

    def tick(self):
        self.start_btn["text"] = "Stop" if self.worker.running.is_set() else "Start"
        if not self.announced and self.app.services.ready.is_set():
            self.announced = True
            self.log.write(f"Ready (recognition language: {self.app.services.lang}, "
                           f"processes: {WORKERS}). Press 'Start'.")

    def _toggle(self):
        if self.worker.running.is_set():
            self.worker.running.clear()
            self.log.write("Stopped.")
            return
        if not self.app.services.ready.is_set():
            self.log.write("Please wait, recognition is still loading.")
            return
        self.log.write(f"Started: {self.paths[0]} -> {self.paths[1]}")
        self.worker.running.set()

    def _open_dst(self):
        os.makedirs(self.paths[1], exist_ok=True)
        os.startfile(self.paths[1])
