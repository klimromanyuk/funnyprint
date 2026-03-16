"""Сервисный слой — логика без GUI.

Используется из gui.py, а потом из бота/CLI.
"""

import asyncio
import threading
from typing import Callable

from PIL import Image

from funnyprint import PRINTER_WIDTH, DEFAULT_DENSITY, DEFAULT_FEED_AFTER
from funnyprint.imaging import (
    prepare_image, prepare_text, prepare_qr, prepare_barcode,
    prepare_pdf_page, prepare_batch_pdf, prepare_batch_images,
    prepare_batch_images_chunked, pil_to_funny_lines,
    apply_filters, apply_artistic_filter, dither_image,
    add_feed_preview, _lines_to_preview, _trim_whitespace,
    _fit_to_printer, _rotate_and_fit,
)
from funnyprint.printer import find_and_connect, Printer
from funnyprint.chunked import needs_chunking, MAX_CHUNK_LINES, estimate_chunks


class PrintService:
    """Логика приложения без привязки к GUI."""

    def __init__(self,
                 on_log: Callable[[str], None] = print,
                 on_progress: Callable[[int], None] | None = None):
        self.on_log = on_log
        self.on_progress = on_progress
        self.printer: Printer | None = None
        self.connected = False

        self._ble_loop = asyncio.new_event_loop()
        threading.Thread(
            target=self._ble_loop.run_forever, daemon=True).start()

    def run_async(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self._ble_loop)

    # ── Подключение ──

    async def connect(self) -> bool:
        try:
            self.printer = await find_and_connect(
                on_log=self.on_log, on_progress=self.on_progress)
            self.connected = self.printer is not None
            return self.connected
        except Exception as e:
            self.on_log(f"Ошибка: {e}")
            self.connected = False
            return False

    async def disconnect(self):
        try:
            if self.printer and self.printer.client:
                if self.printer.client.is_connected:
                    await self.printer.client.disconnect()
            self.on_log("Отключено")
        except Exception as e:
            self.on_log(f"Ошибка: {e}")
        self.printer = None
        self.connected = False

    @property
    def battery(self):
        if self.printer:
            return self.printer.battery
        return "?"

    # ── Печать ──

    async def print_lines(self, lines, density=DEFAULT_DENSITY,
                          feed=DEFAULT_FEED_AFTER):
        if not self.connected or not self.printer:
            raise RuntimeError("Принтер не подключён")
        await self.printer.print_lines(lines, density, feed)

    async def feed(self, pixels=DEFAULT_FEED_AFTER):
        if not self.connected or not self.printer:
            raise RuntimeError("Принтер не подключён")
        await self.printer.feed(pixels)

    def cancel(self):
        if self.printer:
            self.printer.cancel()

    @property
    def is_connected(self):
        return (self.printer is not None
                and self.printer.client is not None
                and self.printer.client.is_connected)

    # ── Подготовка данных ──

    def prepare_image(self, path, **filters):
        return prepare_image(path, **filters)

    def prepare_text(self, text, **kwargs):
        return prepare_text(text, **kwargs)

    def prepare_richtext(self, markup, font_path=None,
                         font_size=24, **filters):
        from funnyprint.richtext import render_rich_text, TextStyle
        style = TextStyle(
            font_path=font_path, font_size=font_size, align="left")
        img = render_rich_text(markup, style)
        img = apply_filters(img,
                            brightness=filters.get("brightness", 0),
                            contrast=filters.get("contrast", 0),
                            sharpness=filters.get("sharpness", 0))
        img = apply_artistic_filter(img, filters.get("artistic", "Нет"))
        border = filters.get("border", "Нет")
        if border != "Нет":
            from funnyprint.borders import apply_border
            img = apply_border(img, border)
            img = _fit_to_printer(img)
        rotation = filters.get("rotation", 0)
        if rotation:
            img = _rotate_and_fit(img, rotation)
        else:
            img = _trim_whitespace(img)
            img = _fit_to_printer(img)
        bw = dither_image(img.convert("L"),
                          filters.get("dither", "Floyd-Steinberg"))
        return pil_to_funny_lines(bw), bw

    def prepare_pdf(self, path, pages, feed_between=50, **filters):
        if len(pages) == 1:
            return prepare_pdf_page(path, page_num=pages[0], **filters)
        return prepare_batch_pdf(
            path, pages, feed_between=feed_between, **filters)

    def prepare_qr(self, data, **kwargs):
        return prepare_qr(data, **kwargs)

    def prepare_barcode(self, data, **kwargs):
        return prepare_barcode(data, **kwargs)

    def prepare_batch_images(self, paths, **kwargs):
        return prepare_batch_images(paths, **kwargs)

    def prepare_batch_images_chunked(self, paths, **kwargs):
        return prepare_batch_images_chunked(paths, **kwargs)

    # ── Утилиты ──

    @staticmethod
    def apply_copies(lines, copies, feed=0):
        if copies <= 1:
            return lines
        repeated = []
        blank = bytes(96)
        gap = feed // 2 if feed > 0 else 0
        for c in range(copies):
            repeated.extend(lines)
            if c < copies - 1 and gap > 0:
                repeated.extend(blank for _ in range(gap))
        return repeated

    @staticmethod
    def chunk_lines(lines, chunk_index=0):
        if not needs_chunking(lines):
            return lines, None, 1, 0
        total = estimate_chunks(len(lines))
        idx = min(chunk_index, total - 1)
        s = idx * MAX_CHUNK_LINES
        chunk = lines[s:min(s + MAX_CHUNK_LINES, len(lines))]
        preview = _lines_to_preview(chunk)
        return chunk, preview, total, idx

    @staticmethod
    def add_feed_preview(img, feed_px):
        return add_feed_preview(img, feed_px)

    @staticmethod
    def lines_to_preview(lines):
        return _lines_to_preview(lines)

    def stop(self):
        try:
            self._ble_loop.call_soon_threadsafe(self._ble_loop.stop)
        except Exception:
            pass