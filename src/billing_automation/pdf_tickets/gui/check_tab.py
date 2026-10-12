"""Tab 2 - Check: missing tickets."""
from __future__ import annotations

import os
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from ..analysis import analyze
from ..config import APP_TITLE, PDF_ROOT
from ..storage import append_log
from ..workers import _process_read_ticket


class CheckTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, padding=10)
        self.app = app
        self.busy = False

        pad = {"padx": 8, "pady": 4}
        box = ttk.Frame(self)
        box.pack(fill="x")
        box.columnconfigure(1, weight=1)
        ttk.Label(box, text="Ticket folder:").grid(row=0, column=0, sticky="w", **pad)
        self.folder = tk.StringVar(value=app.saver.folder_snapshot)
        self.folder_entry = ttk.Entry(box, textvariable=self.folder)
        self.folder_entry.grid(row=0, column=1, sticky="ew", **pad)
        self.browse_btn = ttk.Button(box, text="Browse…", command=self._browse)
        self.browse_btn.grid(row=0, column=2, **pad)
        # by default the doctor's folder that files from inbox are currently sorted into is checked
        self.follow = tk.BooleanVar(value=True)
        ttk.Checkbutton(box, text="The doctor's folder files are currently saved to ('Saving' tab)",
                        variable=self.follow, command=self.tick).grid(
            row=1, column=0, columnspan=3, sticky="w", **pad)
        ttk.Label(box, text="Tickets in NextGen (N from 'Fee Tickets 1 of N'):").grid(
            row=2, column=0, columnspan=2, sticky="w", **pad)
        self.expected = tk.StringVar()
        ttk.Entry(box, textvariable=self.expected, width=8).grid(row=2, column=2, sticky="w", **pad)

        act = ttk.Frame(self)
        act.pack(fill="x", pady=4)
        self.check_btn = ttk.Button(act, text="Check", command=self._check)
        self.check_btn.pack(side="left")
        self.status = ttk.Label(act, foreground="#1a5fb4")
        self.status.pack(side="left", padx=10)

        self.report = tk.Text(self, height=18, wrap="word")
        self.report.pack(fill="both", expand=True)

    def _browse(self):
        path = filedialog.askdirectory(initialdir=self.folder.get() or PDF_ROOT)
        if path:
            self.folder.set(os.path.normpath(path))

    def tick(self):
        """Follow the save folder while the checkbox is set."""
        state = "disabled" if self.follow.get() else "normal"
        self.folder_entry["state"] = state
        self.browse_btn["state"] = state
        if self.follow.get() and self.folder.get() != self.app.saver.folder_snapshot:
            self.folder.set(self.app.saver.folder_snapshot)

    def _check(self):
        if self.busy:
            return
        folder = self.folder.get().strip()
        if not folder or not os.path.isdir(folder):
            self.status["text"] = "Folder not found - choose a doctor on the 'Saving' tab."
            return
        inbox = self.app.saver.inbox_snapshot
        try:
            waiting = [n for n in os.listdir(inbox) if n.lower().endswith(".pdf")]
        except OSError:
            waiting = []
        if waiting and os.path.normcase(os.path.normpath(folder)) != os.path.normcase(os.path.normpath(inbox)) \
                and not messagebox.askyesno(
                    APP_TITLE, f"There are still {len(waiting)} file(s) in inbox - they have not been sorted into the doctor's folder "
                    "(saving is paused or still running).\n\nCheck anyway?"):
            return
        try:
            expected = int(self.expected.get()) if self.expected.get().strip() else None
        except ValueError:
            self.status["text"] = "The number of tickets must be an integer (or leave it empty)."
            return
        if self.app.services.failed:
            self.status["text"] = "Recognition is unavailable - see the log on the 'OCR' tab."
            return
        self.busy = True
        self.check_btn["state"] = "disabled"
        self.status["text"] = "Recognizing tickets…"
        threading.Thread(target=self._run, args=(folder, expected), daemon=True).start()

    def _run(self, folder, expected):
        try:
            self.app.services.ready.wait()
            files = sorted((os.path.join(folder, f) for f in os.listdir(folder)
                            if f.lower().endswith(".pdf")), key=os.path.getmtime)
            t = time.time()
            tickets = list(self.app.services.pool.map(_process_read_ticket, files))
            text = analyze(files, tickets, [os.path.getmtime(f) for f in files], expected)
            text += f"\n\n(checked in {time.time() - t:.0f} s)"
            append_log("check_log.txt", f"===== {time.strftime('%Y-%m-%d %H:%M:%S')} {folder}\n{text}\n")
        except Exception as e:  # noqa: BLE001
            text = f"Error: {e}"
        self.app.post(self._show, text)

    def _show(self, text):
        self.report.delete("1.0", "end")
        self.report.insert("1.0", text)
        self.status["text"] = ""
        self.check_btn["state"] = "normal"
        self.busy = False
