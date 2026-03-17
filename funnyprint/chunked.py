"""Чанкованная обработка для больших данных"""

MAX_CHUNK_LINES = 3000


def estimate_chunks(total_lines):
    if total_lines <= MAX_CHUNK_LINES:
        return 1
    return (total_lines + MAX_CHUNK_LINES - 1) // MAX_CHUNK_LINES


def chunk_lines(all_lines, chunk_index):
    start = chunk_index * MAX_CHUNK_LINES
    end = min(start + MAX_CHUNK_LINES, len(all_lines))
    return all_lines[start:end]


def needs_chunking(lines_or_count):
    n = lines_or_count if isinstance(lines_or_count, int) else len(lines_or_count)
    return n > MAX_CHUNK_LINES


def chunk_by_items(items, feed_lines=0):
    """Разбивает items на чанки, не разрезая элементы.
    Если один элемент > MAX_CHUNK_LINES — он один в чанке.

    items: list of lists (каждый item = list of lines)
    feed_lines: промежуток между элементами (funny_lines)

    Returns: list of flat lists (каждый чанк)
    """
    if not items:
        return [[]]

    blank = bytes(96)
    chunks = []
    current = []
    current_count = 0

    for item in items:
        item_len = len(item)

        if current_count > 0 and current_count + item_len > MAX_CHUNK_LINES:
            chunks.append(current)
            current = []
            current_count = 0

        if current and feed_lines > 0:
            current.extend(blank for _ in range(feed_lines))
            current_count += feed_lines

        current.extend(item)
        current_count += item_len

    if current:
        chunks.append(current)

    return chunks if chunks else [[]]