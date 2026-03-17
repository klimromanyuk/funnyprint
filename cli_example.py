#!/usr/bin/env python3
"""Пример использования PrintService без GUI."""

from funnyprint.service import PrintService
from funnyprint.imaging import prepare_text, prepare_image


def main():
    svc = PrintService(on_log=print)

    try:
        # Подготовка
        lines, bw = prepare_text(
            "Hello from CLI!\nТест печати",
            font_size=32, align="center")
        print(f"Lines: {len(lines)}, size: {bw.size}")
        bw.save("cli_preview.png")

        # Подключение
        future = svc.run_async(svc.connect())
        ok = future.result(timeout=30)
        if not ok:
            return

        # Печать
        future = svc.run_async(svc.print_lines(lines, density=3, feed=50))
        future.result(timeout=120)

        # Картинка:
        # lines, _ = prepare_image("photo.png")
        # future = svc.run_async(svc.print_lines(lines, density=3, feed=50))
        # future.result(timeout=120)

    finally:
        try:
            future = svc.run_async(svc.disconnect())
            future.result(timeout=5)
        except Exception:
            pass
        svc.stop()


if __name__ == "__main__":
    main()