"""Reconciliation: CarePortal records in the week folder on the desktop <-> tickets from pdf_text."""
from __future__ import annotations

import os
import re

from ..doctors import load_doctors
from ..paths import DESKTOP_DIR, PDF_TEXT_DIR
from ..week_folders import WEEK_FOLDER_RE
from .config import AUTOWORK_DONE_LOG
from .header import HEADER_LAYOUT


SAVE_DOCTORS = load_doctors()
NAME_MATCH = 70   # name similarity, % (as in AUTO-WORK)
DOC_NAME_RE = re.compile(r"^(?:(.+)_)?doc(\d+)\.pdf$", re.IGNORECASE)   # SMITH_doc5.pdf


def _doc_number(path):
    m = DOC_NAME_RE.match(os.path.basename(path))
    return (int(m.group(2)) if m else 10 ** 9, os.path.basename(path))


def find_week_folder():
    """The 'CAREPORTAL MMDDYYYY-MMDDYYYY' folder on the desktop ('' - none)."""
    try:
        found = [n for n in os.listdir(DESKTOP_DIR)
                 if WEEK_FOLDER_RE.match(n) and os.path.isdir(os.path.join(DESKTOP_DIR, n))]
    except OSError:
        return ""
    found.sort(key=lambda n: (n[-4:], n[-8:-4]))
    return os.path.join(DESKTOP_DIR, found[-1]) if found else ""


def _name_score(a, b):
    """Name similarity 0-100 ignoring word order and commas ('DOE, JOHN MICHAE' ~ 'DOE JOHN MICHAEL')."""
    import difflib
    wa = re.sub(r"[^A-Z ]", " ", a.upper()).split()
    wb = re.sub(r"[^A-Z ]", " ", b.upper()).split()
    if not wa or not wb:
        return 0
    full = difflib.SequenceMatcher(None, " ".join(sorted(wa)), " ".join(sorted(wb))).ratio()
    # last name + first name (CarePortal and the ticket may have a different number of words)
    short = difflib.SequenceMatcher(None, " ".join(wa[:2]), " ".join(wb[:2])).ratio()
    return round(max(full, short) * 100)


def _doctor_of(physician, fallback=""):
    """Doctor by Rendering Physician ('Smith, John' -> SMITH); if not similar - doctor from the file name."""
    import difflib
    letters = re.sub(r"[^A-Z]", "", (physician or "").split(",")[0].upper())
    if len(letters) >= 3 and SAVE_DOCTORS:
        best = max(SAVE_DOCTORS, key=lambda d: difflib.SequenceMatcher(None, letters, d).ratio())
        if difflib.SequenceMatcher(None, letters, best).ratio() >= 0.75:
            return best
    fb = (fallback or "").upper()
    return fb if fb in SAVE_DOCTORS else ""


def layer_fields(path):
    """Header fields from the PDF text layer (pdf_text) - without OCR: {LABEL: value}; {} - no layer."""
    import pymupdf
    try:
        with pymupdf.open(path) as doc:
            text = " ".join(doc[0].get_text().split())
    except Exception:  # noqa: BLE001
        return {}
    labels = [lb for row in HEADER_LAYOUT for lb in row if lb]
    spots, pos = [], 0
    for lb in labels:
        m = re.compile(r"(?<!\S)" + re.escape(lb) + r"(?!\S)").search(text, pos)
        if m:
            spots.append((lb.upper(), m.start(), m.end()))
            pos = m.end()
    return {lb: text[end:(spots[i + 1][1] if i + 1 < len(spots) else len(text))].strip()
            for i, (lb, _s, end) in enumerate(spots)}


def reconcile_ticket(path):
    """Ticket from pdf_text: name, DOB, doctor, expected day folder 'DOCTOR\\DOCTOR MMDDYYYY'."""
    f = layer_fields(path)
    m = DOC_NAME_RE.match(os.path.basename(path))
    doctor = _doctor_of(f.get("RENDERING PHYSICIAN NAME"), m.group(1) if m else "")
    d = re.fullmatch(r"(\d\d)/(\d\d)/(\d\d)", f.get("CREATE DATE", ""))
    folder = os.path.join(doctor, f"{doctor} {d.group(1)}{d.group(2)}20{d.group(3)}") if doctor and d else ""
    name = " ".join(x for x in (f.get("LAST NAME"), f.get("FIRST NAME"), f.get("MIDDLE NAME")) if x)
    return {"file": os.path.basename(path), "name": name, "dob": f.get("DOB", ""), "folder": folder}


# '1A-BC-DE2 · Male · 42 y · 01/15/1984', 'F-12-K34 · Female · ...', 'AB1CD · Male · 69 y · 11/02/1956'
_PORTAL_ID_LINE = re.compile(r"^\s*[0-9A-Z][\w-]{3,11}\s*·\s*\w+\s*·.*?(\d\d/\d\d/\d{4})")


def read_portal_pdf(path):
    """Saved CarePortal record: (name 'LASTNAME, FIRSTNAME', DOB) - the name line is above the line 'ID · sex · age · DOB'."""
    import pymupdf
    try:
        with pymupdf.open(path) as doc:
            lines = [ln.strip() for ln in doc[0].get_text().splitlines()]
    except Exception:  # noqa: BLE001
        return None, None
    for i, ln in enumerate(lines):
        m = _PORTAL_ID_LINE.match(ln)
        if m:
            prev = next((lines[j] for j in range(i - 1, -1, -1) if lines[j]), "")
            return prev, m.group(1)
    return None, None


def done_pdf_names():
    """PDF names from the AUTO-WORK finished log."""
    try:
        with open(AUTOWORK_DONE_LOG, encoding="utf-8") as f:
            return {ln.split("\t")[1].strip().lower() for ln in f if ln.count("\t") >= 1}
    except OSError:
        return set()


def reconcile(week=None, text_dir=PDF_TEXT_DIR):
    """Reconciliation report text: other people's records, records in the wrong folder, tickets without records."""
    week = week or find_week_folder()
    if not week or not os.path.isdir(week):
        return "Week folder 'CAREPORTAL MMDDYYYY-MMDDYYYY' not found on the desktop."
    paths = sorted((os.path.join(text_dir, n) for n in os.listdir(text_dir) if n.lower().endswith(".pdf")),
                   key=_doc_number) \
        if os.path.isdir(text_dir) else []
    if not paths:
        return f"No PDFs in {text_dir} - nothing to reconcile with."
    tickets = [reconcile_ticket(p) for p in paths]
    saved = []
    for dirpath, _dirs, files in os.walk(week):
        for n in files:
            if n.lower().endswith(".pdf"):
                p = os.path.join(dirpath, n)
                name, dob = read_portal_pdf(p)
                saved.append({"path": p, "rel": os.path.relpath(p, week), "folder": os.path.relpath(dirpath, week),
                              "name": name, "dob": dob})

    stranger, wrong_folder, unread, hits = [], [], [], {}
    for s in saved:
        if not s["dob"]:
            unread.append(s)
            continue
        same_dob = [t for t in tickets if t["dob"] == s["dob"]]
        scored = sorted(((_name_score(s["name"], t["name"]), t) for t in same_dob), key=lambda x: -x[0])
        if not scored or scored[0][0] < NAME_MATCH:
            near = f" (ticket with the same DOB: {scored[0][1]['name']}, {scored[0][1]['file']})" if scored else ""
            stranger.append(f"  {s['rel']}: {s['name']}, DOB {s['dob']}{near}")
            continue
        matched = [t for sc, t in scored if sc >= NAME_MATCH]
        for t in matched:
            hits.setdefault(t["file"], []).append(s)
        if not any(os.path.normcase(t["folder"]) == os.path.normcase(s["folder"]) for t in matched):
            wrong_folder.append(f"  {s['rel']}: {s['name']} - according to ticket {matched[0]['file']} "
                                f"the folder is {matched[0]['folder'] or '?'}")

    done = done_pdf_names()
    no_file_done = [t for t in tickets if t["file"] not in hits and t["file"].lower() in done]
    no_file = [t for t in tickets if t["file"] not in hits and t["file"].lower() not in done]
    lines = [f"Week folder: {week}",
             f"Tickets in pdf_text: {len(tickets)}, CarePortal records (PDF): {len(saved)}, "
             f"tickets with records: {len(hits)}", ""]
    lines.append(f"OTHER PEOPLE'S RECORDS - no ticket with this DOB and a similar name: {len(stranger)}")
    lines += stranger or ["  none"]
    lines.append("")
    lines.append(f"Records in the wrong folder (doctor/day differ from the ticket): {len(wrong_folder)}")
    lines += wrong_folder or ["  none"]
    if unread:
        lines.append("")
        lines.append(f"Could not read the name/DOB in the record: {len(unread)}")
        lines += [f"  {s['rel']}" for s in unread]
    lines.append("")
    lines.append(f"Marked as done in the AUTO-WORK log, but no records: {len(no_file_done)}")
    lines += [f"  {t['file']}: {t['name']}, DOB {t['dob']} -> {t['folder']}" for t in no_file_done] or ["  none"]
    lines.append("")
    lines.append(f"Tickets without records (not done, patient not found or no red dots): {len(no_file)}")
    lines += [f"  {t['file']}: {t['name']}, DOB {t['dob']}" for t in no_file]
    return "\n".join(lines)
