"""A single ticket PDF: blank page detection, header fields and the key used to find reprints."""
from __future__ import annotations

import os
import re

from .header import header_fields, read_header


# gray pixel byte -> 1 if the pixel is dark (< 200), otherwise 0
_DARK = bytes(1 if v < 200 else 0 for v in range(256))


def is_blank(path):
    """Blank page: almost no dark pixels on any page.

    When printing "Pages 87 to 87", MedLedger sends blank pages instead of pages 1-86.
    """
    try:
        import pymupdf
    except ImportError:
        return False  # without pymupdf the check is impossible - assume the page is not blank
    with pymupdf.open(path) as doc:
        for page in doc:
            pix = page.get_pixmap(dpi=40, colorspace=pymupdf.csGRAY, alpha=False)
            if pix.samples.translate(_DARK).count(1) > len(pix.samples) * 0.002:
                return False
    return True


def file_complete(path, last_sizes):
    """PDF24 has finished writing the file: the size has not changed since the last check and the file opens."""
    try:
        size = os.path.getsize(path)
    except OSError:
        return False
    prev = last_sizes.get(path)
    last_sizes[path] = size
    if size == 0 or size != prev:
        return False
    try:
        with open(path, "rb+"):
            return True
    except OSError:
        return False


def read_ticket(path, ocr):
    """SEQ NO, patient, date, appointment time, doctor from the ticket header (or a 'blank page' mark)."""
    import pymupdf
    if is_blank(path):
        return {"blank": True}
    with pymupdf.open(path) as doc:
        header = read_header(doc[0], ocr)
        if header is None:
            return _read_ticket_text(doc[0], ocr)
    f = header_fields(header)
    created = re.fullmatch(r"(\d\d)/(\d\d)/(\d\d)", f.get("CREATE DATE", "").replace(" ", ""))
    seq = re.fullmatch(r"\d{1,4}", f.get("SEQ NO", "").strip())
    dob = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", f.get("DOB", ""))
    tm = re.search(r"\b(\d{1,2}:\d{2}) ?([AP])", f.get("APPOINTMENT", "") + " " + f.get("EVENT", ""))
    name = " ".join(x for x in (f.get("LAST NAME", ""), f.get("FIRST NAME", "")) if x).strip()
    name = " ".join(re.sub(r"[^A-Za-z.'\- ]", "", name).split())   # 'DOE\, JOHN' -> 'DOE JOHN'
    date = created.group(0) if created else None
    return {
        "seq": int(seq.group(0)) if seq and date else None,
        "date": date if seq else "?",
        "time": (tm.group(1) + tm.group(2) + "M") if tm else "?",
        "name": name or "?",
        "dob": f"{int(dob.group(1)):02d}/{int(dob.group(2)):02d}/{dob.group(3)}" if dob else None,
        "created": date,
        "physician": f.get("RENDERING PHYSICIAN NAME", ""),
    }


def _read_ticket_text(page, ocr):
    """Fallback (header table not found): look for the fields in the text at the top of the page."""
    import pymupdf
    pix = page.get_pixmap(dpi=200, colorspace=pymupdf.csGRAY, alpha=False)
    # the ticket header is the top 30% of the page; words left to right, line by line
    words = [w for w in ocr.words(pix.samples, pix.width, pix.height) if w[2] < pix.height * 0.30]
    words.sort(key=lambda w: (round(w[2] / 15), w[1]))
    text = " ".join(w[0] for w in words)
    physician = _rendering_physician(words)
    # SEQ NO comes in the header right after CREATE DATE: '... 10/13/26 214'
    seq = re.search(r"\b(\d\d/\d\d/\d\d) (\d{1,4})\b(?! ?/)", text)
    tm = re.search(r"\b(\d{1,2}:\d{2}) ?([AP])M?\b", text)
    name = re.search(r"SEQ NO (.+?) (?:#|\d)", text)
    # date of birth - the first header date with a 4-digit year (CREATE DATE has a 2-digit year)
    dob = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", text)
    # creation date in case SEQ NO was not recognized: the first date with a 2-digit year
    created = re.search(r"\b(\d\d/\d\d/\d\d)\b(?!/)", text)
    return {
        "seq": int(seq.group(2)) if seq else None,
        "date": seq.group(1) if seq else "?",
        "time": (tm.group(1) + tm.group(2) + "M") if tm else "?",
        "name": name.group(1).strip() if name else "?",
        "dob": f"{int(dob.group(1)):02d}/{int(dob.group(2)):02d}/{dob.group(3)}" if dob else None,
        "created": created.group(1) if created else None,
        "physician": physician,
    }


def _rendering_physician(words):
    """Text under the RENDERING PHYSICIAN NAME heading (e.g. 'Smith, John'; OCR may be inaccurate)."""
    head = next((w for w in words if w[0].upper().startswith("RENDER")), None)
    if head is None:
        return ""
    _, x, y, _, h = head[:5]
    # right column border - the heading of the neighbouring REFERRING column on the same line
    right = min((w[1] for w in words if w[0].upper().startswith("REFERR") and abs(w[2] - y) < h
                 and w[1] > x), default=x + 330)
    below = [w for w in words if y + h < w[2] < y + h * 5 and x - h <= w[1] < right - 5]
    below.sort(key=lambda w: (round(w[2] / 15), w[1]))
    return " ".join(w[0] for w in below)


def ticket_key(info):
    """Ticket key: creation date + SEQ + date of birth + name. None if something could not be read.

    Files of the same ticket differ byte by byte (each printout has its own "TIME PRINTED"),
    so what is printed in the header is compared.
    """
    if not info or info.get("blank"):
        return None
    name = " ".join((info.get("name") or "").upper().split())
    if not info.get("dob") or name in ("", "?"):
        return None
    if info.get("seq") is not None and info.get("date") not in (None, "?"):
        return f"{info['date']}|{info['seq']}|{info['dob']}|{name}"
    # SEQ NO not recognized (it is not visible on some tickets) - creation date + appointment time
    if info.get("created"):
        return f"{info['created']}|noseq|{info.get('time') or '?'}|{info['dob']}|{name}"
    return None
