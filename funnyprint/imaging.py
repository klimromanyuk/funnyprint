"""Обработка изображений для термопринтера"""

import os
import sys
from itertools import islice
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont, ImageEnhance

from funnyprint import PRINTER_WIDTH

# ════════════════════════════════════════
#  Шрифты
# ════════════════════════════════════════

def get_system_fonts():
    fonts = {}
    search_dirs = []
    if sys.platform == "win32":
        windir = os.environ.get("WINDIR", "C:\\Windows")
        search_dirs.append(os.path.join(windir, "Fonts"))
        local = os.environ.get("LOCALAPPDATA", "")
        if local:
            search_dirs.append(
                os.path.join(local, "Microsoft", "Windows", "Fonts"))
    elif sys.platform == "darwin":
        search_dirs += ["/System/Library/Fonts", "/Library/Fonts",
                        os.path.expanduser("~/Library/Fonts")]
    else:
        search_dirs += ["/usr/share/fonts", "/usr/local/share/fonts",
                        os.path.expanduser("~/.fonts"),
                        os.path.expanduser("~/.local/share/fonts")]
    for d in search_dirs:
        if not os.path.isdir(d):
            continue
        for root, _, files in os.walk(d):
            for f in files:
                if f.lower().endswith((".ttf", ".otf")):
                    fonts[os.path.splitext(f)[0]] = os.path.join(root, f)
    return dict(sorted(fonts.items(), key=lambda x: x[0].lower())) or {"Default": None}


def load_font(font_path, size):
    if font_path:
        try:
            return ImageFont.truetype(font_path, size)
        except (OSError, TypeError):
            pass
    for fp in ["C:/Windows/Fonts/arial.ttf",
               "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]:
        try:
            return ImageFont.truetype(fp, size)
        except (OSError, TypeError):
            continue
    try:
        return ImageFont.load_default(size)
    except TypeError:
        return ImageFont.load_default()


# ════════════════════════════════════════
#  Формат принтера
# ════════════════════════════════════════

def pil_to_funny_lines(img_1bit):
    raw = img_1bit.tobytes()
    bpl = PRINTER_WIDTH // 8
    lines = [bytes([b ^ 0xFF for b in raw[i:i + bpl]])
             for i in range(0, len(raw), bpl)]
    result = []
    it = iter(lines)
    while pair := tuple(islice(it, 2)):
        combined = bytearray(96)
        combined[:len(pair[0])] = pair[0]
        if len(pair) == 2:
            combined[48:48 + len(pair[1])] = pair[1]
        result.append(bytes(combined))
    return result


def _lines_to_preview(funny_lines):
    """funny_lines → PIL Image mode '1' для превью"""
    h = max(2, len(funny_lines) * 2)
    if h % 2:
        h += 1
    img = Image.new("1", (PRINTER_WIDTH, h), color=1)
    y = 0
    for fl in funny_lines:
        for row in range(2):
            if y >= h:
                break
            row_data = fl[row * 48:(row + 1) * 48]
            for byte_idx, byte_val in enumerate(row_data):
                for bit in range(8):
                    x = byte_idx * 8 + bit
                    if x < PRINTER_WIDTH:
                        if (byte_val >> (7 - bit)) & 1:
                            img.putpixel((x, y), 0)
            y += 1
    return img


# ════════════════════════════════════════
#  Фильтры и дизеринг
# ════════════════════════════════════════

def apply_filters(img, brightness=0, contrast=0, sharpness=0):
    if brightness:
        img = ImageEnhance.Brightness(img).enhance((brightness + 100) / 100)
    if contrast:
        img = ImageEnhance.Contrast(img).enhance((contrast + 100) / 100)
    if sharpness:
        img = ImageEnhance.Sharpness(img).enhance((sharpness + 100) / 100)
    return img


DITHER_METHODS = [
    "Floyd-Steinberg", "Atkinson", "Stucki", "Burkes",
    "Sierra", "Sierra Lite", "Ordered 4x4", "Ordered 8x8", "Порог",
]

_DIFFUSION_MATRICES = {
    "Atkinson": ([(1,0,1),(2,0,1),(-1,1,1),(0,1,1),(1,1,1),(0,2,1)], 8),
    "Stucki": ([(1,0,8),(2,0,4),(-2,1,2),(-1,1,4),(0,1,8),(1,1,4),
                 (2,1,2),(-2,2,1),(-1,2,2),(0,2,4),(1,2,2),(2,2,1)], 42),
    "Burkes": ([(1,0,8),(2,0,4),(-2,1,2),(-1,1,4),(0,1,8),
                 (1,1,4),(2,1,2)], 32),
    "Sierra": ([(1,0,5),(2,0,3),(-2,1,2),(-1,1,4),(0,1,5),(1,1,4),
                 (2,1,2),(-1,2,2),(0,2,3),(1,2,2)], 32),
    "Sierra Lite": ([(1,0,2),(-1,1,1),(0,1,1)], 4),
}


def _error_diffusion(img_gray, matrix, divisor):
    w, h = img_gray.size
    data = list(img_gray.getdata())
    px = [list(data[i * w:(i + 1) * w]) for i in range(h)]
    out = Image.new("1", (w, h))
    op = out.load()
    for y in range(h):
        for x in range(w):
            old = px[y][x]
            new = 255 if old > 127 else 0
            op[x, y] = new
            err = old - new
            for dx, dy, c in matrix:
                nx, ny = x + dx, y + dy
                if 0 <= nx < w and 0 <= ny < h:
                    px[ny][nx] = max(0, min(255,
                        int(px[ny][nx] + err * c / divisor)))
    return out


def _ordered_dither(img_gray, size=4):
    if size == 4:
        bayer = [[0,8,2,10],[12,4,14,6],[3,11,1,9],[15,7,13,5]]
        n = 16
    else:
        bayer = [
            [0,32,8,40,2,34,10,42],[48,16,56,24,50,18,58,26],
            [12,44,4,36,14,46,6,38],[60,28,52,20,62,30,54,22],
            [3,35,11,43,1,33,9,41],[51,19,59,27,49,17,57,25],
            [15,47,7,39,13,45,5,37],[63,31,55,23,61,29,53,21]]
        n = 64
    sz = len(bayer)
    w, h = img_gray.size
    px = img_gray.load()
    out = Image.new("1", (w, h))
    op = out.load()
    for y in range(h):
        for x in range(w):
            op[x, y] = 255 if px[x, y] > (bayer[y % sz][x % sz] / n) * 255 else 0
    return out


def dither_image(img_gray, method="Floyd-Steinberg"):
    if img_gray.mode != "L":
        img_gray = img_gray.convert("L")
    if method == "Floyd-Steinberg":
        return img_gray.convert("1")
    if method == "Порог":
        return img_gray.point(lambda x: 255 if x > 127 else 0, "1")
    if method.startswith("Ordered"):
        return _ordered_dither(img_gray, 8 if "8" in method else 4)
    if method in _DIFFUSION_MATRICES:
        m, d = _DIFFUSION_MATRICES[method]
        return _error_diffusion(img_gray, m, d)
    return img_gray.convert("1")


# ════════════════════════════════════════
#  Художественные фильтры
# ════════════════════════════════════════

ARTISTIC_FILTERS = [
    "Нет", "LineArt (контуры)", "LineArt (тонкие)", "Инверсия",
    "Высокий контраст", "Постеризация", "Тиснение", "Карандашный набросок",
]


def apply_artistic_filter(img, filter_name):
    if not filter_name or filter_name == "Нет":
        return img
    if img.mode != "RGB":
        img = img.convert("RGB")

    if filter_name == "LineArt (контуры)":
        return _lineart(img, thin=False)
    if filter_name == "LineArt (тонкие)":
        return _lineart(img, thin=True)
    if filter_name == "Инверсия":
        from PIL import ImageOps
        return ImageOps.invert(img)
    if filter_name == "Высокий контраст":
        import numpy as np
        gray = img.convert("L")
        arr = np.array(gray)
        return gray.point(lambda x: 255 if x > arr.mean() else 0).convert("RGB")
    if filter_name == "Постеризация":
        from PIL import ImageOps
        return ImageOps.posterize(img, 2)
    if filter_name == "Тиснение":
        from PIL import ImageFilter
        return img.convert("L").filter(ImageFilter.EMBOSS).convert("RGB")
    if filter_name == "Карандашный набросок":
        return _pencil_sketch(img)
    return img


def _lineart(img, thin=False):
    from PIL import ImageFilter, ImageOps
    gray = img.convert("L")
    if thin:
        edges = gray.filter(ImageFilter.Kernel(
            size=(3, 3), kernel=[-1,-1,-1,-1,8,-1,-1,-1,-1],
            scale=1, offset=0))
        edges = ImageOps.invert(edges)
        return edges.point(lambda x: 255 if x > 200 else 0).convert("RGB")
    edges = gray.filter(ImageFilter.FIND_EDGES)
    edges = ImageOps.invert(edges)
    return ImageEnhance.Contrast(edges.convert("RGB")).enhance(2.0)


def _pencil_sketch(img):
    from PIL import ImageFilter, ImageOps
    import numpy as np
    gray = img.convert("L")
    inv = ImageOps.invert(gray)
    blur = inv.filter(ImageFilter.GaussianBlur(radius=12))
    g = np.array(gray, dtype=np.float32)
    b = np.array(blur, dtype=np.float32)
    divisor = 256.0 - b
    divisor[divisor == 0] = 1
    result = np.clip(g * 256.0 / divisor, 0, 255).astype(np.uint8)
    return Image.fromarray(result, mode="L").convert("RGB")


# ════════════════════════════════════════
#  Утилиты изображений
# ════════════════════════════════════════

def _to_rgb(img):
    """Конвертирует любой режим в RGB, убирая прозрачность."""
    if img.mode in ("RGBA", "LA", "PA"):
        bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
        bg.paste(img, mask=img.split()[-1])
        return bg.convert("RGB")
    if img.mode != "RGB":
        return img.convert("RGB")
    return img


def _trim_whitespace(img):
    """Обрезает белые поля сверху и снизу."""
    gray = img.convert("L")
    mask = gray.point(lambda x: 0 if x > 245 else 255)
    bbox = mask.getbbox()
    if not bbox:
        return img
    pad = 4
    top = max(0, bbox[1] - pad)
    bottom = min(img.height, bbox[3] + pad)
    cropped = img.crop((0, top, img.width, bottom))
    return _even_height(cropped)


def _even_height(img):
    """Делает высоту чётной."""
    w, h = img.size
    if h % 2:
        canvas = Image.new("RGB", (w, h + 1), (255, 255, 255))
        canvas.paste(img, (0, 0))
        return canvas
    return img


def _fit_to_printer(img):
    """Подгоняет ширину к PRINTER_WIDTH, высота чётная."""
    w, h = img.size
    if w > PRINTER_WIDTH:
        new_h = max(2, int(h * PRINTER_WIDTH / w))
        img = img.resize((PRINTER_WIDTH, new_h), Image.LANCZOS)
    elif w < PRINTER_WIDTH:
        canvas = Image.new("RGB", (PRINTER_WIDTH, h), (255, 255, 255))
        canvas.paste(img, ((PRINTER_WIDTH - w) // 2, 0))
        img = canvas
    return _even_height(img)


def _scale_to_width(img):
    """Масштабирует к PRINTER_WIDTH пропорционально, высота чётная."""
    w, h = img.size
    new_h = max(2, int(h * PRINTER_WIDTH / w))
    if new_h % 2:
        new_h += 1
    return img.resize((PRINTER_WIDTH, new_h), Image.LANCZOS)


def _rotate_and_fit(img, angle):
    if not angle:
        return img
    img = img.rotate(-angle, expand=True, fillcolor=(255, 255, 255))
    img = _trim_whitespace(img)
    return _fit_to_printer(img)


def _apply_italic_line(line_img, line_h):
    shear = 0.2
    w, h = line_img.size
    extra = int(h * shear) + 8
    wide = Image.new("RGB", (w + extra * 2, h), (255, 255, 255))
    wide.paste(line_img, (extra, 0))
    wide = wide.transform(
        wide.size, Image.AFFINE,
        (1, -shear, shear * h * 0.5, 0, 1, 0),
        resample=Image.BILINEAR, fillcolor=(255, 255, 255))
    mask = wide.convert("L").point(lambda x: 0 if x > 245 else 255)
    bb = mask.getbbox()
    if bb:
        wide = wide.crop((max(0, bb[0] - 2), 0, min(wide.width, bb[2] + 2), h))
    return wide


def add_feed_preview(img_1bit, feed_px):
    """Добавляет белое пространство внизу для визуализации промотки."""
    if feed_px <= 0:
        return img_1bit
    w, h = img_1bit.size
    new_h = h + feed_px
    if new_h % 2:
        new_h += 1
    result = Image.new("1", (w, new_h), color=1)
    result.paste(img_1bit, (0, 0))
    return result


# ════════════════════════════════════════
#  Финализация (общий конвейер)
# ════════════════════════════════════════

def finalize_image(img, brightness=0, contrast=0, sharpness=0,
                   dither="Floyd-Steinberg", rotation=0,
                   artistic="Нет", border="Нет", trim=True):
    """Фильтры → artistic → border → rotation → trim → fit → dither → lines.
    Возвращает (funny_lines, bw_preview).
    """
    img = _to_rgb(img)
    img = apply_filters(img, brightness, contrast, sharpness)
    img = apply_artistic_filter(img, artistic)

    if border != "Нет":
        from funnyprint.borders import apply_border
        img = apply_border(img, border)
        img = _fit_to_printer(img)

    if rotation:
        img = _rotate_and_fit(img, rotation)
    elif trim:
        img = _trim_whitespace(img)
        img = _fit_to_printer(img)
    else:
        img = _fit_to_printer(img)

    bw = dither_image(img.convert("L"), dither)
    return pil_to_funny_lines(bw), bw


def _open_and_scale(path, rotation=0):
    """Открывает картинку, конвертирует в RGB, поворачивает, масштабирует."""
    img = _to_rgb(Image.open(path))
    if rotation:
        img = img.rotate(-rotation, expand=True, fillcolor=(255, 255, 255))
    return _scale_to_width(img)


def _finalize_to_bw(img, brightness=0, contrast=0, sharpness=0,
                    dither="Floyd-Steinberg", artistic="Нет", border="Нет"):
    """Финализация без rotation/trim (уже применены). Возвращает bw Image."""
    img = apply_filters(img, brightness, contrast, sharpness)
    img = apply_artistic_filter(img, artistic)
    if border != "Нет":
        from funnyprint.borders import apply_border
        img = apply_border(img, border)
        img = _fit_to_printer(img)
    return dither_image(img.convert("L"), dither)


# ════════════════════════════════════════
#  Склейка нескольких bw-картинок
# ════════════════════════════════════════

def _combine_bw(images_bw, feed_between=0):
    """Склеивает список bw-картинок вертикально с промежутками."""
    total_h = sum(im.height for im in images_bw)
    if feed_between > 0 and len(images_bw) > 1:
        total_h += feed_between * (len(images_bw) - 1)
    if total_h % 2:
        total_h += 1
    total_h = max(2, total_h)

    combined = Image.new("1", (PRINTER_WIDTH, total_h), color=1)
    y = 0
    for i, bw in enumerate(images_bw):
        combined.paste(bw, (0, y))
        y += bw.height
        if i < len(images_bw) - 1 and feed_between > 0:
            y += feed_between
    return combined


def _bw_list_to_lines(images_bw, feed_between=0):
    """bw-картинки → funny_lines с промежутками."""
    all_lines = []
    blank = bytes(96)
    gap = feed_between // 2 if feed_between > 0 else 0
    for i, bw in enumerate(images_bw):
        all_lines.extend(pil_to_funny_lines(bw))
        if i < len(images_bw) - 1 and gap > 0:
            all_lines.extend(blank for _ in range(gap))
    return all_lines


# ════════════════════════════════════════
#  Перенос строк
# ════════════════════════════════════════

def _wrap_text(text, font, max_width, draw, stroke=0):
    wrapped = []
    for raw_line in text.replace("\\n", "\n").split("\n"):
        if not raw_line:
            wrapped.append("")
            continue
        current = ""
        for word in raw_line.split(" "):
            test = (current + " " + word).strip()
            bbox = draw.textbbox((0, 0), test, font=font, stroke_width=stroke)
            if bbox[2] <= max_width:
                current = test
            else:
                if current:
                    wrapped.append(current)
                current = word
                bbox = draw.textbbox((0, 0), current, font=font,
                                     stroke_width=stroke)
                if bbox[2] > max_width:
                    chars = ""
                    for ch in current:
                        tc = chars + ch
                        bb = draw.textbbox((0, 0), tc, font=font,
                                           stroke_width=stroke)
                        if bb[2] > max_width and chars:
                            wrapped.append(chars)
                            chars = ch
                        else:
                            chars = tc
                    current = chars
        if current:
            wrapped.append(current)
    return wrapped


def _render_text_line(draw, img, line, font, stroke, italic, line_h,
                      x, y, align, width, pad):
    """Рендерит одну строку текста на img."""
    bbox = draw.textbbox((0, 0), line, font=font, stroke_width=stroke)
    tw = bbox[2] - bbox[0]

    if italic and line.strip():
        line_img = Image.new("RGB", (tw + 8, line_h), (255, 255, 255))
        ld = ImageDraw.Draw(line_img)
        ld.text((4, 0), line, font=font, fill=(0, 0, 0),
                stroke_width=stroke, stroke_fill=(0, 0, 0))
        line_img = _apply_italic_line(line_img, line_h)
        lw = line_img.width
        if align == "center":
            x = (width - lw) // 2
        elif align == "right":
            x = width - lw - pad
        px = max(0, x)
        cl, cr = max(0, -x), min(lw, width - px)
        if cr > cl:
            img.paste(line_img.crop((cl, 0, cr, line_h)), (px, y))
    else:
        if align == "center":
            x = (width - tw) // 2
        elif align == "right":
            x = width - tw - pad
        draw.text((x, y), line, font=font, fill=(0, 0, 0),
                  stroke_width=stroke, stroke_fill=(0, 0, 0))


# ════════════════════════════════════════
#  Подготовка данных для печати
# ════════════════════════════════════════

def prepare_image(path, **filters):
    img = _open_and_scale(path, filters.get("rotation", 0))
    return finalize_image(img, **{**filters, "rotation": 0}, trim=False)


def prepare_text(text, font_path=None, font_size=24,
                 bold=False, italic=False, align="left",
                 strip_mode=False, **filters):
    font = load_font(font_path, font_size)
    stroke = 2 if bold else 0
    line_h = font_size + 6
    pad = 8
    dummy = ImageDraw.Draw(Image.new("RGB", (1, 1)))

    if strip_mode:
        img = _render_strip(text, font, font_size, line_h, pad, stroke,
                            italic, align, dummy)
    else:
        img = _render_text(text, font, line_h, pad, stroke, italic,
                           align, dummy)

    return finalize_image(img, **filters, trim=True)


def _render_text(text, font, line_h, pad, stroke, italic, align, dummy):
    max_w = PRINTER_WIDTH - pad * 2
    wrapped = _wrap_text(text, font, max_w, dummy, stroke)
    img_h = max(32, line_h * len(wrapped) + pad * 2)
    if img_h % 2:
        img_h += 1
    img = Image.new("RGB", (PRINTER_WIDTH, img_h), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    y = pad
    for line in wrapped:
        _render_text_line(draw, img, line, font, stroke, italic,
                          line_h, pad, y, align, PRINTER_WIDTH, pad)
        y += line_h
    return img


def _render_strip(text, font, font_size, line_h, pad, stroke,
                  italic, align, dummy):
    max_lines = PRINTER_WIDTH // line_h
    lines = text.replace("\\n", "\n").split("\n")
    max_w = 0
    for line in lines:
        bbox = dummy.textbbox((0, 0), line, font=font, stroke_width=stroke)
        max_w = max(max_w, bbox[2] - bbox[0])
    img_w = max(max_w + pad * 2, 32)
    used = min(len(lines), max_lines)
    img_h = line_h * used + pad * 2
    img = Image.new("RGB", (img_w, img_h), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    y = pad
    for line in lines[:max_lines]:
        _render_text_line(draw, img, line, font, stroke, italic,
                          line_h, pad, y, align, img_w, pad)
        y += line_h
    img = _trim_whitespace(img)
    img = img.rotate(-90, expand=True, fillcolor=(255, 255, 255))
    return img


def get_strip_info(font_size):
    return PRINTER_WIDTH // (font_size + 6)


def prepare_pdf_page(path, page_num=0, **filters):
    import fitz
    doc = fitz.open(path)
    page = doc[page_num]
    zoom = PRINTER_WIDTH / page.rect.width * 2
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    doc.close()
    rotation = filters.get("rotation", 0)
    if rotation:
        img = img.rotate(-rotation, expand=True, fillcolor=(255, 255, 255))
    img = _fit_to_printer(img)
    return finalize_image(img, **{**filters, "rotation": 0}, trim=False)


def get_pdf_page_count(path):
    import fitz
    doc = fitz.open(path)
    count = len(doc)
    doc.close()
    return count


# ════════════════════════════════════════
#  QR / Barcode
# ════════════════════════════════════════

BARCODE_TYPES = [
    "code128", "code39", "ean13", "ean8", "upca",
    "isbn13", "isbn10", "issn", "pzn",
]


def generate_qr(data, add_text=False, font_path=None, font_size=16, **_):
    import qrcode
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M,
                        box_size=10, border=2)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    qr_size = PRINTER_WIDTH - 16
    img = img.resize((qr_size, qr_size), Image.NEAREST)

    if add_text and data:
        font = load_font(font_path, font_size)
        max_tw = PRINTER_WIDTH - 16
        dummy = ImageDraw.Draw(Image.new("RGB", (1, 1)))
        wrapped, current = [], ""
        for ch in data:
            test = current + ch
            if dummy.textbbox((0, 0), test, font=font)[2] > max_tw and current:
                wrapped.append(current)
                current = ch
            else:
                current = test
        if current:
            wrapped.append(current)
        lh = font_size + 4
        text_h = lh * len(wrapped) + 8
        combined = Image.new("RGB", (PRINTER_WIDTH, qr_size + text_h + 8),
                             (255, 255, 255))
        combined.paste(img, ((PRINTER_WIDTH - qr_size) // 2, 4))
        d = ImageDraw.Draw(combined)
        y = qr_size + 8
        for line in wrapped:
            tw = d.textbbox((0, 0), line, font=font)[2]
            d.text(((PRINTER_WIDTH - tw) // 2, y), line, font=font,
                   fill=(0, 0, 0))
            y += lh
        return combined

    combined = Image.new("RGB", (PRINTER_WIDTH, qr_size + 8), (255, 255, 255))
    combined.paste(img, ((PRINTER_WIDTH - qr_size) // 2, 4))
    return combined


def generate_barcode(data, barcode_type="code128", add_text=True):
    import barcode as bc
    from barcode.writer import ImageWriter
    try:
        code_class = bc.get_barcode_class(barcode_type)
    except bc.errors.BarcodeNotFoundError:
        code_class = bc.get_barcode_class("code128")
    valid = "".join(ch for ch in data if ord(ch) < 128)
    if not valid:
        raise ValueError("Штрих-код поддерживает только латиницу и цифры")
    buf = BytesIO()
    code_class(valid, writer=ImageWriter()).write(buf, options={
        "module_width": 0.4, "module_height": 25, "font_size": 0,
        "text_distance": 0, "quiet_zone": 2, "write_text": False,
    })
    buf.seek(0)
    img = Image.open(buf).convert("RGB")
    if add_text:
        font = load_font(None, 32)
        bbox = ImageDraw.Draw(Image.new("RGB", (1, 1))).textbbox(
            (0, 0), valid, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        combined = Image.new("RGB",
            (max(img.width, tw + 16), img.height + th + 12), (255, 255, 255))
        combined.paste(img, (0, 0))
        ImageDraw.Draw(combined).text(
            ((combined.width - tw) // 2, img.height + 6),
            valid, font=font, fill=(0, 0, 0))
        img = combined
    return img


def prepare_qr(data, add_text=False, font_path=None, font_size=16, **filters):
    img = generate_qr(data, add_text=add_text,
                      font_path=font_path, font_size=font_size)
    rotation = filters.get("rotation", 0)
    if rotation:
        img = img.rotate(-rotation, expand=True, fillcolor=(255, 255, 255))
    img = _fit_to_printer(img)
    return finalize_image(img, **{**filters, "rotation": 0}, trim=False)


def prepare_barcode(data, barcode_type="code128", add_text=True, **filters):
    img = generate_barcode(data, barcode_type, add_text)
    rotation = filters.get("rotation", 0)
    if rotation:
        img = img.rotate(-rotation, expand=True, fillcolor=(255, 255, 255))
    img = _trim_whitespace(img)
    img = _fit_to_printer(img)
    return finalize_image(img, **{**filters, "rotation": 0}, trim=False)


# ════════════════════════════════════════
#  Batch-обработка
# ════════════════════════════════════════

def prepare_batch_images(paths, feed_between=50, **filters):
    rotation = filters.get("rotation", 0)
    images_bw = []
    for path in paths:
        img = _open_and_scale(path, rotation)
        bw = _finalize_to_bw(img, **{k: v for k, v in filters.items()
                                     if k != "rotation"})
        images_bw.append(bw)

    MAX_PREVIEW_H = 20000
    total_h = sum(im.height for im in images_bw)
    if feed_between > 0 and len(images_bw) > 1:
        total_h += feed_between * (len(images_bw) - 1)
    preview_h = min(total_h if total_h % 2 == 0 else total_h + 1,
                    MAX_PREVIEW_H)

    combined = Image.new("1", (PRINTER_WIDTH, max(2, preview_h)), color=1)
    y = 0
    for i, bw in enumerate(images_bw):
        if y >= preview_h:
            break
        paste_h = min(bw.height, preview_h - y)
        combined.paste(bw.crop((0, 0, PRINTER_WIDTH, paste_h)), (0, y))
        y += bw.height
        if i < len(images_bw) - 1 and feed_between > 0:
            y += feed_between

    return _bw_list_to_lines(images_bw, feed_between), combined


def prepare_batch_pdf(path, pages, feed_between=50, **filters):
    import fitz
    rotation = filters.get("rotation", 0)
    flt = {k: v for k, v in filters.items() if k != "rotation"}
    doc = fitz.open(path)
    images_bw = []
    for pg in pages:
        page = doc[pg]
        zoom = PRINTER_WIDTH / page.rect.width * 2
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        if rotation:
            img = img.rotate(-rotation, expand=True,
                             fillcolor=(255, 255, 255))
        img = _fit_to_printer(img)
        images_bw.append(_finalize_to_bw(img, **flt))
    doc.close()

    combined = _combine_bw(images_bw, feed_between)
    return pil_to_funny_lines(combined), combined


def prepare_batch_images_chunked(paths, chunk_index=0, feed_between=50,
                                 **filters):
    from funnyprint.chunked import MAX_CHUNK_LINES
    rotation = filters.get("rotation", 0)
    flt = {k: v for k, v in filters.items() if k != "rotation"}

    # Оцениваем размеры без полной обработки
    file_line_counts = []
    for path in paths:
        try:
            img = Image.open(path)
            w, h = img.size
            file_line_counts.append((max(2, int(h * PRINTER_WIDTH / w)) + 1) // 2)
            img.close()
        except Exception:
            file_line_counts.append(50)

    feed_lines = feed_between // 2 if feed_between > 0 else 0

    # Разбиваем на чанки
    chunks_map, cur_lines, chunk_start = [], 0, 0
    for i, fc in enumerate(file_line_counts):
        if cur_lines + fc > MAX_CHUNK_LINES and cur_lines > 0:
            chunks_map.append((chunk_start, i))
            chunk_start, cur_lines = i, 0
        cur_lines += fc + feed_lines
    chunks_map.append((chunk_start, len(paths)))

    total_chunks = len(chunks_map)
    chunk_index = min(chunk_index, total_chunks - 1)
    start_file, end_file = chunks_map[chunk_index]

    images_bw = []
    for path in paths[start_file:end_file]:
        try:
            img = _open_and_scale(path, rotation)
            images_bw.append(_finalize_to_bw(img, **flt))
        except Exception:
            pass

    combined = _combine_bw(images_bw, feed_between)
    return pil_to_funny_lines(combined), combined, total_chunks, len(paths)


def prepare_text_chunked(text, chunk_index=0, **kwargs):
    from funnyprint.chunked import MAX_CHUNK_LINES, estimate_chunks
    lines, _ = prepare_text(text, **kwargs)
    total = len(lines)
    chunks = estimate_chunks(total)
    start = chunk_index * MAX_CHUNK_LINES
    chunk = lines[start:min(start + MAX_CHUNK_LINES, total)]
    return chunk, _lines_to_preview(chunk), chunks, total