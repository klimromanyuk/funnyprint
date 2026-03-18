"""Document session with item-level cache for preview and chunked printing."""

from dataclasses import dataclass
from typing import Any

from funnyprint.document_engine import DocumentLayout, LayoutSettings
from funnyprint.imaging import (
    prepare_image_item,
    prepare_pdf_page_item,
    _lines_to_preview,
)
from funnyprint.imaging import _detect_image_container


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
    def from_filters(cls, filters: dict[str, Any]):
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
    """Сессия текущего документа с кэшем item'ов и layout."""

    def __init__(self):
        self.source_type: str | None = None
        self.source_data: dict[str, Any] = {}

        self.render_settings = RenderSettings()
        self.feed_px = 0
        self.copies = 1

        self._item_specs: list[tuple] = []
        self._item_cache: dict[tuple, tuple[list[bytes], Any]] = {}
        self._layout: DocumentLayout | None = None

        self._warnings: list[str] = []

    # ─────────────────────────────────────
    # Source setup
    # ─────────────────────────────────────

    def set_batch_images(self, paths, filters=None, feed_px=0, copies=1):
        self._warnings = []
        self.source_type = "batch_images"
        self.source_data = {"paths": tuple(paths)}
        self.render_settings = RenderSettings.from_filters(filters or {})
        self.feed_px = max(0, int(feed_px))
        self.copies = max(1, int(copies))
        self._item_specs = [("image", path) for path in paths]
        self._layout = None

    def set_pdf(self, path, pages, filters=None, feed_px=0, copies=1):
        self._warnings = []
        self.source_type = "pdf"
        self.source_data = {"path": path, "pages": tuple(pages)}
        self.render_settings = RenderSettings.from_filters(filters or {})
        self.feed_px = max(0, int(feed_px))
        self.copies = max(1, int(copies))
        self._item_specs = [("pdf_page", path, int(pg)) for pg in pages]
        self._layout = None

    def set_layout(self, feed_px=0, copies=1):
        feed_px = max(0, int(feed_px))
        copies = max(1, int(copies))
        if self.feed_px != feed_px or self.copies != copies:
            self.feed_px = feed_px
            self.copies = copies
            self._layout = None

    def set_filters(self, filters):
        new_settings = RenderSettings.from_filters(filters or {})
        if new_settings != self.render_settings:
            self.render_settings = new_settings
            self._layout = None

    # ─────────────────────────────────────
    # Item render
    # ─────────────────────────────────────

    def _item_cache_key(self, spec):
        return (spec, self.render_settings, self.feed_px)

    def _render_item(self, spec):
        key = self._item_cache_key(spec)
        if key in self._item_cache:
            return self._item_cache[key]

        kind = spec[0]
        filters = self.render_settings.__dict__.copy()

        if kind == "image":
            _, path = spec
            result = prepare_image_item(
                path,
                feed_px=self.feed_px,
                **filters,
            )
        elif kind == "pdf_page":
            _, path, page_num = spec
            result = prepare_pdf_page_item(
                path,
                page_num=page_num,
                feed_px=self.feed_px,
                **filters,
            )
        else:
            raise ValueError(f"Unsupported item spec: {spec}")

        self._item_cache[key] = result
        return result

    def get_rendered_items(self):
        rendered = []
        errors = []

        for spec in self._item_specs:
            try:
                rendered.append(self._render_item(spec))
            except Exception as e:
                if self.source_type == "batch_images" and spec and spec[0] == "image":
                    errors.append((spec, e))
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
                    continue
                raise

        if not rendered and self._item_specs:
            if errors:
                first_spec, first_error = errors[0]
                raise RuntimeError(
                    f"Не удалось обработать ни одного изображения: {first_spec} -> {first_error}"
                )
            raise RuntimeError("Документ пуст")

        return rendered

    def get_item_lines(self):
        return [lines for lines, _bw in self.get_rendered_items()]

    # ─────────────────────────────────────
    # Layout
    # ─────────────────────────────────────

    def ensure_layout(self):
        if self._layout is not None:
            return self._layout

        items = self.get_item_lines()
        self._layout = DocumentLayout(
            items=[list(item) for item in items],
            settings=LayoutSettings(
                copies=self.copies,
                gap_lines=0,
            ),
        )
        self._layout.rebuild()
        return self._layout

    # ─────────────────────────────────────
    # Chunk API
    # ─────────────────────────────────────

    @property
    def chunk_count(self):
        return self.ensure_layout().chunk_count

    def get_chunk_lines(self, chunk_index):
        layout = self.ensure_layout()
        return layout.assemble_chunk_lines(chunk_index)

    def get_chunk_preview(self, chunk_index):
        lines = self.get_chunk_lines(chunk_index)
        return _lines_to_preview(lines)

    # ─────────────────────────────────────
    # Misc
    # ─────────────────────────────────────

    def clear(self):
        self._warnings = []
        self.source_type = None
        self.source_data = {}
        self._item_specs = []
        self._layout = None

    @property
    def warnings(self):
        return list(self._warnings)