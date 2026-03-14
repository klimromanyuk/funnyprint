"""Протокол общения с принтером LX-D2 (Xiqi/DOLEWA)
Источник: github.com/ValdikSS/printer-driver-funnyprint
"""

import binascii

_CHALLENGE = b"\x00" * 10


def _crc16(data: bytes) -> int:
    crc = 0
    for b in data:
        for i in range(8):
            bit = (b >> (7 - i)) & 1
            c15 = (crc >> 15) & 1
            crc = (crc << 1) & 0xFFFF
            if c15 ^ bit:
                crc ^= 0x1021
    return crc


def pkt_hw() -> bytes:
    """Запрос информации об устройстве"""
    return b"\x5a\x01" + b"\x00" * 10


def pkt_challenge() -> bytes:
    """Handshake фаза 1 — отправка challenge"""
    return b"\x5a\x0a" + _CHALLENGE


def pkt_response(mac: str) -> bytes:
    """Handshake фаза 2 — ответ на основе MAC-адреса"""
    mac_hex = mac.replace(":", "")
    payload = _CHALLENGE[0:1] + binascii.unhexlify(mac_hex)
    r = (_crc16(payload) >> 8) & 0xFF
    return b"\x5a\x0b" + bytes([r]) * 10


def pkt_density(d: int) -> bytes:
    """Установка яркости печати (0-7)"""
    return b"\x5a\x0c" + bytes([max(0, min(7, d))])


def pkt_print_event(num_lines: int, end: bool = False) -> bytes:
    """Начало/конец сессии печати"""
    return (b"\x5a\x04"
            + num_lines.to_bytes(2, "big")
            + end.to_bytes(2, "little"))


def pkt_print_line(line_no: int, data: bytes) -> bytes:
    """Одна строка растровых данных"""
    return b"\x55" + line_no.to_bytes(2, "big") + data + b"\x00"