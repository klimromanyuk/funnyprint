"""Обработка изображений для термопринтера"""

import os
import sys
from itertools import islice
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
    fonts = dict(sorted(fonts.items(), key=lambda x: x[0].lower()))
    return fonts if fonts else {"Default": None}


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


# ════════════════════════════════════════
#  Фильтры
# ════════════════════════════════════════

def apply_filters(img, brightness=0, contrast=0, sharpness=0):
    if brightness != 0:
        img = ImageEnhance.Brightness(img).enhance((brightness + 100) / 100)
    if contrast != 0:
        img = ImageEnhance.Contrast(img).enhance((contrast + 100) / 100)
    if sharpness != 0:
        img = ImageEnhance.Sharpness(img).enhance((sharpness + 100) / 100)
    return img


# ════════════════════════════════════════
#  Дизеринг
# ════════════════════════════════════════

DITHER_METHODS = [
    "Floyd-Steinberg", "Atkinson", "Stucki", "Burkes",
    "Sierra", "Sierra Lite", "Ordered 4x4", "Ordered 8x8", "Порог",
]

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
            op[x, y] = 255 if px[x, y] > (bayer[y%sz][x%sz]/n)*255 else 0
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
    matrices = {
        "Atkinson": ([(1,0,1),(2,0,1),(-1,1,1),(0,1,1),(1,1,1),(0,2,1)], 8),
        "Stucki": ([(1,0,8),(2,0,4),(-2,1,2),(-1,1,4),(0,1,8),(1,1,4),
                     (2,1,2),(-2,2,1),(-1,2,2),(0,2,4),(1,2,2),(2,2,1)], 42),
        "Burkes": ([(1,0,8),(2,0,4),(-2,1,2),(-1,1,4),(0,1,8),
                     (1,1,4),(2,1,2)], 32),
        "Sierra": ([(1,0,5),(2,0,3),(-2,1,2),(-1,1,4),(0,1,5),(1,1,4),
                     (2,1,2),(-1,2,2),(0,2,3),(1,2,2)], 32),
        "Sierra Lite": ([(1,0,2),(-1,1,1),(0,1,1)], 4),
    }
    if method in matrices:
        m, d = matrices[method]
        return _error_diffusion(img_gray, m, d)
    return img_gray.convert("1")


# ════════════════════════════════════════
#  Утилиты
# ════════════════════════════════════════

def _trim_whitespace(img):
    """Обрезает белые поля ТОЛЬКО сверху и снизу, бока не трогает"""
    gray = img.convert("L")
    mask = gray.point(lambda x: 0 if x > 245 else 255)
    bbox = mask.getbbox()
    if not bbox:
        return img
    pad = 4
    top = max(0, bbox[1] - pad)
    bottom = min(img.height, bbox[3] + pad)
    cropped = img.crop((0, top, img.width, bottom))
    w, h = cropped.size
    if h % 2:
        canvas = Image.new("RGB", (w, h + 1), (255, 255, 255))
        canvas.paste(cropped, (0, 0))
        cropped = canvas
    return cropped


def _fit_to_printer(img):
    """Подгоняет ширину к PRINTER_WIDTH, высота чётная.
    Если ширина уже равна PRINTER_WIDTH — только чётность высоты.
    Если меньше — центрируем на белом фоне (не растягиваем!).
    Если больше — масштабируем вниз.
    """
    w, h = img.size

    if w > PRINTER_WIDTH:
        new_h = max(2, int(h * PRINTER_WIDTH / w))
        img = img.resize((PRINTER_WIDTH, new_h), Image.LANCZOS)
        w, h = img.size
    elif w < PRINTER_WIDTH:
        canvas = Image.new("RGB", (PRINTER_WIDTH, h), (255, 255, 255))
        canvas.paste(img, ((PRINTER_WIDTH - w) // 2, 0))
        img = canvas
        w = PRINTER_WIDTH

    if h % 2:
        canvas = Image.new("RGB", (w, h + 1), (255, 255, 255))
        canvas.paste(img, (0, 0))
        img = canvas

    return img


def _rotate_and_fit(img, angle):
    """Поворот для текста — не обрезает бока"""
    if angle == 0:
        return img
    img = img.rotate(-angle, expand=True, fillcolor=(255, 255, 255))
    # Только верх/низ обрезаем
    img = _trim_whitespace(img)
    return _fit_to_printer(img)


def _apply_italic_line(line_img, line_h):
    """Наклоняет одну строку текста"""
    shear = 0.2
    w, h = line_img.size
    extra = int(h * shear) + 8
    wide = Image.new("RGB", (w + extra * 2, h), (255, 255, 255))
    wide.paste(line_img, (extra, 0))
    wide = wide.transform(
        wide.size, Image.AFFINE,
        (1, -shear, shear * h * 0.5, 0, 1, 0),
        resample=Image.BILINEAR, fillcolor=(255, 255, 255))
    # Обрезаем пустоту по бокам
    mask = wide.convert("L").point(lambda x: 0 if x > 245 else 255)
    bb = mask.getbbox()
    if bb:
        wide = wide.crop((max(0, bb[0] - 2), 0, min(wide.width, bb[2] + 2), h))
    return wide


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
            bbox = draw.textbbox((0, 0), test, font=font,
                                 stroke_width=stroke)
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


# ════════════════════════════════════════
#  Подготовка картинки
# ════════════════════════════════════════

def prepare_image(path, brightness=0, contrast=0, sharpness=0,
                  dither="Floyd-Steinberg", rotation=0,
                  artistic="Нет"):
    img = Image.open(path)
    if img.mode in ("RGBA", "LA", "PA"):
        bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
        bg.paste(img, mask=img.split()[-1])
        img = bg.convert("RGB")
    elif img.mode != "RGB":
        img = img.convert("RGB")
    if rotation:
        img = img.rotate(-rotation, expand=True, fillcolor=(255, 255, 255))
    w, h = img.size
    new_h = max(2, int(h * PRINTER_WIDTH / w))
    if new_h % 2:
        new_h += 1
    img = img.resize((PRINTER_WIDTH, new_h), Image.LANCZOS)
    img = apply_filters(img, brightness, contrast, sharpness)
    img = apply_artistic_filter(img, artistic)
    gray = img.convert("L")
    bw = dither_image(gray, dither)
    return pil_to_funny_lines(bw), bw


# ════════════════════════════════════════
#  Подготовка текста
# ════════════════════════════════════════

def prepare_text(text, font_path=None, font_size=24,
                 brightness=0, contrast=0, sharpness=0,
                 dither="Floyd-Steinberg", rotation=0,
                 bold=False, italic=False, align="left",
                 strip_mode=False, artistic="Нет"):
    font = load_font(font_path, font_size)
    stroke = 2 if bold else 0
    line_h = font_size + 6
    pad = 8
    dummy_draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))

    if strip_mode:
        return _prepare_strip(
            text, font, font_size, line_h, pad, stroke, italic,
            align, brightness, contrast, sharpness, dither,
            rotation, dummy_draw)

    # ── Обычный режим ──
    max_w = PRINTER_WIDTH - pad * 2
    wrapped = _wrap_text(text, font, max_w, dummy_draw, stroke)

    img_h = line_h * len(wrapped) + pad * 2
    if img_h < 32:
        img_h = 32
    if img_h % 2:
        img_h += 1

    img = Image.new("RGB", (PRINTER_WIDTH, img_h), (255, 255, 255))
    draw = ImageDraw.Draw(img)

    y = pad
    for line in wrapped:
        bbox = draw.textbbox((0, 0), line, font=font, stroke_width=stroke)
        tw = bbox[2] - bbox[0]

        if italic and line.strip():
            # Рендерим строку отдельно
            line_img = Image.new("RGB", (tw + 8, line_h), (255, 255, 255))
            ld = ImageDraw.Draw(line_img)
            ld.text((4, 0), line, font=font, fill=(0, 0, 0),
                    stroke_width=stroke, stroke_fill=(0, 0, 0))
            line_img = _apply_italic_line(line_img, line_h)
            lw = line_img.width

            if align == "center":
                x = (PRINTER_WIDTH - lw) // 2
            elif align == "right":
                x = PRINTER_WIDTH - lw - pad
            else:
                x = pad

            # Вставляем с обрезкой по границам
            px = max(0, x)
            cl = max(0, -x)
            cr = min(lw, PRINTER_WIDTH - px)
            if cr > cl:
                img.paste(line_img.crop((cl, 0, cr, line_h)), (px, y))
        else:
            if align == "center":
                x = (PRINTER_WIDTH - tw) // 2
            elif align == "right":
                x = PRINTER_WIDTH - tw - pad
            else:
                x = pad
            draw.text((x, y), line, font=font, fill=(0, 0, 0),
                      stroke_width=stroke, stroke_fill=(0, 0, 0))
        y += line_h

    img = apply_filters(img, brightness, contrast, sharpness)
    img = apply_artistic_filter(img, artistic)

    # Обрезаем пустоту, вписываем в PRINTER_WIDTH
    img = _trim_whitespace(img)
    img = _fit_to_printer(img)

    if rotation:
        img = _rotate_and_fit(img, rotation)

    gray = img.convert("L")
    bw = dither_image(gray, dither)
    return pil_to_funny_lines(bw), bw


def _prepare_strip(text, font, font_size, line_h, pad, stroke,
                   italic, align, brightness, contrast, sharpness,
                   dither, rotation, dummy_draw, artistic="Нет"):
    max_lines = PRINTER_WIDTH // line_h
    lines = text.replace("\\n", "\n").split("\n")

    max_w = 0
    for line in lines:
        bbox = dummy_draw.textbbox((0, 0), line, font=font,
                                   stroke_width=stroke)
        max_w = max(max_w, bbox[2] - bbox[0])

    img_w = max(max_w + pad * 2, 32)
    used = min(len(lines), max_lines)
    img_h = line_h * used + pad * 2

    img = Image.new("RGB", (img_w, img_h), (255, 255, 255))
    draw = ImageDraw.Draw(img)

    y = pad
    for line in lines[:max_lines]:
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
                x = (img_w - lw) // 2
            elif align == "right":
                x = img_w - lw - pad
            else:
                x = pad
            px = max(0, x)
            cl = max(0, -x)
            cr = min(lw, img_w - px)
            if cr > cl:
                img.paste(line_img.crop((cl, 0, cr, line_h)), (px, y))
        else:
            if align == "center":
                x = (img_w - tw) // 2
            elif align == "right":
                x = img_w - tw - pad
            else:
                x = pad
            draw.text((x, y), line, font=font, fill=(0, 0, 0),
                      stroke_width=stroke, stroke_fill=(0, 0, 0))
        y += line_h

    img = _trim_whitespace(img)
    img = img.rotate(-90, expand=True, fillcolor=(255, 255, 255))
    img = _trim_whitespace(img)
    img = _fit_to_printer(img)

    img = apply_filters(img, brightness, contrast, sharpness)
    img = apply_artistic_filter(img, artistic)
    if rotation:
        img = _rotate_and_fit(img, rotation)

    gray = img.convert("L")
    bw = dither_image(gray, dither)
    return pil_to_funny_lines(bw), bw


def get_strip_info(font_size):
    return PRINTER_WIDTH // (font_size + 6)


# ════════════════════════════════════════
#  PDF
# ════════════════════════════════════════

def get_pdf_page_count(path):
    import fitz
    doc = fitz.open(path)
    count = len(doc)
    doc.close()
    return count


def prepare_pdf_page(path, page_num=0, brightness=0, contrast=0,
                     sharpness=0, dither="Floyd-Steinberg", rotation=0,
                     artistic="Нет"):
    """Рендерит одну страницу PDF → (funny_lines, preview)"""
    import fitz
    doc = fitz.open(path)
    page = doc[page_num]

    # Рендерим с высоким DPI для качества
    zoom = PRINTER_WIDTH / page.rect.width * 2
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat)
    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    doc.close()

    if rotation:
        img = img.rotate(-rotation, expand=True, fillcolor=(255, 255, 255))

    img = _fit_to_printer(img)
    img = apply_filters(img, brightness, contrast, sharpness)
    img = apply_artistic_filter(img, artistic)
    gray = img.convert("L")
    bw = dither_image(gray, dither)
    return pil_to_funny_lines(bw), bw


# ════════════════════════════════════════
#  QR / Barcode
# ════════════════════════════════════════

def generate_qr(data, size=None, add_text=False, font_path=None,
                font_size=16):
    import qrcode
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10, border=2)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white").convert("RGB")

    # QR всегда по ширине принтера
    qr_size = PRINTER_WIDTH - 16
    img = img.resize((qr_size, qr_size), Image.NEAREST)

    if add_text and data:
        font = load_font(font_path, font_size)
        max_tw = PRINTER_WIDTH - 16
        dummy_draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))

        # Переносим длинный текст
        wrapped = []
        current = ""
        for ch in data:
            test = current + ch
            bbox = dummy_draw.textbbox((0, 0), test, font=font)
            if bbox[2] > max_tw and current:
                wrapped.append(current)
                current = ch
            else:
                current = test
        if current:
            wrapped.append(current)

        line_h = font_size + 4
        text_h = line_h * len(wrapped) + 8
        combined = Image.new("RGB",
            (PRINTER_WIDTH, qr_size + text_h + 8),
            (255, 255, 255))
        combined.paste(img, ((PRINTER_WIDTH - qr_size) // 2, 4))
        d = ImageDraw.Draw(combined)
        y = qr_size + 8
        for line in wrapped:
            bbox = d.textbbox((0, 0), line, font=font)
            tw = bbox[2] - bbox[0]
            d.text(((PRINTER_WIDTH - tw) // 2, y),
                   line, font=font, fill=(0, 0, 0))
            y += line_h
        img = combined
    else:
        # Центрируем QR на белом фоне
        combined = Image.new("RGB", (PRINTER_WIDTH, qr_size + 8),
                             (255, 255, 255))
        combined.paste(img, ((PRINTER_WIDTH - qr_size) // 2, 4))
        img = combined

    return img

def generate_barcode(data, barcode_type="code128", add_text=True):
    import barcode as bc
    from barcode.writer import ImageWriter

    try:
        code_class = bc.get_barcode_class(barcode_type)
    except bc.errors.BarcodeNotFoundError:
        code_class = bc.get_barcode_class("code128")

    # Валидация: убираем невалидные символы
    valid = ""
    for ch in data:
        if ord(ch) < 128:
            valid += ch
    if not valid:
        raise ValueError("Штрих-код поддерживает только латиницу и цифры")

    writer = ImageWriter()
    code = code_class(valid, writer=writer)

    from io import BytesIO
    buf = BytesIO()
    code.write(buf, options={
        "module_width": 0.4,
        "module_height": 25,
        "font_size": 0,
        "text_distance": 0,
        "quiet_zone": 2,
        "write_text": False,
    })
    buf.seek(0)
    img = Image.open(buf).convert("RGB")

    if add_text:
        font = load_font(None, 32)
        draw_dummy = ImageDraw.Draw(Image.new("RGB", (1, 1)))
        bbox = draw_dummy.textbbox((0, 0), valid, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]

        combined = Image.new("RGB",
            (max(img.width, tw + 16), img.height + th + 12),
            (255, 255, 255))
        combined.paste(img, (0, 0))
        d = ImageDraw.Draw(combined)
        d.text(((combined.width - tw) // 2, img.height + 6),
               valid, font=font, fill=(0, 0, 0))
        img = combined

    return img


BARCODE_TYPES = [
    "code128", "code39", "ean13", "ean8", "upca",
    "isbn13", "isbn10", "issn", "pzn",
]


def prepare_qr(data, add_text=False, font_path=None, font_size=16,
               brightness=0, contrast=0, sharpness=0,
               dither="Floyd-Steinberg", rotation=0, artistic="Нет"):
    img = generate_qr(data, add_text=add_text,
                      font_path=font_path, font_size=font_size)
    if rotation:
        img = img.rotate(-rotation, expand=True, fillcolor=(255, 255, 255))
    img = _fit_to_printer(img)
    img = apply_filters(img, brightness, contrast, sharpness)
    img = apply_artistic_filter(img, artistic)
    gray = img.convert("L")
    bw = dither_image(gray, dither)
    return pil_to_funny_lines(bw), bw


def prepare_barcode(data, barcode_type="code128", add_text=True,
                    brightness=0, contrast=0, sharpness=0,
                    dither="Floyd-Steinberg", rotation=0, artistic="Нет"):
    img = generate_barcode(data, barcode_type, add_text)
    if rotation:
        img = img.rotate(-rotation, expand=True, fillcolor=(255, 255, 255))
    img = _trim_whitespace(img)
    img = _fit_to_printer(img)
    img = apply_filters(img, brightness, contrast, sharpness)
    img = apply_artistic_filter(img, artistic)
    gray = img.convert("L")
    bw = dither_image(gray, dither)
    return pil_to_funny_lines(bw), bw


def add_feed_preview(img_1bit, feed_px):
    """Добавляет белое пространство внизу для визуализации промотки"""
    if feed_px <= 0:
        return img_1bit
    w, h = img_1bit.size
    new_h = h + feed_px
    if new_h % 2:
        new_h += 1
    result = Image.new("1", (w, new_h), color=1)  # белый
    result.paste(img_1bit, (0, 0))
    return result


def prepare_batch_images(paths, brightness=0, contrast=0, sharpness=0,
                         dither="Floyd-Steinberg", rotation=0,
                         feed_between=50, artistic="Нет"):
    """Несколько картинок → одна длинная + funny_lines"""
    images_bw = []
    for path in paths:
        img = Image.open(path)
        if img.mode in ("RGBA", "LA", "PA"):
            bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
            bg.paste(img, mask=img.split()[-1])
            img = bg.convert("RGB")
        elif img.mode != "RGB":
            img = img.convert("RGB")
        if rotation:
            img = img.rotate(-rotation, expand=True, fillcolor=(255, 255, 255))
        # Всегда масштабируем по ширине принтера
        w, h = img.size
        new_h = max(2, int(h * PRINTER_WIDTH / w))
        if new_h % 2:
            new_h += 1
        img = img.resize((PRINTER_WIDTH, new_h), Image.LANCZOS)
        img = apply_filters(img, brightness, contrast, sharpness)
        img = apply_artistic_filter(img, artistic)
        gray = img.convert("L")
        bw = dither_image(gray, dither)
        images_bw.append(bw)

    # Склеиваем в одну длинную картинку с промотками между ними
    total_h = sum(im.height for im in images_bw)
    if feed_between > 0:
        total_h += feed_between * (len(images_bw) - 1)
    if total_h % 2:
        total_h += 1

    combined = Image.new("1", (PRINTER_WIDTH, total_h), color=1)
    y = 0
    for i, bw in enumerate(images_bw):
        combined.paste(bw, (0, y))
        y += bw.height
        if i < len(images_bw) - 1 and feed_between > 0:
            y += feed_between

    return pil_to_funny_lines(combined), combined


def prepare_batch_pdf(path, pages, brightness=0, contrast=0, sharpness=0,
                      dither="Floyd-Steinberg", rotation=0, feed_between=50,
                      artistic="Нет"):
    """Несколько страниц PDF → одна длинная + funny_lines"""
    import fitz
    doc = fitz.open(path)
    images_bw = []

    for pg in pages:
        page = doc[pg]
        zoom = PRINTER_WIDTH / page.rect.width * 2
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        if rotation:
            img = img.rotate(-rotation, expand=True, fillcolor=(255, 255, 255))
        img = _fit_to_printer(img)
        img = apply_filters(img, brightness, contrast, sharpness)
        img = apply_artistic_filter(img, artistic)
        gray = img.convert("L")
        bw = dither_image(gray, dither)
        images_bw.append(bw)

    doc.close()

    total_h = sum(im.height for im in images_bw)
    if feed_between > 0:
        total_h += feed_between * (len(images_bw) - 1)
    if total_h % 2:
        total_h += 1

    combined = Image.new("1", (PRINTER_WIDTH, total_h), color=1)
    y = 0
    for i, bw in enumerate(images_bw):
        combined.paste(bw, (0, y))
        y += bw.height
        if i < len(images_bw) - 1 and feed_between > 0:
            y += feed_between

    return pil_to_funny_lines(combined), combined

# ════════════════════════════════════════
#  Художественные фильтры
# ════════════════════════════════════════

ARTISTIC_FILTERS = [
    "Нет",
    "LineArt (контуры)",
    "LineArt (тонкие)",
    "Инверсия",
    "Высокий контраст",
    "Постеризация",
    "Тиснение",
    "Карандашный набросок",
]


def apply_artistic_filter(img, filter_name):
    """Применяет художественный фильтр к RGB изображению"""
    if filter_name == "Нет" or not filter_name:
        return img

    if img.mode != "RGB":
        img = img.convert("RGB")

    if filter_name == "LineArt (контуры)":
        return _lineart(img, thin=False)

    elif filter_name == "LineArt (тонкие)":
        return _lineart(img, thin=True)

    elif filter_name == "Инверсия":
        from PIL import ImageOps
        return ImageOps.invert(img)

    elif filter_name == "Высокий контраст":
        gray = img.convert("L")
        # Порог по среднему
        import numpy as np
        arr = np.array(gray)
        threshold = arr.mean()
        bw = gray.point(lambda x: 255 if x > threshold else 0)
        return bw.convert("RGB")

    elif filter_name == "Постеризация":
        from PIL import ImageOps
        return ImageOps.posterize(img, 2)

    elif filter_name == "Тиснение":
        from PIL import ImageFilter
        gray = img.convert("L")
        emboss = gray.filter(ImageFilter.EMBOSS)
        return emboss.convert("RGB")

    elif filter_name == "Карандашный набросок":
        return _pencil_sketch(img)

    return img


def _lineart(img, thin=False):
    from PIL import ImageFilter, ImageOps
    gray = img.convert("L")
    if thin:
        # Canny-подобный: два прохода с разным порогом
        edges1 = gray.filter(ImageFilter.Kernel(
            size=(3, 3),
            kernel=[-1, -1, -1, -1, 8, -1, -1, -1, -1],
            scale=1, offset=0))
        edges1 = ImageOps.invert(edges1)
        edges1 = edges1.point(lambda x: 255 if x > 200 else 0)
        return edges1.convert("RGB")
    else:
        edges = gray.filter(ImageFilter.FIND_EDGES)
        edges = ImageOps.invert(edges)
        edges = ImageEnhance.Contrast(edges.convert("RGB")).enhance(2.0)
        return edges

def _pencil_sketch(img):
    """Эффект карандашного наброска"""
    from PIL import ImageFilter, ImageOps
    import numpy as np

    gray = img.convert("L")

    # Инвертируем
    inv = ImageOps.invert(gray)

    # Размытие инвертированного
    blur = inv.filter(ImageFilter.GaussianBlur(radius=12))

    # Color Dodge: result = gray * 256 / (256 - blur)
    gray_arr = np.array(gray, dtype=np.float32)
    blur_arr = np.array(blur, dtype=np.float32)

    # Избегаем деления на 0
    divisor = 256.0 - blur_arr
    divisor[divisor == 0] = 1

    result = np.clip(gray_arr * 256.0 / divisor, 0, 255).astype(np.uint8)

    sketch = Image.fromarray(result, mode="L")
    return sketch.convert("RGB")