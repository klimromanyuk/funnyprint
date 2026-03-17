"""Document/layout engine for chunked preview and printing.

Первый этап рефактора:
- отделяем layout чанков от GUI
- не пересобираем весь документ как список чанков заранее
- представляем документ как последовательность сегментов
"""

from dataclasses import dataclass, field
from typing import List, Sequence

from funnyprint.chunked import MAX_CHUNK_LINES


BLANK_LINE = bytes(96)


@dataclass(frozen=True)
class LayoutSettings:
    """Настройки layout, не влияющие на рендер item'ов."""
    copies: int = 1
    gap_lines: int = 0


@dataclass(frozen=True)
class Segment:
    """Линейный сегмент документа."""
    kind: str          # "item" | "gap"
    item_index: int    # индекс item, для gap = -1
    start: int         # start line inside item/gap
    length: int        # number of funny lines


@dataclass(frozen=True)
class ChunkDescriptor:
    """Описание чанка как набора сегментов."""
    index: int
    segments: tuple[Segment, ...]
    total_lines: int


@dataclass
class DocumentLayout:
    """Layout-документ поверх уже готовых item lines.

    items: список item'ов, где каждый item = list[bytes]
    """
    items: List[List[bytes]]
    settings: LayoutSettings
    _sequence: list[Segment] = field(default_factory=list)
    _chunks: list[ChunkDescriptor] = field(default_factory=list)

    def rebuild(self):
        self._sequence = build_segment_sequence(
            self.items,
            copies=self.settings.copies,
            gap_lines=self.settings.gap_lines,
        )
        self._chunks = build_chunk_descriptors(self._sequence)

    @property
    def chunk_count(self) -> int:
        return len(self._chunks) if self._chunks else 1

    @property
    def chunks(self) -> Sequence[ChunkDescriptor]:
        return self._chunks

    def get_chunk(self, chunk_index: int) -> ChunkDescriptor:
        if not self._chunks:
            self.rebuild()
        if not self._chunks:
            return ChunkDescriptor(index=0, segments=tuple(), total_lines=0)
        idx = min(max(0, chunk_index), len(self._chunks) - 1)
        return self._chunks[idx]

    def assemble_chunk_lines(self, chunk_index: int) -> list[bytes]:
        chunk = self.get_chunk(chunk_index)
        return assemble_chunk_lines(self.items, chunk)


def build_segment_sequence(items: Sequence[Sequence[bytes]],
                           copies: int = 1,
                           gap_lines: int = 0) -> list[Segment]:
    """Строит линейную последовательность сегментов документа.

    Важно:
    - copies реализуются на уровне layout
    - gap вставляется между item'ами, в том числе между концом копии
      и началом следующей копии
    """
    if not items:
        return []

    copies = max(1, int(copies))
    gap_lines = max(0, int(gap_lines))

    sequence: list[Segment] = []
    base_count = len(items)

    for copy_idx in range(copies):
        for item_idx, item in enumerate(items):
            item_len = len(item)
            if item_len > 0:
                sequence.append(
                    Segment(
                        kind="item",
                        item_index=item_idx,
                        start=0,
                        length=item_len,
                    )
                )

            is_last_global = (
                copy_idx == copies - 1 and item_idx == base_count - 1
            )
            if not is_last_global and gap_lines > 0:
                sequence.append(
                    Segment(
                        kind="gap",
                        item_index=-1,
                        start=0,
                        length=gap_lines,
                    )
                )

    return sequence


def build_chunk_descriptors(sequence: Sequence[Segment],
                            max_chunk_lines: int = MAX_CHUNK_LINES
                            ) -> list[ChunkDescriptor]:
    """Режет линейную последовательность сегментов на чанки.

    В отличие от старого chunk_by_items:
    - не материализует lines
    - умеет разрезать слишком большой item на несколько чанков
    """
    if not sequence:
        return [ChunkDescriptor(index=0, segments=tuple(), total_lines=0)]

    chunks: list[ChunkDescriptor] = []
    current_segments: list[Segment] = []
    current_total = 0
    chunk_index = 0

    def flush():
        nonlocal current_segments, current_total, chunk_index
        chunks.append(
            ChunkDescriptor(
                index=chunk_index,
                segments=tuple(current_segments),
                total_lines=current_total,
            )
        )
        chunk_index += 1
        current_segments = []
        current_total = 0

    for seg in sequence:
        remaining = seg.length
        offset = seg.start

        while remaining > 0:
            if current_total >= max_chunk_lines:
                flush()

            free = max_chunk_lines - current_total
            take = min(remaining, free)

            current_segments.append(
                Segment(
                    kind=seg.kind,
                    item_index=seg.item_index,
                    start=offset,
                    length=take,
                )
            )
            current_total += take
            remaining -= take
            offset += take

            if current_total >= max_chunk_lines:
                flush()

    if current_segments or not chunks:
        flush()

    return chunks


def assemble_chunk_lines(items: Sequence[Sequence[bytes]],
                         chunk: ChunkDescriptor) -> list[bytes]:
    """Собирает funny_lines для конкретного чанка по descriptor."""
    result: list[bytes] = []

    for seg in chunk.segments:
        if seg.length <= 0:
            continue

        if seg.kind == "gap":
            result.extend(BLANK_LINE for _ in range(seg.length))
            continue

        if seg.kind == "item":
            item = items[seg.item_index]
            result.extend(item[seg.start:seg.start + seg.length])
            continue

        raise ValueError(f"Unknown segment kind: {seg.kind}")

    return result