"""OCR of screen regions: date of birth, patient name and the MedLedger ticket counter."""
from __future__ import annotations

import re
from collections import Counter

import cv2
import numpy as np
import pytesseract
from PIL import ImageGrab
from thefuzz import fuzz

from .state import wait_if_paused


def correct_ocr_field(field_str, min_val, max_val, allow_leading_fix=True):
    """
    Checks a numeric date field (month/day/year) against the allowed range
    [min_val, max_val]. If out of range, tries to fix a typical Tesseract
    error: it often confuses the digit '1' with '4' (they look alike in some fonts):

      Step 1: replace ALL '4's with '1' and check the range.
             Example: month '14' -> '11', day '34' -> '31'.
      Step 2: if that fails, try replacing only ONE '4' at a time
             (in case only some of the digits are wrong).
      Step 3: if the field is still out of range, try fixing the leading digits
             (year clearly in the wrong century/decade; for 2-digit fields - the first digit).

    Returns a tuple (fixed_string, was_corrected).
    """
    value = int(field_str)
    if min_val <= value <= max_val:
        return field_str, False

    # Step 1: replace all '4's with '1' at once (the most common OCR error)
    if '4' in field_str:
        candidate = field_str.replace('4', '1')
        if min_val <= int(candidate) <= max_val:
            return candidate, True

        # Step 2: replace one '4' at a time
        for i, ch in enumerate(field_str):
            if ch == '4':
                candidate = field_str[:i] + '1' + field_str[i + 1:]
                if min_val <= int(candidate) <= max_val:
                    return candidate, True

    if not allow_leading_fix:
        return field_str, False

    # Step 3a: 4-digit field (year) - wrong century/decade
    if len(field_str) == 4:
        if value < min_val:
            candidate = '19' + field_str[2:]
            if min_val <= int(candidate) <= max_val:
                return candidate, True
        elif value > max_val:
            candidate = '20' + field_str[2:]
            if min_val <= int(candidate) <= max_val:
                return candidate, True

    # Step 3b: 2-digit field (month/day) - try fixing the first digit
    if len(field_str) == 2:
        for first_digit in ('1', '0'):
            candidate = first_digit + field_str[1]
            if min_val <= int(candidate) <= max_val:
                return candidate, True

    return field_str, False

def parse_date_positional(text):
    """
    Fallback positional date parsing - in case Tesseract distorted
    or completely "ate" the separators. The date is always written as
    XX/XX/XXXX (10 characters including separators), so:
      - length 10: the separators are at positions 2 and 5, WHATEVER they were
        recognized as ('/' is often confused with the digit '1'). We simply drop
        the characters at those positions and take the rest as month/day/year.
      - length 8: the separators are missing entirely -> read as MMDDYYYY.

    Returns (month_str, day_str, year_str) or None if the string fits
    none of these cases.
    """
    t = text.strip()

    if len(t) == 10 and t[0:2].isdigit() and t[3:5].isdigit() and t[6:10].isdigit():
        return t[0:2], t[3:5], t[6:10]

    only_digits = re.sub(r'\D', '', t)
    if len(only_digits) == 8:
        return only_digits[0:2], only_digits[2:4], only_digits[4:8]

    return None

def fix_month_in_date(text):
    """
    Fixes OCR errors in a date in MM/DD/YYYY format (or with '-' '.' separators).
    Each field has an allowed range:
      - month: 1-12
      - day:   1-31
      - year:  1900 < year < 2030 (strictly)
    The main typical Tesseract error is confusing '1' and '4', so values such
    as 14 (month) or 34 (day) almost always actually mean 11 and 31.
    Example: 14/34/2001 -> 11/31/2001

    If the strict format with a separator is not recognized (e.g. '/' was read
    as '1' and the whole date "merged" into digits), positional parsing is tried
    via parse_date_positional() - the date is always written as XX/XX/XXXX,
    so the positions of month/day/year are known in advance.
    """
    text_stripped = text.strip()
    m = re.match(r'^(\d{2})([\/\-\.])(\d{2})\2(\d{4})$', text_stripped)
    if m:
        month_str = m.group(1)
        sep       = m.group(2)
        day_str   = m.group(3)
        year_str  = m.group(4)
    else:
        parsed = parse_date_positional(text_stripped)
        if not parsed:
            return text
        month_str, day_str, year_str = parsed
        sep = '/'
        print(f"   [SEPARATOR FILTER] '{text_stripped}' -> parsed positionally as "
              f"{month_str}/{day_str}/{year_str} (separator not recognized or confused with a digit)")

    # Fix the month (1-12)
    fixed_month, changed = correct_ocr_field(month_str, 1, 12)
    if changed:
        print(f"   [MONTH FIX] '{month_str}' -> '{fixed_month}' (OCR confused 1/4 or another digit)")
    month_str = fixed_month

    # Fix the day (1-31)
    fixed_day, changed = correct_ocr_field(day_str, 1, 31)
    if changed:
        print(f"   [DAY FIX] '{day_str}' -> '{fixed_day}' (OCR confused 1/4 or another digit)")
    day_str = fixed_day

    # Fix the year (strictly between 1900 and 2030)
    fixed_year, changed = correct_ocr_field(year_str, 1901, 2029)
    if changed:
        print(f"   [YEAR FIX] '{year_str}' -> '{fixed_year}' (OCR confused a digit or the century/decade)")
    year_str = fixed_year

    text = month_str + sep + day_str + sep + year_str
    return text

def _preprocess_date_image(img_cv):
    """
    Returns several differently processed variants of the date image.

    Previously there was only one variant (x2 upscale + adaptiveThreshold), so
    Tesseract sometimes confused VISUALLY similar digits that are BOTH valid
    within the range - the typical case is "5" <-> "9" (unlike "1"/"4", the
    range check in correct_ocr_field does not catch this: both day 05 and day 09
    are valid, so the quality/number of OCR passes has to be increased
    instead of trying to guess after the fact).

    A larger upscale (x6 instead of x2) gives the digits more "body" - the closed
    top loop of a "9" is noticeably thicker and smoother than that of a "5", and on a small/blurry
    image this difference is the first thing to be lost.
    """
    variants = []

    # Variant 1: strong upscale + sharpening + adaptive threshold (as before, but larger)
    big = cv2.resize(img_cv, None, fx=6, fy=6, interpolation=cv2.INTER_CUBIC)
    gray = cv2.cvtColor(big, cv2.COLOR_BGR2GRAY)
    kernel = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]])
    sharp = cv2.filter2D(gray, -1, kernel)
    thresh1 = cv2.adaptiveThreshold(
        sharp, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 15, 4
    )
    variants.append(thresh1)

    # Variant 2: OTSU - a different threshold algorithm, often draws digit loops differently
    _, thresh2 = cv2.threshold(sharp, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    variants.append(thresh2)

    # Variant 3: moderate upscale (x3) without sharpening - sometimes better for small fonts,
    # since strong sharpening can "break" the thin bridge in the loop of a "9"
    medium = cv2.resize(img_cv, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    gray_m = cv2.cvtColor(medium, cv2.COLOR_BGR2GRAY)
    thresh3 = cv2.adaptiveThreshold(
        gray_m, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2
    )
    variants.append(thresh3)

    # Variant 4: inverted main variant
    variants.append(cv2.bitwise_not(thresh1))

    return variants


def read_date_from_region(region):
    """
    Reads the date in several ways (different image processing + different
    Tesseract configs) and picks the result by VOTING on each digit separately.

    Why voting instead of a single attempt: the "5"<->"9" error almost never
    repeats identically across all image/engine variants at once - it
    comes from specific quirks of ONE particular pass
    (threshold/sharpening/antialiasing). If the correct digit is the majority and the
    error is a random "outlier" in 1-2 passes, voting cancels it out.
    """
    wait_if_paused()
    img = ImageGrab.grab(bbox=(region[0], region[1], region[0]+region[2], region[1]+region[3]))
    img_cv = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)

    variants = _preprocess_date_image(img_cv)

    ocr_configs = [
        '--oem 1 --psm 7 -c tessedit_char_whitelist=0123456789./- ',  # LSTM, single line
        '--oem 3 --psm 7 -c tessedit_char_whitelist=0123456789./- ',  # default engine
        '--oem 1 --psm 8 -c tessedit_char_whitelist=0123456789./- ',  # LSTM, "single word"
    ]

    parsed_candidates = []  # list of tuples (month_str, day_str, year_str) before range correction
    raw_debug = []

    for img_variant in variants:
        for cfg in ocr_configs:
            raw = pytesseract.image_to_string(img_variant, lang='eng', config=cfg).strip()
            raw = raw.strip(' \n\r\t')
            if not raw:
                continue
            raw_debug.append(raw)

            m = re.match(r'^(\d{2})([\/\-\.])(\d{2})\2(\d{4})$', raw)
            if m:
                parsed_candidates.append((m.group(1), m.group(3), m.group(4)))
                continue

            positional = parse_date_positional(raw)
            if positional:
                parsed_candidates.append(positional)

    print(f"   [DATE-DEBUG] All OCR variants: {raw_debug}")

    if not parsed_candidates:
        # Nothing was recognized in any variant - return empty, as before
        return "", img_cv

    # Vote on each digit position separately (month: 2 digits, day: 2 digits,
    # year: 4 digits) - regardless of which variant/config it came from.
    def vote_field(values):
        length = len(values[0])
        result = []
        for pos in range(length):
            digits_at_pos = [v[pos] for v in values if len(v) == length]
            if not digits_at_pos:
                digits_at_pos = [v[pos] for v in values if len(v) > pos]
            most_common = Counter(digits_at_pos).most_common(1)[0][0]
            result.append(most_common)
        return ''.join(result)

    months = [c[0] for c in parsed_candidates]
    days = [c[1] for c in parsed_candidates]
    years = [c[2] for c in parsed_candidates]

    month_str = vote_field(months)
    day_str = vote_field(days)
    year_str = vote_field(years)

    if len(parsed_candidates) > 1:
        print(f"   [DATE-DEBUG] Candidates (month/day/year): {parsed_candidates} -> vote: "
              f"{month_str}/{day_str}/{year_str}")

    text = f"{month_str}/{day_str}/{year_str}"
    text = fix_month_in_date(text)
    return text, img_cv


def clean_ocr_name(text):
    """
    Completely removes junk characters that Tesseract sometimes
    recognizes instead of letters or separators (|, _, [], {}, ~, ` etc.).
    Unlike .strip(), the characters are removed from ANY position in the string, not just the edges.
    """
    cleaned = re.sub(r'[|_\[\]{}~`^*]', '', text)
    # Collapse spaces that may remain after removing characters
    cleaned = re.sub(r'[ \t]+', ' ', cleaned)
    # Remove spaces around line breaks
    cleaned = re.sub(r'\s*\n\s*', '\n', cleaned).strip()
    return cleaned

def _remove_grid_lines(gray):
    """
    Removes thin table/field-border lines (as on a form with the cells
    LAST NAME / FIRST NAME) - if a border runs close to the first or
    last letter, Tesseract may "eat" the whole letter together with the line
    (a typical reason why the first letter of a word disappears, e.g.
    'SMITH' -> 'MITH') or, conversely, glue a piece of the line to a letter and
    distort its shape.

    Uses morphological opening with a long horizontal/vertical
    kernel: only long straight lines (the border) remain, they are subtracted from the
    image, and the short letter strokes are not affected.
    """
    _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    horizontal_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (25, 1))
    horizontal_lines = cv2.morphologyEx(bw, cv2.MORPH_OPEN, horizontal_kernel, iterations=1)

    vertical_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 25))
    vertical_lines = cv2.morphologyEx(bw, cv2.MORPH_OPEN, vertical_kernel, iterations=1)

    lines_mask = cv2.bitwise_or(horizontal_lines, vertical_lines)
    cleaned = cv2.bitwise_and(bw, cv2.bitwise_not(lines_mask))
    # Return in normal polarity (black text on a white background)
    return cv2.bitwise_not(cleaned)


def _preprocess_name_image(img_cv):
    """
    Several variants of processing the name image for OCR.

    IMPORTANT: before processing, white margins (padding) are added on all sides.
    If the calibrated region is cropped tight to the text, the outermost
    letter (e.g. the first 'S' in 'SMITH') may be slightly clipped at the edge -
    Tesseract then either does not recognize it at all or confuses it with another
    character. A white margin removes this effect almost for free.
    """
    variants = []

    padded = cv2.copyMakeBorder(img_cv, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=(255, 255, 255))

    # Variant 1: x4 upscale + adaptive threshold (the main working variant)
    big = cv2.resize(padded, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
    gray = cv2.cvtColor(big, cv2.COLOR_BGR2GRAY)
    thresh1 = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 15, 4
    )
    variants.append(thresh1)

    # Variant 2: the same, but with the table border lines removed
    variants.append(_remove_grid_lines(gray))

    # Variant 3: OTSU without adaptive threshold - sometimes cleaner on a flat background
    _, thresh3 = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    variants.append(thresh3)

    # Variant 4: moderate x2 upscale (as before) - kept in case
    # a larger scale "overdoes" the sharpening somewhere
    medium = cv2.resize(padded, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    gray_m = cv2.cvtColor(medium, cv2.COLOR_BGR2GRAY)
    thresh4 = cv2.adaptiveThreshold(
        gray_m, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2
    )
    variants.append(thresh4)

    return variants


NAME_REGION_EXTRA_WIDTH = 350  # px of extra width to the right to find the real end of the field (see _auto_widen_region_for_text)


def _auto_widen_region_for_text(region, extra_width=NAME_REGION_EXTRA_WIDTH):
    """
    Solves the problem of long names (like 'WOLFESCHLEGEL') that do not fit into
    the width calibrated for short names (like 'SMITH') and are simply
    cut off at the right edge of the calibration frame.

    Idea: calibration sets ONLY the left edge and the top of the field correctly (the name
    always starts at the same place), while the width is taken with a margin (+extra_width
    pixels to the right of the original) and then TRIMMED back based on the actual content:
      1) if a vertical cell border line (the boundary of the
         "FIRST NAME" column, etc.) is found to the right - trim at it;
      2) if there is no line - trim at the actual right edge of the text
         (the last column with dark pixels) + a small margin.

    This works both for a short 'SMITH' and a long 'WOLFESCHLEGEL' -
    the width is recalculated from the content every time instead of being taken from
    the old calibration.
    """
    x, y, w, h = region
    wide_w = w + extra_width
    img = ImageGrab.grab(bbox=(x, y, x + wide_w, y + h))
    gray = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2GRAY)

    _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    # 1) Look for a vertical border line to the right of the original calibrated width
    #    (with a small -20px margin in case the border extends slightly inward)
    vertical_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(5, int(h * 0.6))))
    vertical_lines = cv2.morphologyEx(bw, cv2.MORPH_OPEN, vertical_kernel, iterations=1)
    col_has_line = vertical_lines.sum(axis=0) > 0
    search_start = max(0, w - 20)
    line_cols = np.where(col_has_line[search_start:])[0]

    border_x = int(search_start + line_cols[0]) if len(line_cols) > 0 else None

    # 2) Find the actual right edge of the text (up to the border line, if found)
    text_area = bw[:, :border_x] if border_x is not None else bw
    col_has_text = text_area.sum(axis=0) > 0
    text_cols = np.where(col_has_text)[0]
    text_right = int(text_cols[-1]) + 15 if len(text_cols) > 0 else w  # +15px margin on the right

    if border_x is not None:
        final_w = border_x
    else:
        final_w = max(w, text_right)

    final_w = min(final_w, wide_w)
    print(f"   [NAME-DEBUG] Field width: calibration={w}px -> actual={final_w}px "
          f"(border={border_x}, text edge={text_right if border_x is None else 'n/a'})")

    return (x, y, final_w, h)


def read_name_from_region(region):
    """
    Reads the name in several ways (different image processing + different
    Tesseract configs/engines), then picks the best result by MEAN OCR
    CONFIDENCE (confidence from image_to_data) instead of taking the first one.

    Unlike the date (plain digits, positional voting is possible), the text here has
    variable length - so instead of per-character voting the candidates are
    compared with each other (fuzzy) and their confidence is summed: the most
    "popular" variant with the highest confidence wins.

    Before recognition the field width is recalculated for the actual
    content (see _auto_widen_region_for_text) - this fixes truncation of
    long names that did not fit into the originally calibrated width.
    """
    wait_if_paused()
    region = _auto_widen_region_for_text(region)
    img = ImageGrab.grab(bbox=(region[0], region[1], region[0]+region[2], region[1]+region[3]))
    img_cv = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)

    variants = _preprocess_name_image(img_cv)

    ocr_configs = [
        '--oem 1 --psm 6',
        '--oem 3 --psm 6',
        '--oem 1 --psm 7',
    ]

    candidates = []  # (text, mean_conf)
    raw_debug = []

    for img_variant in variants:
        for cfg in ocr_configs:
            data = pytesseract.image_to_data(img_variant, lang='eng', config=cfg, output_type=pytesseract.Output.DICT)
            words = []
            confs = []
            for i in range(len(data['text'])):
                w = data['text'][i].strip()
                c = int(data['conf'][i])
                if w and c >= 0:
                    words.append(w)
                    confs.append(c)
            if not words:
                continue
            text = clean_ocr_name(' '.join(words))
            if not text:
                continue
            mean_conf = sum(confs) / len(confs)
            raw_debug.append(f"{text!r}(conf={mean_conf:.0f})")
            candidates.append((text, mean_conf))

    print(f"   [NAME-DEBUG] All OCR variants: {raw_debug}")

    if not candidates:
        return "", img_cv

    # Group similar candidates (fuzzy) so that the "majority" votes
    # for one spelling even if case/spaces differ slightly.
    groups = []  # each item: {'texts': [...], 'total_conf': x, 'best_text': str, 'best_conf': x}
    for text, conf in candidates:
        placed = False
        for g in groups:
            if fuzz.token_sort_ratio(text.lower(), g['best_text'].lower()) >= 85:
                g['texts'].append(text)
                g['total_conf'] += conf
                if conf > g['best_conf']:
                    g['best_text'] = text
                    g['best_conf'] = conf
                placed = True
                break
        if not placed:
            groups.append({'texts': [text], 'total_conf': conf, 'best_text': text, 'best_conf': conf})

    # The group with the highest total confidence wins (this accounts both for the variant
    # being more "popular" and for it being recognized more confidently)
    best_group = max(groups, key=lambda g: g['total_conf'])
    final_text = best_group['best_text']

    if len(groups) > 1:
        print(f"   [NAME-DEBUG] Candidate groups: {[(g['best_text'], round(g['total_conf'])) for g in groups]} "
              f"-> chosen: '{final_text}'")

    return final_text, img_cv


def _preprocess_counter_image(img_cv):
    """Returns several image processing variants for OCR."""
    variants = []

    # Variant 1: x4 upscale + adaptive threshold
    big = cv2.resize(img_cv, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
    gray = cv2.cvtColor(big, cv2.COLOR_BGR2GRAY)
    # sharpening
    kernel = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]])
    sharp = cv2.filter2D(gray, -1, kernel)
    thresh1 = cv2.adaptiveThreshold(
        sharp, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 15, 4
    )
    variants.append(thresh1)

    # Variant 2: OTSU at x4
    _, thresh2 = cv2.threshold(sharp, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    variants.append(thresh2)

    # Variant 3: inverted (white text on a dark background)
    variants.append(cv2.bitwise_not(thresh1))

    return variants


def read_ticket_counter(reg_ticket_counter):
    wait_if_paused()
    img = ImageGrab.grab(bbox=(
        reg_ticket_counter[0], reg_ticket_counter[1],
        reg_ticket_counter[0] + reg_ticket_counter[2],
        reg_ticket_counter[1] + reg_ticket_counter[3]
    ))
    img_cv = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)

    variants = _preprocess_counter_image(img_cv)

    # OCR configs: first allow digits + "of", then digits only
    ocr_configs = [
        '--psm 7 -c tessedit_char_whitelist=0123456789of ',   # digits + "of"
        '--psm 7 -c tessedit_char_whitelist=0123456789Of ',   # with a capital O
        '--psm 6 -c tessedit_char_whitelist=0123456789of ',
        '--psm 7',                                             # no whitelist - fallback
        '--psm 13',                                            # raw line
    ]

    all_raws = []

    for img_variant in variants:
        for cfg in ocr_configs:
            raw = pytesseract.image_to_string(img_variant, lang='eng', config=cfg).strip()
            if raw:
                all_raws.append(raw)

    print(f"   [COUNTER] OCR variants: {all_raws}")

    # Pattern 1: "17 of 17", "1 of 17", etc. (also with 'o' instead of 'of')
    pattern_of = re.compile(r'(\d{1,3})\s*[oO0][fF]?\s*(\d{1,3})')
    # Pattern 2: just two numbers next to each other - "1 17", "17 17"
    pattern_two = re.compile(r'(\d{1,3})\D+(\d{1,3})')

    for raw in all_raws:
        m = pattern_of.search(raw)
        if m:
            cur, tot = int(m.group(1)), int(m.group(2))
            if 1 <= cur <= 9999 and 1 <= tot <= 9999 and cur <= tot:
                print(f"   [COUNTER] Recognized: {cur} of {tot} (raw: '{raw}')")
                return cur, tot

    for raw in all_raws:
        m = pattern_two.search(raw)
        if m:
            cur, tot = int(m.group(1)), int(m.group(2))
            if 1 <= cur <= 9999 and 1 <= tot <= 9999 and cur <= tot:
                print(f"   [COUNTER] Recognized (fallback): {cur} of {tot} (raw: '{raw}')")
                return cur, tot

    print(f"   [COUNTER] Could not recognize the counter. All variants: {all_raws}")
    return None, None
