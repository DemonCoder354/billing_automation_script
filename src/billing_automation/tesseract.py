"""Tesseract OCR: the executable path and running it without a flashing console window."""
from __future__ import annotations

import os
import subprocess
import types

# IMPORTANT: path to the installed Tesseract OCR
TESSERACT_PATH = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
CREATE_NO_WINDOW = 0x08000000


class _HiddenPopen(subprocess.Popen):
    """Tesseract without a flashing console window (CREATE_NO_WINDOW)."""
    def __init__(self, *args, **kwargs):
        if os.name == "nt":
            kwargs["creationflags"] = kwargs.get("creationflags", 0) | CREATE_NO_WINDOW
        super().__init__(*args, **kwargs)


def configure_pytesseract() -> None:
    """Points pytesseract at TESSERACT_PATH and gives it a private copy of subprocess that hides the console."""
    import pytesseract

    pytesseract.pytesseract.tesseract_cmd = TESSERACT_PATH
    hidden = types.ModuleType("subprocess_hidden")
    hidden.__dict__.update(subprocess.__dict__)
    hidden.Popen = _HiddenPopen

    def _no_window(func):
        def wrapper(*args, **kwargs):
            kwargs["creationflags"] = kwargs.get("creationflags", 0) | CREATE_NO_WINDOW
            return func(*args, **kwargs)
        return wrapper

    # the Tesseract version check (before every recognition) goes through check_output/run
    for name in ("check_output", "run", "call", "check_call"):
        setattr(hidden, name, _no_window(getattr(subprocess, name)))
    pytesseract.pytesseract.subprocess = hidden
