"""Rich Text движок для термопринтера"""

from dataclasses import dataclass, field
from PIL import Image, ImageDraw, ImageFont

from funnyprint import PRINTER_WIDTH
from funnyprint.imaging import load_font


@dataclass
class TextStyle:
    font_path: str | None = None
    font_size: int = 24
    bold: bool = False
    italic: bool = False
    underline: bool = False
    strikethrough: bool = False
    align: str = "left"
    list_marker: str = ""
    superscript: bool = False
    subscript: bool = False


@dataclass
class TextSpan:
    text: str
    style: TextStyle = field(default_factory=TextStyle)


@dataclass
class RenderSpan:
    """Спан готовый к рендеру"""
    text: str
    font: ImageFont.FreeTypeFont
    style: TextStyle
    width: int = 0
    ascent: int = 0
    descent: int = 0
    font_size: int = 24


@dataclass
class TextLine:
    spans: list  # list[RenderSpan]
    width: int = 0
    ascent: int = 0   # максимальный ascent в строке
    descent: int = 0  # максимальный descent
    height: int = 0   # ascent + descent
    align: str = "left"
    marker: str = ""
    marker_number: int = 0


def _get_font(style):
    size = style.font_size
    if style.superscript or style.subscript:
        size = max(8, size * 2 // 3)
    return load_font(style.font_path, size)


def _measure(text, font, bold=False):
    dummy = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    stroke = 1 if bold else 0
    bbox = dummy.textbbox((0, 0), text, font=font, stroke_width=stroke)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def _font_metrics(font, font_size):
    """Возвращает (ascent, descent) для выравнивания по baseline"""
    try:
        ascent, descent = font.getmetrics()
    except Exception:
        ascent = int(font_size * 0.8)
        descent = int(font_size * 0.2)
    return ascent, descent


# ════════════════════════════════════════
#  Маркеры — рисуем программно
# ════════════════════════════════════════

MARKER_NAMES = [
    "", "checkbox", "checked", "bullet", "dash",
    "arrow", "star", "circle", "number",
]


def _draw_marker(draw, marker, x, y, size, number=0):
    """Рисует маркер программно, возвращает ширину"""
    s = size
    gap = s + 6
    cx = x + s // 2
    cy = y + s // 2

    if marker == "checkbox":
        draw.rectangle([x + 2, y + 2, x + s - 2, y + s - 2],
                       outline=(0, 0, 0), width=2)
        return gap

    elif marker == "checked":
        draw.rectangle([x + 2, y + 2, x + s - 2, y + s - 2],
                       outline=(0, 0, 0), width=2)
        # Галочка
        draw.line([(x + 5, cy), (cx - 1, y + s - 5),
                   (x + s - 4, y + 4)],
                  fill=(0, 0, 0), width=2)
        return gap

    elif marker == "bullet":
        r = s // 5
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(0, 0, 0))
        return gap

    elif marker == "circle":
        r = s // 4
        draw.ellipse([cx - r, cy - r, cx + r, cy + r],
                     outline=(0, 0, 0), width=2)
        return gap

    elif marker == "dash":
        draw.line([(x + 3, cy), (x + s - 3, cy)],
                  fill=(0, 0, 0), width=2)
        return gap

    elif marker == "arrow":
        pts = [(x + 3, y + 4), (x + s - 3, cy), (x + 3, y + s - 4)]
        draw.polygon(pts, fill=(0, 0, 0))
        return gap

    elif marker == "star":
        import math
        points = []
        for i in range(5):
            a = math.radians(-90 + i * 72)
            points.append((cx + int(s * 0.4 * math.cos(a)),
                           cy + int(s * 0.4 * math.sin(a))))
            a2 = math.radians(-90 + i * 72 + 36)
            points.append((cx + int(s * 0.18 * math.cos(a2)),
                           cy + int(s * 0.18 * math.sin(a2))))
        draw.polygon(points, fill=(0, 0, 0))
        return gap

    elif marker == "number":
        font = load_font(None, s)
        txt = f"{number}."
        tw, th = _measure(txt, font)
        draw.text((x, y), txt, font=font, fill=(0, 0, 0))
        return tw + 4

    return 0


# ════════════════════════════════════════
#  Перенос строк
# ════════════════════════════════════════

def _make_render_span(text, style):
    font = _get_font(style)
    w, h = _measure(text, font, style.bold)
    actual_size = style.font_size
    if style.superscript or style.subscript:
        actual_size = max(8, style.font_size * 2 // 3)
    ascent, descent = _font_metrics(font, actual_size)
    return RenderSpan(
        text=text, font=font, style=style,
        width=w, ascent=ascent, descent=descent,
        font_size=actual_size)


def _wrap_spans(spans, max_width, marker="", start_number=1):
    lines = []
    align = spans[0].style.align if spans else "left"

    marker_width = 0
    if marker:
        fs = spans[0].style.font_size if spans else 24
        if marker == "number":
            num_font = load_font(None, fs)
            mw, _ = _measure(f"{start_number}.", num_font)
            marker_width = mw + 4
        else:
            marker_width = fs + 6

    available = max_width - marker_width
    first_line = True
    current = []
    current_width = 0

    def push_line():
        nonlocal current, current_width, first_line, available
        if not current:
            return
        max_asc = max(r.ascent for r in current)
        max_desc = max(r.descent for r in current)
        lines.append(TextLine(
            spans=list(current),
            width=current_width,
            ascent=max_asc, descent=max_desc,
            height=max_asc + max_desc,
            align=align,
            marker=marker if first_line else "",
            marker_number=start_number))
        first_line = False
        available = max_width
        current = []
        current_width = 0

    for span in spans:
        words = span.text.split(' ')
        for wi, word in enumerate(words):
            if not word:
                continue

            # Нужен ли пробел перед словом?
            need_space = bool(current) and (wi > 0 or bool(current))
            if need_space:
                prev_ss = (current[-1].style.superscript or
                           current[-1].style.subscript)
                this_ss = span.style.superscript or span.style.subscript
                if prev_ss or this_ss:
                    need_space = False

            text_to_add = (' ' + word) if need_space else word
            if not text_to_add:
                continue

            rs = _make_render_span(text_to_add, span.style)

            if current_width + rs.width <= available or not current:
                current.append(rs)
                current_width += rs.width
            else:
                push_line()
                # На новой строке пробел в начале не нужен
                rs = _make_render_span(word, span.style)
                current.append(rs)
                current_width = rs.width

    push_line()

    if not lines:
        fs = spans[0].style.font_size if spans else 24
        lines.append(TextLine(
            spans=[], width=0,
            ascent=int(fs * 0.8), descent=int(fs * 0.2),
            height=fs + 6, align=align,
            marker=marker, marker_number=start_number))

    return lines


# ════════════════════════════════════════
#  Парсинг разметки
# ════════════════════════════════════════

def parse_rich_text(text, base_style=None):
    if base_style is None:
        base_style = TextStyle()

    paragraphs = []
    raw_lines = text.replace("\\n", "\n").split("\n")
    number = 0

    for raw_line in raw_lines:
        line = raw_line.strip()
        marker = ""

        if line.startswith("[] "):
            marker = "checkbox"; line = line[3:]
        elif line.startswith("[x] ") or line.startswith("[X] "):
            marker = "checked"; line = line[4:]
        elif line.startswith("- "):
            marker = "dash"; line = line[2:]
        elif line.startswith("• "):
            marker = "bullet"; line = line[2:]
        elif line.startswith("○ "):
            marker = "circle"; line = line[2:]
        elif line.startswith("> "):
            marker = "arrow"; line = line[2:]
        elif line.startswith("★ "):
            marker = "star"; line = line[2:]
        elif len(line) > 2 and line[0].isdigit():
            dot_pos = line.find(". ")
            if 0 < dot_pos < 4:
                try:
                    number = int(line[:dot_pos])
                    marker = "number"
                    line = line[dot_pos + 2:]
                except ValueError:
                    pass

        spans = _parse_inline(line, base_style)
        paragraphs.append((spans, marker, number))

    return paragraphs


def _parse_inline(text, base_style):
    """Парсит инлайн-разметку на тегах.
    
    Теги:
        <b>жирный</b>
        <i>курсив</i>
        <u>подчёркнутый</u>
        <s>зачёркнутый</s>
        <sup>верхний индекс</sup>
        <sub>нижний индекс</sub>
        <size:32>размер</size>
    """
    spans = []
    current = ""
    bold = base_style.bold
    italic = base_style.italic
    underline = base_style.underline
    strike = base_style.strikethrough
    font_size = base_style.font_size
    sup = False
    sub = False
    size_stack = []

    def flush():
        nonlocal current
        if current:
            style = TextStyle(
                font_path=base_style.font_path,
                font_size=font_size,
                bold=bold, italic=italic,
                underline=underline, strikethrough=strike,
                align=base_style.align,
                superscript=sup, subscript=sub)
            spans.append(TextSpan(text=current, style=style))
            current = ""

    i = 0
    while i < len(text):
        if text[i] == '<':
            # Ищем закрывающую >
            end = text.find('>', i + 1)
            if end < 0:
                current += text[i]
                i += 1
                continue

            tag = text[i + 1:end].strip().lower()

            if tag == "b":
                flush(); bold = True
            elif tag == "/b":
                flush(); bold = False
            elif tag == "i":
                flush(); italic = True
            elif tag == "/i":
                flush(); italic = False
            elif tag == "u":
                flush(); underline = True
            elif tag == "/u":
                flush(); underline = False
            elif tag == "s":
                flush(); strike = True
            elif tag == "/s":
                flush(); strike = False
            elif tag == "sup":
                flush(); sup = True
            elif tag == "/sup":
                flush(); sup = False
            elif tag == "sub":
                flush(); sub = True
            elif tag == "/sub":
                flush(); sub = False
            elif tag.startswith("size:"):
                flush()
                size_stack.append(font_size)
                try:
                    font_size = int(tag[5:])
                except ValueError:
                    pass
            elif tag == "/size":
                flush()
                font_size = size_stack.pop() if size_stack else base_style.font_size
            elif tag in ("left", "center", "right"):
                flush()
                base_style = TextStyle(
                    font_path=base_style.font_path,
                    font_size=base_style.font_size,
                    bold=base_style.bold, italic=base_style.italic,
                    underline=base_style.underline,
                    strikethrough=base_style.strikethrough,
                    align=tag)
            elif tag in ("/left", "/center", "/right"):
                flush()
                base_style = TextStyle(
                    font_path=base_style.font_path,
                    font_size=base_style.font_size,
                    bold=base_style.bold, italic=base_style.italic,
                    underline=base_style.underline,
                    strikethrough=base_style.strikethrough,
                    align="left")
            else:
                # Неизвестный тег — оставляем как текст
                current += text[i:end + 1]

            i = end + 1
        else:
            current += text[i]
            i += 1

    flush()
    if not spans:
        spans.append(TextSpan(text="", style=base_style))
    return spans


# ════════════════════════════════════════
#  Рендеринг
# ════════════════════════════════════════

def render_rich_text(text, base_style=None, max_width=None):
    if base_style is None:
        base_style = TextStyle()
    if max_width is None:
        max_width = PRINTER_WIDTH

    pad = 8
    content_width = max_width - pad * 2

    paragraphs = parse_rich_text(text, base_style)

    all_lines = []
    for spans, marker, number in paragraphs:
        if not spans or (len(spans) == 1 and not spans[0].text):
            h = base_style.font_size + 6
            all_lines.append(TextLine(
                spans=[], width=0, ascent=h * 3 // 4,
                descent=h // 4, height=h, align=base_style.align))
        else:
            all_lines.extend(_wrap_spans(spans, content_width, marker, number))

    total_h = sum(l.height for l in all_lines) + pad * 2
    if total_h < 32:
        total_h = 32
    if total_h % 2:
        total_h += 1

    img = Image.new("RGB", (max_width, total_h), (255, 255, 255))
    draw = ImageDraw.Draw(img)

    y = pad
    for line in all_lines:
        if not line.spans:
            y += line.height
            continue

        baseline_y = y + line.ascent  # baseline позиция

        # Маркер
        marker_offset = 0
        if line.marker:
            fs = line.spans[0].font_size if line.spans else 24
            marker_offset = _draw_marker(
                draw, line.marker, pad, y + (line.ascent - fs) // 2,
                fs, line.marker_number)

        # Выравнивание
        if line.align == "center":
            x = pad + (content_width - line.width) // 2
        elif line.align == "right":
            x = max_width - pad - line.width
        else:
            x = pad + marker_offset

        for rs in line.spans:
            stroke = 1 if rs.style.bold else 0
            text_str = rs.text

            if rs.style.superscript:
                span_y = y
            elif rs.style.subscript:
                span_y = y + line.height - rs.ascent - rs.descent
            else:
                span_y = baseline_y - rs.ascent

            span_x_start = x  # запоминаем начало

            if rs.style.italic and text_str.strip():
                tw = rs.width
                shear = 0.18
                extra = int(rs.font_size * 0.3) + 8
                stroke_extra = 4 if rs.style.bold else 0
                total_w = tw + extra * 2 + stroke_extra
                total_h = rs.ascent + rs.descent + 4
                li = Image.new("RGB", (total_w, total_h),
                               (255, 255, 255))
                ld = ImageDraw.Draw(li)
                ld.text((extra, 0), text_str, font=rs.font,
                        fill=(0, 0, 0), stroke_width=stroke,
                        stroke_fill=(0, 0, 0))
                li = li.transform(
                    li.size, Image.AFFINE,
                    (1, -shear, shear * total_h * 0.5, 0, 1, 0),
                    resample=Image.BILINEAR,
                    fillcolor=(255, 255, 255))
                mask = li.convert("L").point(lambda p: 0 if p > 245 else 255)
                bb = mask.getbbox()
                if bb:
                    li = li.crop((bb[0], 0, bb[2], total_h))
                px = max(0, int(x))
                if px + li.width <= max_width:
                    img.paste(li, (px, int(span_y)))
                x += li.width
            else:
                draw.text((int(x), int(span_y)), text_str,
                          font=rs.font, fill=(0, 0, 0),
                          stroke_width=stroke, stroke_fill=(0, 0, 0))
                x += rs.width

            span_x_end = x

            # Подчёркивание
            if rs.style.underline and text_str.strip():
                uy = int(baseline_y + 3)
                draw.line([(int(span_x_start), uy),
                           (int(span_x_end), uy)],
                          fill=(0, 0, 0), width=2)

            # Зачёркивание
            if rs.style.strikethrough and text_str.strip():
                sy = int(span_y + (rs.ascent + rs.descent) // 2)
                draw.line([(int(span_x_start), sy),
                           (int(span_x_end), sy)],
                          fill=(0, 0, 0), width=2)

        y += line.height

    return img


def get_marker_names():
    return MARKER_NAMES