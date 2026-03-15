"""Чанкованная обработка для больших данных"""

# ~6000px высоты = ~3000 funny_lines
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