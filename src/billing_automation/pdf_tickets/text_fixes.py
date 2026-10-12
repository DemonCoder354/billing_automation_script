"""Corrections of OCR text in the ticket header: Latin-only text, form labels, numbers, dates, times, ICD-10."""
from __future__ import annotations

import re

from ..paths import user_or_bundled

TEMPLATE_FILE = user_or_bundled("ticket_words.txt")


# Each cell separately and without the table lines: this way OCR does not mix up neighbouring fields
# and does not lose values near the borders (SEQ NO, (W), $0.00). Text is Latin only.


_ASCII_MAP = str.maketrans({"ł": "l", "Ł": "L", "ø": "o", "Ø": "O", "đ": "d", "ß": "ss", "æ": "ae",
                            "‘": "'", "’": "'", "“": '"', "”": '"', "•": "-", "·": "-", "—": "-",
                            "–": "-", "¯": "", "«": "", "»": ""})
_DIGITS = str.maketrans({"O": "0", "o": "0", "D": "0", "Q": "0", "l": "1", "I": "1", "i": "1", "|": "1"})
_ICD_FIRST = {"1": "I", "0": "O", "5": "S", "8": "B", "2": "Z", "6": "G"}
_vocab = None


def load_vocab():
    """Form cell labels {UPPER CASE: as on the form} from ticket_words.txt."""
    global _vocab
    if _vocab is None:
        _vocab = {}
        try:
            with open(TEMPLATE_FILE, "r", encoding="utf-8") as f:
                lines = [ln for ln in f if not ln.lstrip().startswith("#")]
        except OSError:
            lines = []
        for token in " ".join(lines).split():
            core = token.strip(".,:;()#")
            if sum(c.isalpha() for c in core) >= 2:
                _vocab.setdefault(core.upper(), core)
    return _vocab


def to_ascii(text):
    """Latin only: diacritics -> plain letters, other non-ASCII characters are removed."""
    import unicodedata
    text = unicodedata.normalize("NFKD", text.translate(_ASCII_MAP))
    return "".join(c for c in text if ord(c) < 128)


def _snap_label(text):
    """Cell label word -> form word ('PATENT' -> 'PATIENT', 'Tlme:' -> 'Time:')."""
    import difflib
    vocab = load_vocab()
    m = re.match(r"^([^A-Za-z0-9]*)(.*?)([^A-Za-z0-9]*)$", text)
    pre, core, post = m.groups()
    if len(core) < 2 or core.upper() in vocab:
        return text   # already correct (case as printed: 'DATE' in a label, 'Date:' in the appointment cell)
    best = difflib.get_close_matches(core.upper(), list(vocab), n=1, cutoff=0.7)
    return pre + vocab[best[0]] + post if best else text


def _fix_number(token):
    """Number with letters that look like digits -> number ('$o.oo' -> '$0.00', '1O/12/26' -> '10/12/26')."""
    if not (any(c.isdigit() for c in token) or token.startswith("$")):
        return token
    m = re.fullmatch(r"(.*?)(AM|PM)?", token)   # time '9:OOAM' -> '9:00AM'
    fixed = m.group(1).translate(_DIGITS)
    fixed = re.sub(r"^(\d{1,2})[-.:;]{1,2}(\d\d)$", r"\1:\2", fixed) if m.group(2) or ":" in fixed else fixed
    return fixed + (m.group(2) or "") if re.fullmatch(r"[\d$.,:/()\-#+]+", fixed) else token


_TIME_RE = re.compile(r"\d{1,2}:\d\d ?[AP]")


def _norm_time(text, suffix_m):
    """'1 1 .-OO A' -> '11:00 A', 'II:OOAM' -> '11:00AM'; does not look like a time -> None."""
    s = text.replace(" ", "").translate(_DIGITS).upper()
    s = re.sub(r"[-.;,:]+", ":", s)
    m = re.fullmatch(r"(\d{1,2}):?(\d\d)([AP])M?", s)
    if not m:
        return None
    return f"{int(m.group(1))}:{m.group(2)}" + (f"{m.group(3)}M" if suffix_m else f" {m.group(3)}")


def _fix_time_value(label, text):
    """Time in the APPOINTMENT ('Time: 11:00 A') and EVENT ('OV 11:00AM') cells."""
    if label == "APPOINTMENT" and "Time:" in text:
        head, tail = text.split("Time:", 1)
        t = _norm_time(tail, False)
        return f"{head}Time: {t}" if t else text
    if label == "EVENT":
        m = re.match(r"^([A-Za-z]{1,4})\s+(.+)$", text)
        if m and not any(c.isdigit() for c in m.group(1)):
            t = _norm_time(m.group(2), True)
            return f"{m.group(1)} {t}" if t else text
        t = _norm_time(text, True)
        return t or text
    return text


def _fix_value(label, text):
    """Value fixes depending on the meaning of the cell."""
    tokens = text.split()
    label = label.upper()
    if label in ("APPOINTMENT", "EVENT"):
        fixed = _fix_time_value(label, text)
        if fixed != text:
            return fixed
    if "DX" in label.split():   # ICD-10 code: letter + digits ('110' -> 'I10', 'El I.59' -> 'E11.59')
        code = re.sub(r"^[Il1|]<", "K", "".join(tokens))   # OCR sees 'K' as 'I<'
        code = re.sub(r"^[Il1|]-[Il1|]", "H", code)          # and 'H' as 'I-1'
        if len(code) >= 3:
            code = _ICD_FIRST.get(code[0], code[0].upper()) + code[1:].translate(_DIGITS)
        return code.upper()   # 'S32.10xs' -> 'S32.10XS'
    if label in ("DOB", "CREATE DATE", "DATE OF LAST PAYMENT"):
        return _fix_number("".join(tokens))   # '1 1/12/2025' -> '11/12/2025'
    if text.lstrip().startswith("$") or label in ("CHART BALANCE", "PATIENT INS BALANCE", "PATIENT SELF BALANCE",
                                                  "AMOUNT OF LAST PAYMENT"):
        return _fix_number("".join(tokens))   # amount without spaces: '$1 ,030.00' -> '$1,030.00'
    if label in ("LAST NAME", "FIRST NAME", "MIDDLE NAME", "PATIENT ADDRESS", "INSURANCE INFORMATION",
                 "GROUP NAME", "RENDERING PHYSICIAN NAME", "REFERRING PHYSICIAN NAME",
                 "REFERRING LOCATION", "DETAILS", "POLICY NUMBER", "GROUP NUMBER", "OLD CHART NUMBER"):
        if label in ("LAST NAME", "FIRST NAME", "MIDDLE NAME"):
            # patient names are printed in capitals; at the edges there are letter fragments from the neighbouring cell
            text = re.sub(r"[^A-Z'\- ]", "", text.upper())
            text = " ".join(re.sub(r"^[^A-Z]+|[^A-Z]+$", "", text).split())
        return text   # names, addresses, policy numbers - as read
    out = []
    for t in tokens:
        s = _snap_label(t) if re.fullmatch(r"\(?[A-Za-z]+[:)]?", t) and label in ("PHONE", "APPOINTMENT") else t
        out.append(_fix_number(s))
    return " ".join(out)
