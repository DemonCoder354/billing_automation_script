"""Built-in Windows text recognition (Windows.Media.Ocr) through winsdk."""
from __future__ import annotations

import asyncio

from .config import OCR_LANGS


class WindowsOcr:
    """Built-in Windows text recognition (Windows.Media.Ocr)."""

    def __init__(self):
        from winsdk.windows.globalization import Language
        from winsdk.windows.media.ocr import OcrEngine
        self.engine = None
        for tag in OCR_LANGS:
            lang = Language(tag)
            if OcrEngine.is_language_supported(lang):
                self.engine = OcrEngine.try_create_from_language(lang)
                self.lang = tag
                break
        if self.engine is None:
            self.engine = OcrEngine.try_create_from_user_profile_languages()
            self.lang = "user profile"
        if self.engine is None:
            raise RuntimeError("No text recognition language is installed in Windows.")
        self.max_side = OcrEngine.get_max_image_dimension() if hasattr(
            OcrEngine, "get_max_image_dimension") else OcrEngine.max_image_dimension
        self.loop = asyncio.new_event_loop()

    def words(self, gray_pixels, width, height):
        """Words of the image (Gray8, one byte per pixel): [(text, x, y, width, height)] in pixels."""
        return self.loop.run_until_complete(self._words(gray_pixels, width, height))

    async def _words(self, gray_pixels, width, height):
        from winsdk.windows.graphics.imaging import BitmapPixelFormat, SoftwareBitmap
        from winsdk.windows.storage.streams import DataWriter
        # the pixels are passed directly, without PNG encoding
        writer = DataWriter()
        writer.write_bytes(gray_pixels)
        bitmap = SoftwareBitmap.create_copy_from_buffer(
            writer.detach_buffer(), BitmapPixelFormat.GRAY8, width, height)
        result = await self.engine.recognize_async(bitmap)
        out = []
        for line in result.lines:
            for w in line.words:
                r = w.bounding_rect
                out.append((w.text, r.x, r.y, r.width, r.height))
        return out
