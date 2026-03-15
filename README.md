# FunnyPrint LX-D2

GUI-приложение для печати на термопринтере **LX-D2 / LX-D02** (Xiqi / DOLEWA) через Bluetooth LE.

<div align="center">
  <img src="images\pic1.webp">
</div>
<div align="center">
  <img src="images\pic2.webp">
</div>

Протокол принтера основан на реверс-инжиниринге из [printer-driver-funnyprint](https://github.com/ValdikSS/printer-driver-funnyprint) by ValdikSS.

## Возможности

- Печать картинок (PNG, JPG, BMP, WebP, GIF)
- Печать текста с выбором шрифта, размера, жирности, курсива
- Выравнивание текста (лево / центр / право)
- Режим ленты (текст поворачивается на 90°) *(совмещается с поворотом, используйте аккуратно, выводите поворот в 0)*
- 9 методов дизеринга (Floyd-Steinberg, Atkinson, Stucki и др.)
- Фильтры: яркость, контраст, резкость
- Поворот 0-360°
- Предпросмотр с зумом
- Регулировка яркости печати (аппаратная, 0-7)
- Промотка бумаги
- Обработка перегрева и потери пакетов

## Совместимые принтеры

- LX-D2 / LX-D02
- LX-D3 / LX-D03
- LX-D5
- DOLEWA D3 Mini Printer
- Другие принтеры, работающие с приложением "Funny Print"
>Это написал Claude, лучше уточняйте. Но про "Funny Print" - скорее всего правда

## Установка

```bash
git clone https://github.com/klimromanyuk/funnyprint.git
cd funnyprint
pip install -r requirements.txt
cp .env.example .env
# Отредактируй .env — укажи MAC-адрес своего принтера
```

## Запуск

```bash
python run.py
```

## Настройка

Отредактируй файл `.env`:

```env
PRINTER_MAC=C0:00:00:00:07:35   # MAC-адрес принтера
PRINTER_NAME=LX-D02              # Имя для поиска
DEFAULT_DENSITY=3                 # Яркость по умолчанию (0-7)
```

MAC-адрес принтера можно узнать через кнопку «Подключить» — он отобразится в логе.

## Требования

- Python 3.10+
- Bluetooth LE адаптер
- Windows / Linux / macOS

## Благодарности

- [ValdikSS](https://github.com/ValdikSS) — реверс-инжиниринг протокола принтера
- Протокол: [printer-driver-funnyprint](https://github.com/ValdikSS/printer-driver-funnyprint)

## Лицензия

Apache License 2.0
