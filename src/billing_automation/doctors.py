"""The list of doctors (rendering physicians) shared by all programs."""
from __future__ import annotations

import os

from .paths import ROOT_DIR

DOCTORS_FILES = ("doctors.txt", "doctors.example.txt")


def load_doctors(folder: str = ROOT_DIR) -> list[str]:
    """Doctor names (upper case) from doctors.txt in the root folder, one per line
    (falls back to doctors.example.txt). Lines starting with # are ignored."""
    for name in DOCTORS_FILES:
        try:
            with open(os.path.join(folder, name), encoding="utf-8") as f:
                names = [ln.strip().upper() for ln in f if ln.strip() and not ln.lstrip().startswith("#")]
        except OSError:
            continue
        if names:
            return names
    return []
