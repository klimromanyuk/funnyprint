"""Document session with lazy item rendering and chunk preview cache."""

from dataclasses import dataclass
from typing import Any

from PIL import Image

from funnyprint.document_engine import LayoutSettings, VirtualDocumentLayout
from funnyprint.imaging import (
    load_image_base,
    load_pdf_page_base,
    finalize_image,
    append_feed_bw,
    estimate_image_item_lines,
    estimate_pdf_page_item_lines,
    _detect_image_container,
)


@dataclass(frozen=True)
class RenderSettings:
    brightness: int = 0
    contrast: int = 0
    sharpness: int = 0
    dither: str = "Floyd-Steinberg"
    rotation: int = 0
    artistic: str = "Нет"
    border: str = "Нет"

    @classmethod
    def from_filters(cls, filters: dict[str, Any] | None):
        filters = filters or {}
        return cls(
            brightness=int(filters.get("brightness", 0)),
            contrast=int(filters.get("contrast", 0)),
            sharpness=int(filters.get("sharpness", 0)),
            dither=filters.get("dither", "Floyd-Steinberg"),
            rotation=int(filters.get("rotation", 0)),
            artistic=filters.get("artistic", "Нет"),
            border=filters.get("border", "Нет"),
        )


class DocumentSession:
    """Сессия текущего документа с lazy-рендером item'ов и кэшем preview."""

    def __init__(self):
        # Source / document identity
        self.source_type: str | None = None
        self.source_data: dict[str, Any] = {}

        # Current settings
        self.render_settings = RenderSettings()
        self.feed_px = 0
        self.copies = 1

        # Item model
        self._item_specs: list[tuple] = []
        self._layout: VirtualDocumentLayout | None = None

        # Caches
        self._item_cache: dict[tuple, tuple[list[bytes], Image.Image]] = {}
        self._base_image_cache: dict[tuple, Image.Image] = {}
        self._chunk_preview_cache: dict[tuple, Image.Image] = {}
        self._item_length_cache: dict[tuple, int] = {}

        # Diagnostics
        self._warnings: list[str] = []

    # ─────────────────────────────────────
    # Source setup
    # ─────────────────────────────────────

    def set_batch_images(self, paths, filters=None, feed_px=0, copies=1):
        self._reset_for_new_source()
        self.source_type = "batch_images"
        self.source_data = {"paths": tuple(paths)}
        self.render_settings = RenderSettings.from_filters(filters)
        self.feed_px = max(0, int(feed_px))
        self.copies = max(1, int(copies))
        self._item_specs = [("image", path) for path in paths]

    def set_pdf(self, path, pages, filters=None, feed_px=0, copies=1):
        self._reset_for_new_source()
        self.source_type = "pdf"
        self.source_data = {"path": path, "pages": tuple(pages)}
        self.render_settings = RenderSettings.from_filters(filters)
        self.feed_px = max(0, int(feed_px))
        self.copies = max(1, int(copies))
        self._item_specs = [("pdf_page", path, int(pg)) for pg in pages]

    def set_layout(self, feed_px=0, copies=1):
        feed_px = max(0, int(feed_px))
        copies = max(1, int(copies))
        if self.feed_px != feed_px or self.copies != copies:
            self.feed_px = feed_px
            self.copies = copies
            self._layout = None
            self._chunk_preview_cache.clear()
            self._item_length_cache.clear()

    def set_filters(self, filters):
        new_settings = RenderSettings.from_filters(filters)
        if new_settings != self.render_settings:
            self.render_settings = new_settings
            self._layout = None
            self._chunk_preview_cache.clear()
            self._item_length_cache.clear()

    def clear(self):
        self._reset_for_new_source()
        self.source_type = None
        self.source_data = {}
        self._item_specs = []

    def _reset_for_new_source(self):
        self._warnings.clear()
        self._layout = None
        self._item_specs = []
        self._item_cache.clear()
        self._base_image_cache.clear()
        self._chunk_preview_cache.clear()
        self._item_length_cache.clear()

    # ─────────────────────────────────────
    # Cache keys
    # ─────────────────────────────────────

    def _item_cache_key(self, spec):
        return (spec, self.render_settings)

    def _base_cache_key(self, spec):
        kind = spec[0]
        rotation = self.render_settings.rotation

        if kind == "image":
            _, path = spec
            return ("image", path, rotation)

        if kind == "pdf_page":
            _, path, page_num = spec
            return ("pdf_page", path, page_num, rotation)

        return (kind, spec, rotation)

    def _length_cache_key(self, spec):
        kind = spec[0]
        rotation = self.render_settings.rotation
        return ("len", kind, spec, rotation, self.feed_px)

    def _chunk_preview_cache_key(self, chunk_index):
        return (
            "chunk_preview",
            chunk_index,
            self.source_type,
            self.source_data.get("path"),
            self.source_data.get("paths"),
            self.source_data.get("pages"),
            self.render_settings,
            self.feed_px,
            self.copies,
        )

    # ─────────────────────────────────────
    # Feed helpers
    # ─────────────────────────────────────

    def _append_feed_lines(self, lines):
        if self.feed_px <= 0:
            return list(lines)
        blank = bytes(96)
        return list(lines) + [blank for _ in range(self.feed_px // 2)]

    def _append_feed_bw(self, bw):
        if self.feed_px <= 0:
            return bw.copy()
        return append_feed_bw(bw, self.feed_px)

    # ─────────────────────────────────────
    # Length estimation / layout
    # ─────────────────────────────────────

    def _estimate_item_length(self, spec):
        key = self._length_cache_key(spec)
        if key in self._item_length_cache:
            return self._item_length_cache[key]

        kind = spec[0]

        if kind == "image":
            _, path = spec
            value = estimate_image_item_lines(
                path,
                rotation=self.render_settings.rotation,
                feed_px=self.feed_px,
            )
        elif kind == "pdf_page":
            _, path, page_num = spec
            value = estimate_pdf_page_item_lines(
                path,
                page_num=page_num,
                rotation=self.render_settings.rotation,
                feed_px=self.feed_px,
            )
        else:
            raise ValueError(f"Unsupported item spec: {spec}")

        self._item_length_cache[key] = value
        return value

    def get_item_lengths(self):
        return [self._estimate_item_length(spec) for spec in self._item_specs]

    def ensure_layout(self):
        if self._layout is not None:
            return self._layout

        self._layout = VirtualDocumentLayout(
            item_lengths=self.get_item_lengths(),
            settings=LayoutSettings(copies=self.copies, gap_lines=0),
        )
        self._layout.rebuild()
        return self._layout

    @property
    def chunk_count(self):
        return self.ensure_layout().chunk_count

    # ─────────────────────────────────────
    # Base images / rendered items
    # ─────────────────────────────────────

    def _get_base_image(self, spec):
        key = self._base_cache_key(spec)
        if key in self._base_image_cache:
            return self._base_image_cache[key].copy()

        kind = spec[0]

        if kind == "image":
            _, path = spec
            img = load_image_base(path, rotation=self.render_settings.rotation)
        elif kind == "pdf_page":
            _, path, page_num = spec
            img = load_pdf_page_base(
                path,
                page_num=page_num,
                rotation=self.render_settings.rotation,
            )
        else:
            raise ValueError(f"Unsupported item spec: {spec}")

        self._base_image_cache[key] = img.copy()
        return img

    def _render_item(self, spec):
        key = self._item_cache_key(spec)
        if key in self._item_cache:
            lines, bw = self._item_cache[key]
            return list(lines), bw.copy()

        filters = self.render_settings.__dict__.copy()
        base_img = self._get_base_image(spec)

        lines, bw = finalize_image(
            base_img,
            brightness=filters["brightness"],
            contrast=filters["contrast"],
            sharpness=filters["sharpness"],
            dither=filters["dither"],
            rotation=0,
            artistic=filters["artistic"],
            border=filters["border"],
            trim=False,
        )

        result = (list(lines), bw.copy())
        self._item_cache[key] = result
        return list(lines), bw.copy()

    # ─────────────────────────────────────
    # Chunk assembly
    # ─────────────────────────────────────

    def _assemble_chunk_from_descriptor(self, chunk):
        result = []

        for seg in chunk.segments:
            if seg.length <= 0:
                continue

            if seg.kind == "gap":
                blank = bytes(96)
                result.extend(blank for _ in range(seg.length))
                continue

            if seg.kind == "item":
                spec = self._item_specs[seg.item_index]
                content_lines, _bw = self._render_item(spec)
                lines = self._append_feed_lines(content_lines)
                result.extend(lines[seg.start:seg.start + seg.length])
                continue

            raise ValueError(f"Unknown segment kind: {seg.kind}")

        return result

    def get_chunk_lines(self, chunk_index):
        layout = self.ensure_layout()
        chunk = layout.get_chunk(chunk_index)
        return self._assemble_chunk_from_descriptor(chunk)

    # ─────────────────────────────────────
    # Chunk preview cache
    # ─────────────────────────────────────

    def has_chunk_preview(self, chunk_index):
        return self._chunk_preview_cache_key(chunk_index) in self._chunk_preview_cache

    def get_chunk_preview(self, chunk_index):
        return self.get_chunk_preview_fast(chunk_index)

    def get_chunk_preview_fast(self, chunk_index):
        layout = self.ensure_layout()
        chunk = layout.get_chunk(chunk_index)

        cache_key = self._chunk_preview_cache_key(chunk_index)
        cached = self._chunk_preview_cache.get(cache_key)
        if cached is not None:
            return cached.copy()

        total_h = 0
        segment_images = []

        for seg in chunk.segments:
            if seg.length <= 0:
                continue

            if seg.kind == "gap":
                seg_h = seg.length * 2
                img = Image.new("1", (384, seg_h), color=1)
                segment_images.append(img)
                total_h += seg_h
                continue

            if seg.kind == "item":
                spec = self._item_specs[seg.item_index]
                _lines, content_bw = self._render_item(spec)
                bw = self._append_feed_bw(content_bw)
                top = seg.start * 2
                bottom = top + seg.length * 2
                cropped = bw.crop((0, top, bw.width, bottom))
                segment_images.append(cropped)
                total_h += cropped.height
                continue

        total_h = max(2, total_h)
        if total_h % 2:
            total_h += 1

        preview = Image.new("1", (384, total_h), color=1)

        y = 0
        for img in segment_images:
            preview.paste(img, (0, y))
            y += img.height

        self._chunk_preview_cache[cache_key] = preview.copy()
        return preview

    def warm_chunk_preview(self, chunk_index):
        self.get_chunk_preview(chunk_index)

    def count_warmed_chunks(self):
        return len(self._chunk_preview_cache)

    # ─────────────────────────────────────
    # Diagnostics
    # ─────────────────────────────────────

    @property
    def warnings(self):
        return list(self._warnings)

    def collect_warnings_for_current_source(self):
        """Пытается собрать warnings по текущему source без полного падения batch."""
        self._warnings.clear()

        if self.source_type != "batch_images":
            return self.warnings

        for spec in self._item_specs:
            try:
                self._estimate_item_length(spec)
            except Exception as e:
                if spec and spec[0] == "image":
                    path = spec[1] if len(spec) > 1 else "?"
                    detected = _detect_image_container(path)

                    if detected == "heif":
                        msg = (
                            f"Пропущена картинка: {path} "
                            f"(файл не является PNG/JPG, это HEIF/AVIF-подобный контейнер; "
                            f"Pillow не может открыть его без дополнительного декодера)"
                        )
                    elif detected and path.lower().endswith(".png") and detected != "png":
                        msg = (
                            f"Пропущена картинка: {path} "
                            f"(расширение .png не соответствует реальному формату: {detected})"
                        )
                    else:
                        msg = f"Пропущена картинка: {path} ({e})"

                    self._warnings.append(msg)

        return self.warnings