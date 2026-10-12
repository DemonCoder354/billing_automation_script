"""Shared widgets of the PDF Tickets window."""
from __future__ import annotations

import time
import tkinter as tk
from tkinter import ttk

from ..storage import append_log


class LogBox(ttk.LabelFrame):
    """Tab log: in the window and in a file."""

    def __init__(self, parent, file_name, height=10):
        super().__init__(parent, text="Log")
        self.file_name = file_name
        self.text = tk.Text(self, height=height, state="disabled", wrap="word")
        self.text.pack(fill="both", expand=True, padx=5, pady=5)

    def write(self, text):
        line = time.strftime("%H:%M:%S ") + text
        self.text["state"] = "normal"
        self.text.insert("end", line + "\n")
        self.text.see("end")
        self.text["state"] = "disabled"
        append_log(self.file_name, time.strftime("%Y-%m-%d ") + line)
