"""BLE-драйвер принтера"""

import asyncio
from functools import partial
from typing import Callable

from bleak import BleakClient, BleakScanner

from funnyprint import (
    PRINTER_MAC, PRINTER_NAME, WRITE_UUID, NOTIFY_UUID,
    SCAN_TIMEOUT, CONNECT_TIMEOUT,
)
from funnyprint.protocol import (
    pkt_hw, pkt_challenge, pkt_response,
    pkt_density, pkt_print_event, pkt_print_line,
)


class Printer:
    """Управление принтером через BLE"""

    def __init__(
        self,
        client: BleakClient,
        mac: str,
        on_log: Callable[[str], None] = print,
        on_progress: Callable[[int], None] | None = None,
    ):
        self.client = client
        self.mac = mac
        self.log = on_log
        self.on_progress = on_progress
        self._hs_q: asyncio.Queue = asyncio.Queue()
        self._ctrl_q: asyncio.Queue = asyncio.Queue()
        self.battery: int | str = "?"
        self._cancel = False
        self._overheat = False
        self._no_paper_logged = False

    async def _write(self, data: bytes):
        await self.client.write_gatt_char(WRITE_UUID, data, response=False)

    def _on_notify(self, sender, data):
        pt = data[0:2]
        if pt == b"\x5a\x0a":
            self._hs_q.put_nowait(data)
        elif pt == b"\x5a\x0b":
            self._hs_q.put_nowait(data)
        elif pt == b"\x5a\x05":
            ln = int.from_bytes(data[2:4], "big")
            self._ctrl_q.put_nowait(("lost", ln))
        elif pt == b"\x5a\x06":
            self._ctrl_q.put_nowait(("done", 0))
        elif pt == b"\x5a\x08":
            self._ctrl_q.put_nowait(("pause", 0))
        elif pt == b"\x5a\x02":
            self.battery = data[2]
            if data[3] and not self._no_paper_logged:
                self.log("⚠️ Нет бумаги!")
                self._no_paper_logged = True
            if data[5] and not self._overheat:
                self._overheat = True
                self.log("🔥 Перегрев! Ждём остывания...")
            if not data[5] and self._overheat:
                self._overheat = False
                self._no_paper_logged = False
                self.log("✅ Принтер остыл")

    async def auth(self):
        """Подписка + handshake"""
        await self.client.start_notify(
            NOTIFY_UUID, partial(Printer._on_notify, self))
        await self._write(pkt_hw())
        await asyncio.sleep(0.5)
        await self._write(pkt_challenge())
        await asyncio.wait_for(self._hs_q.get(), timeout=5)
        await self._write(pkt_response(self.mac))
        result = await asyncio.wait_for(self._hs_q.get(), timeout=5)
        if result[2] != 0x01:
            raise Exception("Handshake failed!")
        self.log(f"🤝 Подключено! 🔋{self.battery}%")

    def cancel(self):
        self._cancel = True

    async def print_lines(self, funny_lines, density=3, feed_after=50):
        await self._write(pkt_density(density))
        await asyncio.sleep(0.3)
        self._cancel = False
        self._flush_ctrl()

        all_lines = list(funny_lines)
        real_count = len(all_lines)
        if feed_after > 0:
            blank = bytes(96)
            for _ in range(feed_after // 2):
                all_lines.append(blank)

        total = len(all_lines)
        await self._write(pkt_print_event(total, end=False))
        await asyncio.sleep(0.1)

        cur = 0
        state = "SENDING"
        pause_count = 0
        max_done_wait = max(60, real_count * 0.5)

        while state != "DONE":
            if self._cancel:
                self.log("Печать прервана!")
                break

            if state == "PAUSED":
                try:
                    ev, val = await asyncio.wait_for(
                        self._ctrl_q.get(), timeout=90)
                except asyncio.TimeoutError:
                    self.log("Таймаут паузы (90с)")
                    break

                if ev == "done":
                    state = "DONE"
                    continue
                elif ev == "pause":
                    continue  # всё ещё на паузе
                elif ev == "lost":
                    pause_count += 1
                    # Даём принтеру реально отпечатать буфер
                    cooldown = min(8.0, 2.0 + pause_count * 0.5)
                    await asyncio.sleep(cooldown)
                    # Собираем все события за время cooldown
                    latest_lost = val
                    while True:
                        more = self._poll_ctrl()
                        if more is None:
                            break
                        if more[0] == "done":
                            state = "DONE"
                            break
                        elif more[0] == "lost":
                            latest_lost = more[1]
                        # pause игнорируем — уже отдохнули
                    if state == "DONE":
                        continue
                    cur = latest_lost
                    state = "SENDING"
                    if pause_count <= 3 or pause_count % 10 == 0:
                        self.log(f"▶ Строка {cur}/{total} "
                                 f"(пауз: {pause_count})")
                continue

            # === SENDING ===
            ev_data = self._poll_ctrl()
            if ev_data:
                ev, val = ev_data
                if ev == "done":
                    state = "DONE"
                    continue
                elif ev == "lost":
                    cur = val
                    continue
                elif ev == "pause":
                    state = "PAUSED"
                    if pause_count == 0:
                        self.log(f"⏸ Пауза ({cur}/{total})")
                    continue

            if cur < total:
                await self._write(pkt_print_line(cur, all_lines[cur]))
                cur += 1
                if self.on_progress and cur <= real_count:
                    self.on_progress(min(100, 100 * cur // real_count))
                await asyncio.sleep(0.025)
            else:
                try:
                    ev, val = await asyncio.wait_for(
                        self._ctrl_q.get(), timeout=max_done_wait)
                    if ev == "done":
                        state = "DONE"
                    elif ev == "lost":
                        cur = val
                    elif ev == "pause":
                        state = "PAUSED"
                except asyncio.TimeoutError:
                    self.log("Таймаут завершения")
                    break

        self._flush_ctrl()
        self._cancel = False
        await self._write(pkt_print_event(total, end=True))
        if state == "DONE":
            self.log("✅ Печать завершена!")
        else:
            self.log("⚠️ Печать завершена с ошибками")

    def _poll_ctrl(self):
        try:
            return self._ctrl_q.get_nowait()
        except asyncio.QueueEmpty:
            return None

    def _flush_ctrl(self):
        while not self._ctrl_q.empty():
            try:
                self._ctrl_q.get_nowait()
            except asyncio.QueueEmpty:
                break

    async def feed(self, pixels=100):
        n = max(1, pixels // 2)
        blank = bytes(96)
        await self._write(pkt_print_event(n, end=False))
        for i in range(n):
            await self._write(pkt_print_line(i, blank))
            await asyncio.sleep(0.02)
        await asyncio.sleep(0.5)
        await self._write(pkt_print_event(n, end=True))
        self.log(f"Промотка {pixels}px")

async def find_and_connect(
    on_log: Callable[[str], None] = print,
    on_progress: Callable[[int], None] | None = None,
    scan_retries: int = 5,
    connect_retries: int = 3,
) -> Printer | None:
    """Найти принтер → подключиться → авторизоваться"""

    # 1. Поиск
    address = None
    on_log("🔍 Ищем принтер...")
    for attempt in range(scan_retries):
        try:
            devices = await BleakScanner.discover(timeout=SCAN_TIMEOUT)
            for d in devices:
                if (d.address.upper() == PRINTER_MAC.upper()
                        or (d.name and PRINTER_NAME in (d.name or ""))):
                    address = d.address
                    break
        except Exception as e:
            on_log(f"  ⚠️ {e}")
        if address:
            break
        on_log(f"  Попытка {attempt + 1}/{scan_retries}...")

    if not address:
        on_log("❌ Принтер не найден!")
        return None

    on_log(f"📡 Найден: {address}")

    # 2. Подключение
    client = None
    for attempt in range(connect_retries):
        try:
            on_log(f"  Подключение ({attempt + 1}/{connect_retries})...")
            client = BleakClient(address, timeout=CONNECT_TIMEOUT)
            await client.connect()
            if client.is_connected:
                await asyncio.sleep(1)
                break
        except (asyncio.TimeoutError, asyncio.CancelledError):
            on_log("  BLE таймаут, повтор...")
            try:
                await client.disconnect()
            except Exception:
                pass
            await asyncio.sleep(3)
        except Exception as e:
            on_log(f"  ⚠️ {e}")
            try:
                if client:
                    await client.disconnect()
            except Exception:
                pass
            await asyncio.sleep(2)
    else:
        on_log("❌ Не удалось подключиться!")
        return None

    # 3. Авторизация
    printer = Printer(client, address, on_log, on_progress)
    await printer.auth()
    return printer