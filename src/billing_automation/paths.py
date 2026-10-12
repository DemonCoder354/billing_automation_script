"""Locations of the shared folders.

All programs share one root folder: the repository root when run from source,
or the folder that contains the .exe files in a release build.

    <root>/
        pdf/                ticket PDFs (inbox, doctor folders, pdf_all, pdf_text, blank)
        data/auto_work/     AUTO-WORK settings, calibration, logs
        data/pdf_tickets/   PDF Tickets settings, number log, ticket index, logs
        doctors.txt         doctor names (one per line)
"""
from __future__ import annotations

import os
import sys


def _root_dir() -> str:
    if getattr(sys, "frozen", False):   # PyInstaller build: the folder of the .exe
        return os.path.dirname(os.path.abspath(sys.executable))
    # src/billing_automation/paths.py -> repository root
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


ROOT_DIR = _root_dir()
PDF_ROOT = os.path.join(ROOT_DIR, "pdf")
PDF_TEXT_DIR = os.path.join(PDF_ROOT, "pdf_text")
DATA_DIR = os.path.join(ROOT_DIR, "data")
AUTO_WORK_DIR = os.path.join(DATA_DIR, "auto_work")
PDF_TICKETS_DIR = os.path.join(DATA_DIR, "pdf_tickets")
DEFAULT_CALIBRATION_FILE = os.path.join(AUTO_WORK_DIR, "calibration_data.json")
DESKTOP_DIR = os.path.join(os.path.expanduser("~"), "Desktop")


def resource_path(name: str) -> str:
    """Path of a file bundled with the package (billing_automation/resources)."""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return os.path.join(base, "billing_automation", "resources", name)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "resources", name)


def user_or_bundled(name: str) -> str:
    """The user's copy of a file in the root folder if it exists, otherwise the bundled default."""
    user = os.path.join(ROOT_DIR, name)
    return user if os.path.exists(user) else resource_path(name)
