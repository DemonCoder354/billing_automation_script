"""Tab 1 - Saving: inbox -> doctor folder."""
from __future__ import annotations

import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from ..config import APP_TITLE, DEFAULT_INBOX, FOLDER_COUNT, PDF_ROOT
from ..storage import documents_log_path, last_document_number, load_saver_config, save_json
from ..workers import InboxWatcher
from .widgets import LogBox


class SaverTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, padding=10)
        self.app = app
        self.cfg = load_saver_config()
        self.path_vars = [tk.StringVar(value=p) for p in self.cfg["folders"]]
        self.selected = tk.IntVar(value=self.cfg["selected"])
        self.inbox_var = tk.StringVar(value=self.cfg["inbox"])
        self.folder_snapshot = ""
        self.inbox_snapshot = self.cfg["inbox"]

        pad = {"padx": 8, "pady": 4}
        box = ttk.LabelFrame(self, text="Doctor folders")
        box.pack(fill="x")
        box.columnconfigure(1, weight=1)
        for i in range(FOLDER_COUNT):
            ttk.Label(box, text=f"Folder {i + 1}:").grid(row=i, column=0, sticky="w", **pad)
            ttk.Entry(box, textvariable=self.path_vars[i]).grid(row=i, column=1, sticky="ew", **pad)
            ttk.Button(box, text="Browse…", command=lambda i=i: self._browse(i)).grid(row=i, column=2, **pad)
        ttk.Label(box, text="Inbox (PDF24):").grid(row=FOLDER_COUNT, column=0, sticky="w", **pad)
        ttk.Entry(box, textvariable=self.inbox_var).grid(row=FOLDER_COUNT, column=1, sticky="ew", **pad)
        ttk.Button(box, text="Browse…", command=self._browse_inbox).grid(row=FOLDER_COUNT, column=2, **pad)

        act = ttk.Frame(self)
        act.pack(fill="x", pady=5)
        self.menu_btn = ttk.Menubutton(act, text="Save to ▾")
        self.menu = tk.Menu(self.menu_btn, tearoff=False)
        self.menu_btn["menu"] = self.menu
        self.menu_btn.pack(side="left")
        self.start_btn = ttk.Button(act, text="Start (F9)", command=self.toggle)
        self.start_btn.pack(side="left", padx=15)
        ttk.Button(act, text="Numbers", command=self._open_numbers).pack(side="right")
        ttk.Button(act, text="Reset numbers", command=self._reset_numbers).pack(side="right", padx=5)
        ttk.Button(act, text="Open inbox", command=self._open_inbox).pack(side="right")

        self.target_label = ttk.Label(self, foreground="#1a5fb4")
        self.target_label.pack(fill="x", pady=(0, 5))
        self.log = LogBox(self, "log.txt")
        self.log.pack(fill="both", expand=True)

        self._refresh()
        for v in self.path_vars + [self.inbox_var]:
            v.trace_add("write", lambda *_: self._changed())
        self.selected.trace_add("write", lambda *_: self._changed())

        self.watcher = InboxWatcher(lambda: self.folder_snapshot, lambda: self.inbox_snapshot,
                                    lambda s: app.post(self.log.write, s))
        self.watcher.start()
        self.log.write(f"Last document number: {last_document_number()}")
        self.log.write("Choose a doctor and press 'Start' (F9).")

    def _refresh(self):
        self.menu.delete(0, "end")
        for i in range(FOLDER_COUNT):
            path = self.path_vars[i].get().strip() or "(not set)"
            self.menu.add_radiobutton(label=f"Folder {i + 1}: {path}", variable=self.selected, value=i)
        i = self.selected.get()
        path = self.path_vars[i].get().strip()
        self.target_label["text"] = f"PDFs are saved to folder {i + 1}: {path or '(path not set)'}"
        self.folder_snapshot = path
        self.inbox_snapshot = self.inbox_var.get().strip() or DEFAULT_INBOX

    def _changed(self):
        self._refresh()
        self.cfg = {"folders": [v.get().strip() for v in self.path_vars],
                    "selected": self.selected.get(), "inbox": self.inbox_var.get().strip()}
        try:
            save_json("settings.json", self.cfg)
        except OSError as e:
            self.log.write(f"Could not save the settings: {e}")

    def _browse(self, i):
        path = filedialog.askdirectory(title=f"Folder {i + 1}",
                                       initialdir=self.path_vars[i].get() or PDF_ROOT)
        if path:
            self.path_vars[i].set(os.path.normpath(path))

    def _browse_inbox(self):
        path = filedialog.askdirectory(title="Inbox folder (where PDF24 saves)",
                                       initialdir=self.inbox_var.get() or PDF_ROOT)
        if path:
            self.inbox_var.set(os.path.normpath(path))

    def tick(self):
        self.start_btn["text"] = "Pause (F9)" if self.watcher.running.is_set() else "Start (F9)"

    def toggle(self):
        if self.watcher.running.is_set():
            self.watcher.stop()
            self.log.write("Paused (F9 or 'Start' to continue). New files wait in inbox.")
            return
        self.log.write(f"Started: picking up files from {self.inbox_snapshot}")
        self.watcher.running.set()

    def _open_inbox(self):
        os.makedirs(self.inbox_snapshot, exist_ok=True)
        os.startfile(self.inbox_snapshot)

    def _open_numbers(self):
        path = documents_log_path()
        if not os.path.exists(path):
            open(path, "a", encoding="utf-8").close()
        os.startfile(path)

    def _reset_numbers(self):
        if self.watcher.running.is_set():
            messagebox.showinfo(APP_TITLE, "Pause first (F9).")
            return
        if not messagebox.askyesno(
                APP_TITLE,
                f"Clear the number log (last number: {last_document_number()})?\n\n"
                "Numbering will start from doc1. Files with such names that already exist "
                "in the folder will not be overwritten - their numbers are skipped."):
            return
        try:
            open(documents_log_path(), "w", encoding="utf-8").close()
        except OSError as e:
            messagebox.showerror(APP_TITLE, f"Could not clear the log: {e}")
            return
        self.log.write("Number log cleared, numbering will start from 1.")
