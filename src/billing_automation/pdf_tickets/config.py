"""PDF Tickets constants: folders, polling intervals, OCR and analysis thresholds."""
from __future__ import annotations

import os

from ..paths import AUTO_WORK_DIR, PDF_ROOT, PDF_TEXT_DIR

APP_TITLE = "PDF Tickets"
# PDF24 saves the printed tickets into the inbox
DEFAULT_INBOX = os.path.join(PDF_ROOT, "inbox")
# AUTO-WORK log of finished PDFs - cleared together with the files on the "Cleanup" tab
AUTOWORK_DONE_LOG = os.path.join(AUTO_WORK_DIR, "logs", "done_pdfs.txt")
DEFAULT_OCR_SRC = os.path.join(PDF_ROOT, "pdf_all")
DEFAULT_OCR_DST = PDF_TEXT_DIR
ALL_FOLDER_NAME = "pdf_all"
BLANK_FOLDER_NAME = "blank"
FOLDER_COUNT = 4
SAVER_POLL_SECONDS = 0.5
OCR_POLL_SECONDS = 2
OCR_DPI = 300
OCR_LANGS = ("pl", "en-US", "ru")  # the first one available in Windows
WORKERS = max(2, (os.cpu_count() or 4) - 2)  # a couple of cores stay free for the system and the window
MAX_SEQ_GAP = 3      # a bigger gap in SEQ NO means other doctors' tickets, not a loss
PAUSE_MIN = 8.0      # print pause (s) from which it becomes suspicious
NEW_PRINT_PAUSE = 90.0  # a longer pause is a new print job (reprint), not lost tickets
