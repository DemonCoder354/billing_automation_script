"""Writing an invisible text layer of the ticket header into the PDF."""
from __future__ import annotations

import os

from .header import HEADER_DPI, HEADER_PART, read_header
from .text_fixes import to_ascii


FONT = None  # font of the invisible layer, created once per process


def _write_words(page, words):
    """Invisible text layer: words [(text, x, y, width, height)] in points."""
    import pymupdf
    writer = pymupdf.TextWriter(page.rect)
    for text, x, y, w, h in words:
        fontsize = max(h * 0.9, 1)
        natural = FONT.text_length(text, fontsize=fontsize)
        if natural > w > 0:  # the word is wider than its box - shrink the font so that the selection matches
            fontsize *= w / natural
        writer.append((x, y + h * 0.85), text, font=FONT, fontsize=fontsize)
    writer.write_text(page, render_mode=3)  # 3 = invisible text


def ocr_pdf(src, dst, ocr):
    """Copy of src with an invisible text layer of the ticket header -> dst. Returns the number of words."""
    import pymupdf
    global FONT
    if FONT is None:
        FONT = pymupdf.Font("helv")
    doc = pymupdf.open(src)
    total = 0
    try:
        for page in doc:
            if len(page.get_text("text").strip()) > 20:
                continue  # the page already has text
            header = read_header(page, ocr)
            if header is not None:
                words = [w for cell in header for w in cell["words"]]
            else:
                # not a ticket: recognize the top of the page as is (Latin only)
                clip = pymupdf.Rect(0, 0, page.rect.width, page.rect.height * HEADER_PART)
                pix = page.get_pixmap(dpi=HEADER_DPI, colorspace=pymupdf.csGRAY, alpha=False, clip=clip)
                k = 72 / HEADER_DPI
                words = [(to_ascii(t), x * k, y * k, w * k, h * k)
                         for t, x, y, w, h in ocr.words(pix.samples, pix.width, pix.height) if to_ascii(t).strip()]
            if words:
                _write_words(page, words)
                total += len(words)
        tmp = dst + ".part"
        doc.save(tmp, garbage=1, deflate=True)
    finally:
        doc.close()
    os.replace(tmp, dst)
    return total
