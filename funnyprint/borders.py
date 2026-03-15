"""Рамки и бордеры для термопринтера"""

from PIL import Image, ImageDraw

from funnyprint import PRINTER_WIDTH


def get_border_names():
    return [
        "Нет",
        "Простая линия",
        "Двойная линия",
        "Толстая рамка",
        "Закруглённая",
        "Точечная",
        "Штриховая",
        "Тень",
        "Декоративная",
        "Волнистая",
        "Зигзаг",
        "Цепочка",
        "Кресты",
        "Ромбы",
        "Зубчатая",
        "Плетёнка",
        "Сердечки",
        "Звёзды",
    ]


def apply_border(img, border_name, padding=12):
    """Применяет рамку к PIL Image (mode '1' или 'RGB').
    Возвращает новое изображение с рамкой."""
    if border_name == "Нет" or not border_name:
        return img

    # Работаем в RGB
    if img.mode == "1":
        img = img.convert("RGB")
    elif img.mode == "L":
        img = img.convert("RGB")

    w, h = img.size
    new_w = w + padding * 2
    new_h = h + padding * 2

    result = Image.new("RGB", (new_w, new_h), (255, 255, 255))
    result.paste(img, (padding, padding))
    draw = ImageDraw.Draw(result)

    if border_name == "Простая линия":
        _simple_border(draw, new_w, new_h, width=2)

    elif border_name == "Двойная линия":
        _simple_border(draw, new_w, new_h, width=2)
        _simple_border(draw, new_w, new_h, width=1, inset=5)

    elif border_name == "Толстая рамка":
        _simple_border(draw, new_w, new_h, width=5)

    elif border_name == "Закруглённая":
        _rounded_border(draw, new_w, new_h, radius=12, width=2)

    elif border_name == "Точечная":
        _dotted_border(draw, new_w, new_h, dot_spacing=6)

    elif border_name == "Штриховая":
        _dashed_border(draw, new_w, new_h, dash_len=10, gap_len=5)

    elif border_name == "Тень":
        result = _shadow_border(img, padding)

    elif border_name == "Декоративная":
        _decorative_border(draw, new_w, new_h)

    elif border_name == "Волнистая":
        result = _wavy_border(img, padding)
    elif border_name == "Зигзаг":
        result = _zigzag_border(img, padding)
    elif border_name == "Цепочка":
        result = _chain_border(img, padding)
    elif border_name == "Кресты":
        result = _crosses_border(img, padding)
    elif border_name == "Ромбы":
        result = _diamonds_border(img, padding)
    elif border_name == "Зубчатая":
        result = _sawtooth_border(img, padding)
    elif border_name == "Плетёнка":
        result = _braid_border(img, padding)
    elif border_name == "Сердечки":
        result = _hearts_border(img, padding)
    elif border_name == "Звёзды":
        result = _stars_border(img, padding)

    return result


def _simple_border(draw, w, h, width=2, inset=0):
    for i in range(width):
        draw.rectangle(
            [inset + i, inset + i, w - 1 - inset - i, h - 1 - inset - i],
            outline=(0, 0, 0))


def _rounded_border(draw, w, h, radius=12, width=2):
    for i in range(width):
        draw.rounded_rectangle(
            [i, i, w - 1 - i, h - 1 - i],
            radius=radius, outline=(0, 0, 0))


def _dotted_border(draw, w, h, dot_spacing=6):
    for x in range(0, w, dot_spacing):
        draw.rectangle([x, 0, x + 1, 1], fill=(0, 0, 0))
        draw.rectangle([x, h - 2, x + 1, h - 1], fill=(0, 0, 0))
    for y in range(0, h, dot_spacing):
        draw.rectangle([0, y, 1, y + 1], fill=(0, 0, 0))
        draw.rectangle([w - 2, y, w - 1, y + 1], fill=(0, 0, 0))


def _dashed_border(draw, w, h, dash_len=10, gap_len=5):
    step = dash_len + gap_len
    # Верх и низ
    for x in range(0, w, step):
        draw.line([(x, 0), (min(x + dash_len, w), 0)],
                  fill=(0, 0, 0), width=2)
        draw.line([(x, h - 1), (min(x + dash_len, w), h - 1)],
                  fill=(0, 0, 0), width=2)
    # Лево и право
    for y in range(0, h, step):
        draw.line([(0, y), (0, min(y + dash_len, h))],
                  fill=(0, 0, 0), width=2)
        draw.line([(w - 1, y), (w - 1, min(y + dash_len, h))],
                  fill=(0, 0, 0), width=2)


def _shadow_border(img, padding):
    w, h = img.size
    shadow_offset = 4
    new_w = w + padding * 2 + shadow_offset
    new_h = h + padding * 2 + shadow_offset

    result = Image.new("RGB", (new_w, new_h), (255, 255, 255))
    draw = ImageDraw.Draw(result)

    # Тень
    draw.rectangle(
        [padding + shadow_offset, padding + shadow_offset,
         padding + w + shadow_offset, padding + h + shadow_offset],
        fill=(100, 100, 100))

    # Белый фон под контентом
    draw.rectangle(
        [padding, padding, padding + w, padding + h],
        fill=(255, 255, 255))

    # Контент
    result.paste(img, (padding, padding))

    # Рамка
    draw.rectangle(
        [padding, padding, padding + w, padding + h],
        outline=(0, 0, 0), width=1)

    return result


def _decorative_border(draw, w, h):
    _simple_border(draw, w, h, width=2)
    _simple_border(draw, w, h, width=1, inset=4)
    # Уголки
    corner_size = 15
    for cx, cy, dx, dy in [(0, 0, 1, 1), (w - 1, 0, -1, 1),
                            (0, h - 1, 1, -1), (w - 1, h - 1, -1, -1)]:
        for i in range(corner_size):
            x = cx + dx * i
            y = cy + dy * i
            draw.rectangle([x, y, x, y], fill=(0, 0, 0))
            # Диагональ
            x2 = cx + dx * (corner_size - 1 - i)
            y2 = cy + dy * i
            draw.rectangle([x2, y2, x2, y2], fill=(0, 0, 0))


def _wavy_border(img, padding):
    import math
    w, h = img.size
    wave_amp = 3
    wave_freq = 0.15
    new_w = w + padding * 2
    new_h = h + padding * 2

    result = Image.new("RGB", (new_w, new_h), (255, 255, 255))
    result.paste(img, (padding, padding))
    draw = ImageDraw.Draw(result)

    # Верхняя и нижняя волна
    for x in range(new_w):
        yt = int(wave_amp * math.sin(x * wave_freq)) + 2
        yb = new_h - 3 + int(wave_amp * math.sin(x * wave_freq))
        draw.rectangle([x, yt, x, yt + 1], fill=(0, 0, 0))
        draw.rectangle([x, yb, x, yb + 1], fill=(0, 0, 0))

    # Левая и правая волна
    for y in range(new_h):
        xl = int(wave_amp * math.sin(y * wave_freq)) + 2
        xr = new_w - 3 + int(wave_amp * math.sin(y * wave_freq))
        draw.rectangle([xl, y, xl + 1, y], fill=(0, 0, 0))
        draw.rectangle([xr, y, xr + 1, y], fill=(0, 0, 0))

    return result


def _zigzag_border(img, padding):
    import math
    w, h = img.size
    new_w = w + padding * 2
    new_h = h + padding * 2
    result = Image.new("RGB", (new_w, new_h), (255, 255, 255))
    result.paste(img, (padding, padding))
    draw = ImageDraw.Draw(result)
    zw = 8  # ширина зигзага
    zh = 5  # высота зигзага

    # Верх и низ
    for x in range(0, new_w, zw * 2):
        draw.line([(x, 2), (x + zw, 2 + zh), (x + zw * 2, 2)],
                  fill=(0, 0, 0), width=2)
        draw.line([(x, new_h - 3), (x + zw, new_h - 3 - zh),
                   (x + zw * 2, new_h - 3)], fill=(0, 0, 0), width=2)
    # Лево и право
    for y in range(0, new_h, zw * 2):
        draw.line([(2, y), (2 + zh, y + zw), (2, y + zw * 2)],
                  fill=(0, 0, 0), width=2)
        draw.line([(new_w - 3, y), (new_w - 3 - zh, y + zw),
                   (new_w - 3, y + zw * 2)], fill=(0, 0, 0), width=2)
    return result


def _chain_border(img, padding):
    w, h = img.size
    new_w = w + padding * 2
    new_h = h + padding * 2
    result = Image.new("RGB", (new_w, new_h), (255, 255, 255))
    result.paste(img, (padding, padding))
    draw = ImageDraw.Draw(result)
    link_w, link_h = 10, 6
    # Верх и низ
    for x in range(4, new_w - 4, link_w + 4):
        draw.ellipse([x, 1, x + link_w, 1 + link_h], outline=(0, 0, 0), width=2)
        draw.ellipse([x, new_h - 2 - link_h, x + link_w, new_h - 2],
                     outline=(0, 0, 0), width=2)
    # Лево и право
    for y in range(4, new_h - 4, link_w + 4):
        draw.ellipse([1, y, 1 + link_h, y + link_w], outline=(0, 0, 0), width=2)
        draw.ellipse([new_w - 2 - link_h, y, new_w - 2, y + link_w],
                     outline=(0, 0, 0), width=2)
    return result


def _crosses_border(img, padding):
    w, h = img.size
    new_w = w + padding * 2
    new_h = h + padding * 2
    result = Image.new("RGB", (new_w, new_h), (255, 255, 255))
    result.paste(img, (padding, padding))
    draw = ImageDraw.Draw(result)
    step = 12
    cs = 3  # размер креста
    for x in range(step // 2, new_w, step):
        draw.line([(x - cs, 3), (x + cs, 3)], fill=(0, 0, 0), width=2)
        draw.line([(x, 3 - cs), (x, 3 + cs)], fill=(0, 0, 0), width=2)
        draw.line([(x - cs, new_h - 4), (x + cs, new_h - 4)],
                  fill=(0, 0, 0), width=2)
        draw.line([(x, new_h - 4 - cs), (x, new_h - 4 + cs)],
                  fill=(0, 0, 0), width=2)
    for y in range(step // 2, new_h, step):
        draw.line([(3 - cs, y), (3 + cs, y)], fill=(0, 0, 0), width=2)
        draw.line([(3, y - cs), (3, y + cs)], fill=(0, 0, 0), width=2)
        draw.line([(new_w - 4 - cs, y), (new_w - 4 + cs, y)],
                  fill=(0, 0, 0), width=2)
        draw.line([(new_w - 4, y - cs), (new_w - 4, y + cs)],
                  fill=(0, 0, 0), width=2)
    return result


def _diamonds_border(img, padding):
    w, h = img.size
    new_w = w + padding * 2
    new_h = h + padding * 2
    result = Image.new("RGB", (new_w, new_h), (255, 255, 255))
    result.paste(img, (padding, padding))
    draw = ImageDraw.Draw(result)
    step = 14
    ds = 4
    for x in range(step // 2, new_w, step):
        draw.polygon([(x, 1), (x + ds, 1 + ds), (x, 1 + ds * 2),
                      (x - ds, 1 + ds)], outline=(0, 0, 0), width=1)
        draw.polygon([(x, new_h - 2 - ds * 2), (x + ds, new_h - 2 - ds),
                      (x, new_h - 2), (x - ds, new_h - 2 - ds)],
                     outline=(0, 0, 0), width=1)
    for y in range(step // 2, new_h, step):
        draw.polygon([(1, y), (1 + ds, y + ds), (1, y + ds * 2),
                      (1 - ds + 2, y + ds)], outline=(0, 0, 0), width=1)
        draw.polygon([(new_w - 2 - ds * 2 + ds, y),
                      (new_w - 2, y + ds),
                      (new_w - 2 - ds * 2 + ds, y + ds * 2),
                      (new_w - 2 - ds * 2, y + ds)],
                     outline=(0, 0, 0), width=1)
    return result


def _sawtooth_border(img, padding):
    w, h = img.size
    new_w = w + padding * 2
    new_h = h + padding * 2
    result = Image.new("RGB", (new_w, new_h), (255, 255, 255))
    result.paste(img, (padding, padding))
    draw = ImageDraw.Draw(result)
    tooth = 8
    for x in range(0, new_w, tooth):
        draw.polygon([(x, 6), (x + tooth // 2, 0), (x + tooth, 6)],
                     fill=(0, 0, 0))
        draw.polygon([(x, new_h - 7), (x + tooth // 2, new_h - 1),
                      (x + tooth, new_h - 7)], fill=(0, 0, 0))
    for y in range(0, new_h, tooth):
        draw.polygon([(6, y), (0, y + tooth // 2), (6, y + tooth)],
                     fill=(0, 0, 0))
        draw.polygon([(new_w - 7, y), (new_w - 1, y + tooth // 2),
                      (new_w - 7, y + tooth)], fill=(0, 0, 0))
    return result


def _braid_border(img, padding):
    import math
    w, h = img.size
    new_w = w + padding * 2
    new_h = h + padding * 2
    result = Image.new("RGB", (new_w, new_h), (255, 255, 255))
    result.paste(img, (padding, padding))
    draw = ImageDraw.Draw(result)
    freq = 0.3
    amp = 3
    for x in range(new_w):
        y1 = int(amp * math.sin(x * freq)) + 3
        y2 = int(amp * math.sin(x * freq + math.pi)) + 3
        draw.rectangle([x, y1, x, y1 + 1], fill=(0, 0, 0))
        draw.rectangle([x, y2, x, y2 + 1], fill=(0, 0, 0))
        yb1 = new_h - 4 + int(amp * math.sin(x * freq))
        yb2 = new_h - 4 + int(amp * math.sin(x * freq + math.pi))
        draw.rectangle([x, yb1, x, yb1 + 1], fill=(0, 0, 0))
        draw.rectangle([x, yb2, x, yb2 + 1], fill=(0, 0, 0))
    for y in range(new_h):
        x1 = int(amp * math.sin(y * freq)) + 3
        x2 = int(amp * math.sin(y * freq + math.pi)) + 3
        draw.rectangle([x1, y, x1 + 1, y], fill=(0, 0, 0))
        draw.rectangle([x2, y, x2 + 1, y], fill=(0, 0, 0))
        xr1 = new_w - 4 + int(amp * math.sin(y * freq))
        xr2 = new_w - 4 + int(amp * math.sin(y * freq + math.pi))
        draw.rectangle([xr1, y, xr1 + 1, y], fill=(0, 0, 0))
        draw.rectangle([xr2, y, xr2 + 1, y], fill=(0, 0, 0))
    return result


def _hearts_border(img, padding):
    import math
    w, h = img.size
    new_w = w + padding * 2
    new_h = h + padding * 2
    result = Image.new("RGB", (new_w, new_h), (255, 255, 255))
    result.paste(img, (padding, padding))
    draw = ImageDraw.Draw(result)
    step = 18
    hs = 5

    def draw_heart(cx, cy, s):
        pts = []
        for t_deg in range(0, 360, 10):
            t = math.radians(t_deg)
            x = s * 16 * math.sin(t) ** 3 / 16
            y = -s * (13 * math.cos(t) - 5 * math.cos(2*t) -
                      2 * math.cos(3*t) - math.cos(4*t)) / 16
            pts.append((cx + int(x), cy + int(y)))
        if len(pts) > 2:
            draw.polygon(pts, fill=(0, 0, 0))

    for x in range(step // 2, new_w, step):
        draw_heart(x, 5, hs)
        draw_heart(x, new_h - 6, hs)
    for y in range(step // 2, new_h, step):
        draw_heart(4, y, hs)
        draw_heart(new_w - 5, y, hs)
    return result


def _stars_border(img, padding):
    import math
    w, h = img.size
    new_w = w + padding * 2
    new_h = h + padding * 2
    result = Image.new("RGB", (new_w, new_h), (255, 255, 255))
    result.paste(img, (padding, padding))
    draw = ImageDraw.Draw(result)
    step = 16
    ss = 4

    def draw_star(cx, cy, s):
        pts = []
        for i in range(5):
            a = math.radians(-90 + i * 72)
            pts.append((cx + int(s * math.cos(a)),
                        cy + int(s * math.sin(a))))
            a2 = math.radians(-90 + i * 72 + 36)
            pts.append((cx + int(s * 0.4 * math.cos(a2)),
                        cy + int(s * 0.4 * math.sin(a2))))
        draw.polygon(pts, fill=(0, 0, 0))

    for x in range(step // 2, new_w, step):
        draw_star(x, 5, ss)
        draw_star(x, new_h - 6, ss)
    for y in range(step // 2, new_h, step):
        draw_star(5, y, ss)
        draw_star(new_w - 6, y, ss)
    return result