"""FunnyPrint — драйвер для термопринтера LX-D2 / LX-D02"""
import os
from dotenv import load_dotenv

load_dotenv()

PRINTER_MAC = os.getenv("PRINTER_MAC", "C0:00:00:00:07:35")
PRINTER_NAME = os.getenv("PRINTER_NAME", "LX-D02")
PRINTER_WIDTH = int(os.getenv("PRINTER_WIDTH", "384"))
PRINTER_DPI = int(os.getenv("PRINTER_DPI", "203"))
DEFAULT_DENSITY = int(os.getenv("DEFAULT_DENSITY", "3"))
DEFAULT_FEED_AFTER = int(os.getenv("DEFAULT_FEED_AFTER", "50"))
SCAN_TIMEOUT = int(os.getenv("SCAN_TIMEOUT", "10"))
CONNECT_TIMEOUT = int(os.getenv("CONNECT_TIMEOUT", "30"))
SECRET_TEXT = os.getenv("SECRET_TEXT",
                        "Made by klimromanyuk and Claude with love")
WRITE_UUID = "0000ffe1-0000-1000-8000-00805f9b34fb"
NOTIFY_UUID = "0000ffe2-0000-1000-8000-00805f9b34fb"