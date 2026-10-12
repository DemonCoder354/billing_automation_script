"""Tickets from PDF files (pdf_text), the log of finished PDFs and the week save folders."""
from __future__ import annotations

import os
import re
import time

from thefuzz import fuzz

from ..doctors import load_doctors
from ..paths import DESKTOP_DIR
from ..recycle_bin import to_recycle_bin
from ..week_folders import WEEK_FOLDER_RE
from .applog import LOG_DIR
from .settings import SETTINGS, update_settings


# The "PDF Tickets" program (billing_automation.pdf_tickets) saves NextGen tickets as docN.pdf
# (N is a running number in print order), copies them to pdf_all as DOCTOR_docN.pdf and
# OCRs them into pdf_text. In 'pdf' mode AUTO-WORK takes the files from pdf_text one by one -
# without reading the NextGen screen, without the "next ticket" arrow and without the "Fee Tickets N of M" counter.


DOC_FILE_RE = re.compile(r"^(?:(.+)_)?doc(\d+)\.pdf$", re.IGNORECASE)   # SMITH_doc5.pdf or doc5.pdf
# finished PDFs (for which records were saved); cleared by the "Cleanup" tab in "PDF Tickets"
DONE_LOG = os.path.join(LOG_DIR, "done_pdfs.txt")
AUTO_START = "from the last one in the log"   # item of the "Start from" list

# folder of the current run in PDF mode (filled in by the window before start)
pdf_run = {"folder": "", "start_name": ""}   # start_name: start from this file (empty = after the finished ones)
_pdf_reader = None


def list_ticket_pdfs(folder):
    """[(number, path)] of the folder's docN.pdf / DOCTOR_docN.pdf files in ascending number order (= print order)."""
    found = []
    try:
        for name in os.listdir(folder):
            m = DOC_FILE_RE.match(name)
            if m:
                found.append((int(m.group(2)), name.lower(), os.path.join(folder, name)))
    except OSError:
        pass
    return [(n, p) for n, _name, p in sorted(found)]


def pdf_doctor(path):
    """Doctor from the file name SMITH_doc5.pdf (or '')."""
    m = DOC_FILE_RE.match(os.path.basename(path))
    return (m.group(1) or "") if m else ""


def done_pdfs():
    """Names of finished PDFs from done_pdfs.txt (in the order they were written)."""
    try:
        with open(DONE_LOG, "r", encoding="utf-8") as f:
            return [ln.rstrip("\n").split("\t")[1] for ln in f if ln.count("\t") >= 1]
    except OSError:
        return []


def mark_pdf_done(path, saved):
    """Writes the PDF to done_pdfs.txt (only if the website records were actually saved)."""
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(DONE_LOG, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}\t{os.path.basename(path)}\trecords saved: {saved}\n")
    except OSError as e:
        print(f"[PDF] [ERROR] Could not write {DONE_LOG}: {e}")


def clear_done_log():
    """Moves the log of finished PDFs to the Recycle Bin (recoverable). Returns an error text or None."""
    if not os.path.exists(DONE_LOG):
        return None
    try:
        to_recycle_bin([DONE_LOG])
    except Exception as e:
        return str(e)
    return None if not os.path.exists(DONE_LOG) else "the file was not deleted"


def pdf_start_index(tickets):
    """Index of the file from the last line of the finished log - it is processed again for safety
    (saving again does no harm). Empty log or the file is not in the folder - 0."""
    names = [os.path.basename(p).lower() for _n, p in tickets]
    for name in reversed(done_pdfs()):
        if name.lower() in names:
            return names.index(name.lower())
    return 0


def read_ticket_pdf(path):
    """(date of birth 'MM/DD/YYYY', 'LASTNAME FIRSTNAME', all ticket fields) from the PDF; blank page -> (None, None, {})."""
    global _pdf_reader
    if _pdf_reader is None:
        # the same recognition as in the "PDF Tickets" program
        from ..pdf_tickets.ticket import read_ticket
        from ..pdf_tickets.windows_ocr import WindowsOcr
        _pdf_reader = (read_ticket, WindowsOcr())
    read_ticket, ocr = _pdf_reader
    info = read_ticket(path, ocr)
    if info.get("blank"):
        return None, None, {}
    name = info.get("name") if info.get("name") not in (None, "?") else ""
    return info.get("dob"), name, info


# SAVE FOLDER ON THE DESKTOP: CAREPORTAL <dates>\DOCTOR\DOCTOR MMDDYYYY


SAVE_DOCTORS = load_doctors()
week_folder = ""   # full path of the week folder (found on every run)


def check_week_folder():
    """Finds the 'CAREPORTAL MMDDYYYY-MMDDYYYY' folder on the desktop, stores its name in the settings and writes it to the log."""
    global week_folder
    try:
        found = sorted(n for n in os.listdir(DESKTOP_DIR)
                       if WEEK_FOLDER_RE.match(n) and os.path.isdir(os.path.join(DESKTOP_DIR, n)))
    except OSError:
        found = []
    old = SETTINGS.get("week_folder", "")
    if not found:
        week_folder = ""
        print(f"[WEEK FOLDER] [!] There is no 'CAREPORTAL MMDDYYYY-MMDDYYYY' folder on the desktop ({DESKTOP_DIR}). "
              "Files will be saved wherever Explorer suggests.")
        return ""
    if len(found) > 1:
        print(f"[WEEK FOLDER] [!] There are several such folders: {', '.join(found)}. Taking the latest by date.")
        found.sort(key=lambda n: (n[-4:], n[-8:-4]))   # by year and week-end date
    name = found[-1]
    week_folder = os.path.join(DESKTOP_DIR, name)
    if name != old:
        if old:
            print(f"[WEEK FOLDER] Name changed: '{old}' -> '{name}'.")
        update_settings(week_folder=name)
    print(f"[WEEK FOLDER] {week_folder}")
    return week_folder


def doctor_from_physician(text):
    """Doctor from the Rendering Physician Name field ('Smi h, John' -> SMITH); not similar to anyone -> ''."""
    last = (text or "").split(",")[0]
    letters = re.sub(r"[^A-Z]", "", last.upper())
    if len(letters) < 3 or not SAVE_DOCTORS:
        return ""
    best = max(SAVE_DOCTORS, key=lambda d: fuzz.ratio(letters, d))
    return best if fuzz.ratio(letters, best) >= 75 else ""


def save_folder_for_ticket(info, fallback_doctor=""):
    """Week folder\\DOCTOR\\DOCTOR MMDDYYYY by doctor (Rendering Physician) and ticket creation date."""
    if not week_folder:
        return ""
    doctor = doctor_from_physician(info.get("physician"))
    if not doctor:
        fb = fallback_doctor.upper()
        doctor = next((d for d in SAVE_DOCTORS if d == fb), "")
        print(f"   [FOLDER] Doctor not recognized in the ticket ('{info.get('physician') or ''}')"
              + (f" - using the folder of doctor {doctor}." if doctor else " - not inserting a path."))
        if not doctor:
            return ""
    date = info.get("date") if info.get("date") not in (None, "?") else info.get("created")
    m = re.match(r"^(\d\d)/(\d\d)/(\d\d)$", date or "")
    if not m:
        print("   [FOLDER] Ticket creation date not recognized - not inserting a path.")
        return ""
    stamp = f"{m.group(1)}{m.group(2)}20{m.group(3)}"
    doctor_dir = os.path.join(week_folder, doctor)
    # day folder: "DOCTOR MMDDYYYY" or "DOCTORMMDDYYYY" - whichever already exists
    try:
        for n in os.listdir(doctor_dir):
            if n.replace(" ", "").upper() == doctor + stamp and os.path.isdir(os.path.join(doctor_dir, n)):
                return os.path.join(doctor_dir, n)
    except OSError:
        pass
    path = os.path.join(doctor_dir, f"{doctor} {stamp}")
    try:
        os.makedirs(path, exist_ok=True)
        print(f"   [FOLDER] The folder did not exist - created: {path}")
    except OSError as e:
        print(f"   [FOLDER] [ERROR] Could not create {path}: {e}")
        return ""
    return path
