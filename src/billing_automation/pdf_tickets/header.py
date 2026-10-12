"""Reading the ticket header table cell by cell (Windows OCR with Tesseract as a fallback)."""
from __future__ import annotations

import os
import re
import subprocess

from ..tesseract import TESSERACT_PATH as TESSERACT
from .text_fixes import _DIGITS, _TIME_RE, _fix_time_value, _fix_value, _norm_time, _snap_label, to_ascii


HEADER_PART = 0.29   # the header is the top 29% of the page
HEADER_DPI = 300


def _ink_lines(cell):
    """Lines of text in a cell: [(top, bottom)] in pixels."""
    ink = (cell < 128).any(axis=1)
    lines, start = [], None
    for i, v in enumerate(ink):
        if v and start is None:
            start = i
        elif not v and start is not None:
            lines.append((start, i))
            start = None
    if start is not None:
        lines.append((start, len(ink)))
    return lines


def _ocr_array(ocr, arr, pad=30):
    """Words of an image (numpy, gray) in its own coordinates: [(text, x, y, width, height)]."""
    import numpy as np
    padded = np.pad(arr, pad, constant_values=255)
    words = ocr.words(padded.tobytes(), padded.shape[1], padded.shape[0])
    return [(to_ascii(t), x - pad, y - pad, w, h) for t, x, y, w, h in words if to_ascii(t).strip()]


def _ocr_tiled(ocr, arr):
    """Short value (a single letter 'M', '-5525'): Windows OCR skips single characters,
    so the image is repeated 3 times in a row and the first reading is taken."""
    import numpy as np
    gap = np.full((arr.shape[0], 40), 255, np.uint8)
    words = _ocr_array(ocr, np.hstack([arr, gap, arr, gap, arr]))
    return " ".join(w[0] for w in words if w[1] < arr.shape[1] + 20)


# header cell labels by table row (as printed on the form); empty - a cell without a label
HEADER_LAYOUT = [
    ["LAST NAME", "FIRST NAME", "MIDDLE NAME", "SSN", "DOB", "AGE", "SEX", "MEDICAL RECORD",
     "CREATE DATE", "SEQ NO"],
    ["PATIENT ADDRESS", "PHONE", "APPOINTMENT", "DETAILS"],
    ["INSURANCE INFORMATION", "GROUP NAME", "GROUP NUMBER", "POLICY NUMBER", "EVENT"],
    ["RENDERING PHYSICIAN NAME", "REFERRING PHYSICIAN NAME", "REFERRING location", "LAST PRIMARY DX",
     "", "ENCOUNTER"],
    ["AMOUNT OF LAST PAYMENT", "DATE OF LAST PAYMENT", "CHART BALANCE", "PATIENT INS BALANCE",
     "PATIENT SELF BALANCE", "Old Chart Number", ""],
]


def _ocr_tesseract(arr):
    """Fallback single-line recognition (Tesseract, English): short values
    like 'HN' that Windows OCR does not see. No Tesseract - empty string."""
    import numpy as np
    import pymupdf
    if not os.path.exists(TESSERACT):
        return ""
    padded = np.ascontiguousarray(np.pad(arr, 20, constant_values=255))
    png = pymupdf.Pixmap(pymupdf.csGRAY, padded.shape[1], padded.shape[0], padded.tobytes(), False).tobytes("png")
    try:
        res = subprocess.run([TESSERACT, "stdin", "stdout", "-l", "eng", "--psm", "7"], input=png,
                             capture_output=True, timeout=20, creationflags=0x08000000)
    except (OSError, subprocess.SubprocessError):
        return ""
    return to_ascii(res.stdout.decode("utf-8", "ignore")).strip()


def _table_cells(gray):
    """Cells of the top table: [(x0, y0, x1, y1, label from the form or None)]; [] - table not found."""
    dark = gray < 128

    def centers(mask):
        out = []
        for i in mask.nonzero()[0]:
            if out and i - out[-1][1] <= 3:
                out[-1][1] = i
            else:
                out.append([i, i])
        return [(a + b) // 2 for a, b in out]

    rows = centers(dark.mean(axis=1) > 0.5)
    bands = []
    for y0, y1 in zip(rows, rows[1:]):
        if y1 - y0 < 25:
            continue
        cols = centers(dark[y0 + 3:y1 - 2].mean(axis=0) > 0.9)
        band = [(x0, y0, x1, y1) for x0, x1 in zip(cols, cols[1:]) if x1 - x0 > 15]
        if band:   # a band without cells (the gap below the table) is not a table row
            bands.append(band)
    # labels are taken by cell position if the table rows match the form
    layout_ok = [len(b) for b in bands] == [len(r) for r in HEADER_LAYOUT]
    cells = [(*box, HEADER_LAYOUT[i][j] if layout_ok else None)
             for i, band in enumerate(bands) for j, box in enumerate(band)]
    return (rows, cells) if len(cells) >= 20 else (rows, [])


def _name_overflow(ocr, gray, top, bottom, x0, x1, fx1):
    """A last name longer than its cell runs over the line into the FIRST NAME cell ('MONTGOMER|YJANE').
    The strip is read across the line and cut where the first name usually starts.
    Returns (last name, (x, y, width, height) from the cell corner, cut x in the image) or None."""
    rows = gray[top:bottom]
    ink = rows < 128
    if not (ink[:, x1 - 8:x1 - 2].any() and ink[:, x1 + 3:x1 + 9].any()):
        return None   # the last name fits into the cell
    ox = x0 + 5
    strip = rows[:, ox:fx1 - 4].copy()
    lx = x1 - ox
    # erase the vertical line, but a letter on the line (the 'Y' in MONTGOMERY) stays whole:
    # where there is ink both left and right of the line, the line is painted as part of the letter
    both = (strip[:, lx - 3] < 128) & (strip[:, lx + 3] < 128)
    both[1:] |= both[:-1].copy()
    strip[:, lx - 2:lx + 3] = 255
    strip[both, lx - 2:lx + 3] = 0
    cols = (strip < 128).sum(axis=0)
    filled = cols.nonzero()[0]
    if not len(filled):
        return None
    start = filled[0]
    expected = lx + start   # the first name starts at the same offset from the line as the last name from its own
    window = range(max(lx + 3, expected - 14), min(expected + 3, len(cols)))
    if not len(window):
        return None
    split = min(window, key=lambda i: (cols[i], abs(i - expected)))
    part = strip[:, :split]
    text = " ".join(w[0] for w in _ocr_array(ocr, part)) or _ocr_tesseract(part)
    if not text:
        return None
    ys = ink.any(axis=1).nonzero()[0]
    y_top = ys[0] if len(ys) else 0
    return text, (start, y_top, split - start, (ys[-1] - y_top + 1) if len(ys) else bottom - top), ox + split


def read_header(page, ocr):
    """Ticket header: [{"label", "value", "words": [(text, x, y, width, height) in points]}]
    or None if there is no header table on the page."""
    import numpy as np
    import pymupdf
    clip = pymupdf.Rect(0, 0, page.rect.width, page.rect.height * HEADER_PART)
    pix = page.get_pixmap(dpi=HEADER_DPI, colorspace=pymupdf.csGRAY, alpha=False, clip=clip)
    gray = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width)
    rows, boxes = _table_cells(gray)
    if not boxes:
        return None
    k = 72 / HEADER_DPI
    result = []
    # above the table - clinic name and address
    if rows[0] > 20:
        words = _ocr_array(ocr, gray[:rows[0] - 3])
        words = [(_snap_label(t), x, y, w, h) for t, x, y, w, h in words]
        result.append({"label": "", "value": " ".join(w[0] for w in words),
                       "words": [(t, x * k, y * k, w * k, h * k) for t, x, y, w, h in words]})
    name_split = None   # where in the image the last name that ran into the FIRST NAME cell ends
    for x0, y0, x1, y1, layout_label in boxes:
        ox, oy = x0 + 5, y0 + 4   # without the table lines (otherwise a line is read as 'I' or '1')
        cell = gray[oy:y1 - 3, ox:x1 - 4]
        lines = [ln for ln in _ink_lines(cell) if ln[1] - ln[0] >= 12]   # specks are not text lines
        if not lines:
            continue
        # the label is the small first line of the cell; if it merged with the value, its height is taken from the font
        top0, bottom0 = lines[0]
        label_bottom = bottom0 + 2 if bottom0 - top0 <= 26 else top0 + 24
        if layout_label == "":
            label_bottom = 0   # a cell without a label
        if layout_label == "FIRST NAME" and name_split is not None and name_split > ox:
            cell = cell.copy()
            cell[label_bottom:, :name_split - ox] = 255   # the tail of the last name was already read in LAST NAME
        words = _ocr_array(ocr, cell)
        label_words = [(_snap_label(t), x, y, w, h) for t, x, y, w, h in words if y + h / 2 < label_bottom]
        value_words = [w for w in words if w[2] + w[4] / 2 >= label_bottom]
        label = " ".join(w[0] for w in label_words)
        if layout_label:
            # label exactly as on the form (OCR of small labels sometimes errs or misses them)
            label, names = layout_label, layout_label.split()
            if len(label_words) == len(names):
                label_words = [(n, *w[1:]) for n, w in zip(names, label_words)]
            else:
                ink = (cell[top0:label_bottom] < 128).any(axis=0).nonzero()[0]
                lx = ink[0] if len(ink) else 0
                label_words = [(label, lx, top0, max((ink[-1] - lx) if len(ink) else 1, 1),
                                label_bottom - 2 - top0)]
        if label.upper() == "SSN" or (not value_words and any(ln[0] >= label_bottom - 2 for ln in lines)):
            # the value is in the image, but OCR did not see it (single letter 'M'; '###-##-5525')
            top = max(label_bottom - 2, 0)
            part = cell[top:]
            ink_rows = (part < 128).any(axis=1).nonzero()[0]
            cols = (part < 128).any(axis=0).nonzero()[0]
            text = ""
            if len(cols) and len(ink_rows):
                part = part[max(ink_rows[0] - 3, 0):ink_rows[-1] + 4]
                top += max(ink_rows[0] - 3, 0)
                left, right = max(cols[0] - 5, 0), cols[-1] + 6
                part = part[:, left:right]
                if label.upper() == "SSN":   # '###' is unreadable - take the last 4 digits
                    # the number often sticks out past the right cell line - capture the tail up to a space
                    wide = gray[oy + top:oy + top + part.shape[0], ox + left:min(x1 + 60, gray.shape[1])].copy()
                    line_x = x1 - ox - left
                    wide[:, max(line_x - 2, 0):line_x + 3] = 255   # erase the vertical line
                    blank = ~(wide < 128).any(axis=0)
                    end, run = wide.shape[1], 0
                    for i in range(line_x + 3, wide.shape[1]):
                        run = run + 1 if blank[i] else 0
                        if run >= 6:
                            end = i - run + 2
                            break
                    part = wide[:, :end]
                    for start in (0.5, 0.4, 0.6):
                        tail = _ocr_tiled(ocr, part[:, int(part.shape[1] * start):])
                        digits = re.sub(r"\D", "", tail.translate(_DIGITS))
                        if len(digits) >= 4:
                            break
                    text = f"###-##-{digits[-4:]}" if len(digits) >= 4 else ""
                else:
                    text = _ocr_tiled(ocr, part) or _ocr_tesseract(part)
            if text:
                value_words = [(text, left, top, right - left, part.shape[0])]
            elif label.upper() == "SSN":
                value_words = []
        if layout_label == "LAST NAME":
            fn = next((b for b in boxes if b[4] == "FIRST NAME"), None)
            over = fn and _name_overflow(ocr, gray, oy + label_bottom, y1 - 3, x0, x1, fn[2])
            if over:
                text, (vx, vy, vw, vh), name_split = over
                value_words = [(text, vx, label_bottom + vy, vw, vh)]
        value = _fix_value(label, " ".join(w[0] for w in value_words))
        if label.upper() in ("DOB", "CREATE DATE", "DATE OF LAST PAYMENT") and value \
                and not re.fullmatch(r"\d\d/\d\d/\d\d(\d\d)?", value):
            # the date was read incompletely ('01' instead of '01/04/2024') - read the value line with Tesseract
            top1, bottom1 = lines[-1]
            tess = _fix_value(label, _ocr_tesseract(cell[max(top1 - 3, 0):bottom1 + 3]))
            value = tess if re.fullmatch(r"\d\d/\d\d/\d\d(\d\d)?", tess) else value
        if label.upper() in ("APPOINTMENT", "EVENT") and value and not _TIME_RE.search(value):
            # time not parsed (Windows OCR loses ':00') - read the time line with Tesseract
            top1, bottom1 = lines[-1]
            tess = _ocr_tesseract(cell[max(top1 - 3, 0):bottom1 + 3])
            if label.upper() == "EVENT":
                fixed = _fix_time_value("EVENT", tess)
                value = fixed if _TIME_RE.search(fixed) else value
            else:
                t = _norm_time(re.split(r"T\w{1,3}e:?", tess)[-1], False)
                if t:
                    value = (value.split("Time:")[0] if "Time:" in value else value + " ") + f"Time: {t}"
        if value_words and len(value_words) == len(value.split()):
            value_words = [(t, *w[1:]) for t, w in zip(value.split(), value_words)]
        elif value_words:   # the number of words changed - one word for the whole value
            xs = [w[1] for w in value_words] + [w[1] + w[3] for w in value_words]
            ys = [w[2] for w in value_words] + [w[2] + w[4] for w in value_words]
            value_words = [(value, min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))]
        result.append({"label": label, "value": value,
                       "words": [(t, (x + ox) * k, (y + oy) * k, w * k, h * k)
                                 for t, x, y, w, h in label_words + value_words]})
    return result


def header_fields(header):
    """{CELL LABEL (upper case): value} from read_header."""
    return {c["label"].upper(): c["value"] for c in header if c["label"]}
