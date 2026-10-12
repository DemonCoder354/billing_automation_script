"""Tab 4 - Cleanup: everything to the Recycle Bin before a new week."""
from __future__ import annotations

import os
import time
import tkinter as tk
from tkinter import messagebox, ttk

from ...recycle_bin import to_recycle_bin
from ..cleanup import collect_files
from ..config import APP_TITLE, AUTOWORK_DONE_LOG, PDF_ROOT
from ..storage import documents_log_path


class PurgeTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, padding=10)
        self.app = app
        self.reset_numbers = tk.BooleanVar(value=True)
        ttk.Label(self, text=f"All files will be deleted from the folders inside:\n{PDF_ROOT}\n"
                             "as well as the AUTO-WORK finished PDF log.").pack(anchor="w")

        self.table = ttk.Treeview(self, columns=("count",), height=8)
        self.table.heading("#0", text="Folder")
        self.table.heading("count", text="Files")
        self.table.column("count", width=80, anchor="e")
        self.table.pack(fill="both", expand=True, pady=8)

        self.total_label = ttk.Label(self)
        self.total_label.pack(anchor="w")
        ttk.Checkbutton(self, text="Reset numbering (the next file is doc1 again)",
                        variable=self.reset_numbers).pack(anchor="w", pady=(8, 0))
        ttk.Label(self, text="Files go to the Recycle Bin - they can be restored until it is emptied.",
                  foreground="#666").pack(anchor="w", pady=(4, 0))

        btns = ttk.Frame(self)
        btns.pack(fill="x", pady=(10, 0))
        ttk.Button(btns, text="Refresh", command=self.refresh).pack(side="left")
        ttk.Button(btns, text="Delete all", command=self.purge).pack(side="right")
        self.refresh()

    def refresh(self):
        self.found = collect_files(PDF_ROOT) if os.path.isdir(PDF_ROOT) else {}
        self.table.delete(*self.table.get_children())
        for folder, files in sorted(self.found.items()):
            name = os.path.relpath(folder, PDF_ROOT)
            self.table.insert("", "end", text="pdf" if name == "." else name, values=(len(files),))
        if os.path.exists(AUTOWORK_DONE_LOG):
            self.table.insert("", "end", text="AUTO-WORK: finished PDF log", values=(1,))
        self.total_label["text"] = f"Total files: {sum(len(f) for f in self.found.values())}"

    def purge(self):
        if self.app.saver.watcher.running.is_set() or self.app.ocr.worker.running.is_set():
            messagebox.showinfo(APP_TITLE, "Stop saving (F9) and OCR first.")
            return
        self.refresh()
        files = [p for paths in self.found.values() for p in paths]
        if os.path.exists(AUTOWORK_DONE_LOG):
            files.append(AUTOWORK_DONE_LOG)   # next week AUTO-WORK will start from the first PDF
        reset = self.reset_numbers.get()
        if not files and not reset:
            messagebox.showinfo(APP_TITLE, "The folders are already empty.")
            return
        text = f"Delete {len(files)} files from the folders inside {PDF_ROOT}?"
        if reset:
            text += "\n\nNumbering will be reset: the next file is doc1 again."
        if not messagebox.askyesno(APP_TITLE, text, icon="warning"):
            return
        numbers = documents_log_path()
        try:
            if files:
                to_recycle_bin(files)
            if reset and os.path.exists(numbers):
                # the old number log is not lost - it is renamed with a date
                os.replace(numbers, numbers[:-4] + time.strftime("_%Y-%m-%d_%H-%M-%S.txt"))
        except OSError as e:
            messagebox.showerror(APP_TITLE, str(e))
            self.refresh()
            return
        self.refresh()
        if reset:
            self.app.saver.log.write("Numbering reset ('Cleanup' tab): the next file is doc1.")
        messagebox.showinfo(APP_TITLE, f"Done: files deleted - {len(files)}."
                            + ("\nNumbering reset." if reset else ""))
