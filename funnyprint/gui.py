"""GUI приложение"""

import asyncio
import os
import threading
import tkinter as tk
from tkinter import ttk, filedialog

from PIL import Image, ImageTk

from funnyprint import (
    PRINTER_DPI, PRINTER_WIDTH, DEFAULT_DENSITY,
    DEFAULT_FEED_AFTER, SECRET_TEXT,
)
from funnyprint.imaging import (
    prepare_image, prepare_text, get_system_fonts,
    get_strip_info, DITHER_METHODS,
)
from funnyprint.printer import find_and_connect


class PrintButton(tk.Canvas):
    def __init__(self, parent, text="ПЕЧАТАТЬ", command=None, **kw):
        super().__init__(parent, height=52, highlightthickness=0,
                         cursor="hand2", **kw)
        self._cmd = command
        self._pct = 0
        self._enabled = True
        self._text = text
        self.bind("<Button-1>", self._click)
        self.bind("<Configure>", lambda e: self._draw())
        self._draw()

    def _draw(self):
        self.delete("all")
        w = max(self.winfo_width(), 50)
        h = max(self.winfo_height(), 40)
        bg = "#4CAF50" if self._enabled else "#9E9E9E"
        self.create_rectangle(0, 0, w, h, fill=bg, outline="")
        if 0 < self._pct <= 100:
            self.create_rectangle(0, 0, int(w * self._pct / 100), h,
                                  fill="#2E7D32", outline="")
        self.create_text(w // 2, h // 2, text=self._text,
                         font=("Arial", 14, "bold"), fill="white")

    def set_progress(self, pct):
        self._pct = max(0, min(100, pct))
        self._draw()

    def set_enabled(self, en):
        self._enabled = en
        self.config(cursor="hand2" if en else "arrow")
        self._draw()

    def _click(self, e):
        if self._enabled and self._cmd:
            self._cmd()


class App:
    def __init__(self):
        try:
            from tkinterdnd2 import TkinterDnD
            self.root = TkinterDnD.Tk()
            self._dnd_available = True
        except ImportError:
            self.root = tk.Tk()
            self._dnd_available = False
        self.root.title("FunnyPrint LX-D2")
        self.root.geometry("960x780")
        self.root.minsize(700, 500)

        self.printer = None
        self.connected = False
        self.busy = False
        self.image_path = None
        self.batch_paths = None
        self.current_lines = None
        self.current_preview = None
        self._preview_tk = None
        self._update_timer = None
        self._zoom = 1.0
        self._last_tab = -1

        self.system_fonts = get_system_fonts()
        self.font_names = list(self.system_fonts.keys())

        self._ble_loop = asyncio.new_event_loop()
        threading.Thread(
            target=self._ble_loop.run_forever, daemon=True).start()

        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _run_async(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self._ble_loop)

    def log(self, msg):
        self.root.after(0, self._log_write, msg)

    def _log_write(self, msg):
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, msg + "\n")
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)

    def _set_progress(self, pct):
        self.root.after(0, lambda: self.print_btn.set_progress(pct))

    def _set_status(self, on):
        self.connected = on
        def _u():
            if on:
                self.status_lbl.config(text="  Подключено", foreground="green")
                self.btn_connect.config(state=tk.DISABLED)
                self.btn_disconnect.config(state=tk.NORMAL)
            else:
                self.status_lbl.config(text="  Отключено", foreground="red")
                self.btn_connect.config(state=tk.NORMAL)
                self.btn_disconnect.config(state=tk.DISABLED)
                self.battery_lbl.config(text="")
        self.root.after(0, _u)

    def _set_busy(self, busy):
        self.busy = busy
        def _u():
            self.print_btn.set_enabled(not busy)
            st = tk.DISABLED if busy else tk.NORMAL
            self.btn_feed.config(state=st)
            self.btn_cancel.config(state=tk.NORMAL if busy else tk.DISABLED)
            if not busy:
                self.root.after(1500, lambda: self.print_btn.set_progress(0))
        self.root.after(0, _u)

    def _build_ui(self):
        # ── Подключение ──
        conn = ttk.LabelFrame(self.root, text="Подключение", padding=5)
        conn.pack(fill=tk.X, padx=5, pady=(5, 2))

        self.btn_connect = ttk.Button(conn, text="Подключить",
                                      command=self.on_connect)
        self.btn_connect.pack(side=tk.LEFT, padx=2)
        self.btn_disconnect = ttk.Button(conn, text="Отключить",
                                         command=self.on_disconnect,
                                         state=tk.DISABLED)
        self.btn_disconnect.pack(side=tk.LEFT, padx=2)
        self.status_lbl = ttk.Label(conn, text="  Отключено",
                                    foreground="red",
                                    font=("Arial", 10, "bold"))
        self.status_lbl.pack(side=tk.LEFT, padx=10)
        self.battery_lbl = ttk.Label(conn, text="", font=("Arial", 10))
        self.battery_lbl.pack(side=tk.RIGHT)

        # ── Главный PanedWindow (верх/лог) ──
        main_pane = tk.PanedWindow(
            self.root, orient=tk.VERTICAL,
            sashwidth=8, sashrelief=tk.RAISED, bg="#b0b0b0",
            sashcursor="sb_v_double_arrow")
        main_pane.pack(fill=tk.BOTH, expand=True, padx=5, pady=2)

        upper = tk.Frame(main_pane)
        main_pane.add(upper, minsize=250)

        # ── Горизонтальный PanedWindow (лево/право) ──
        h_pane = tk.PanedWindow(
            upper, orient=tk.HORIZONTAL,
            sashwidth=8, sashrelief=tk.RAISED, bg="#b0b0b0",
            sashcursor="sb_h_double_arrow")
        h_pane.pack(fill=tk.BOTH, expand=True)

        # ══════ ЛЕВАЯ ПАНЕЛЬ (скроллируемая) ══════
        left_outer = tk.Frame(h_pane)
        h_pane.add(left_outer, minsize=250, width=340)

        left_canvas = tk.Canvas(left_outer, highlightthickness=0)
        left_sb = ttk.Scrollbar(left_outer, orient=tk.VERTICAL,
                                command=left_canvas.yview)
        left = ttk.Frame(left_canvas)
        left.bind("<Configure>", lambda e:
            left_canvas.configure(scrollregion=left_canvas.bbox("all")))
        left_canvas.create_window((0, 0), window=left, anchor="nw",
                                  tags="inner")
        left_canvas.configure(yscrollcommand=left_sb.set)
        left_sb.pack(side=tk.RIGHT, fill=tk.Y)
        left_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Ширина внутреннего фрейма = ширина канваса
        def _resize_inner(e):
            left_canvas.itemconfig("inner", width=e.width)
        left_canvas.bind("<Configure>", _resize_inner)

        # Колёсико внутри левой панели — всегда скроллит панель
        def _left_wheel(e):
            left_canvas.yview_scroll(-(e.delta // 120), "units")
            return "break"  # блокируем дальнейшую обработку
        left_canvas.bind("<MouseWheel>", _left_wheel)
        left.bind("<MouseWheel>", _left_wheel)

        def _bind_wheel_recursive(widget):
            # Spinbox, Combobox, Scale — блокируем их собственный скролл
            widget.bind("<MouseWheel>", _left_wheel)
            for child in widget.winfo_children():
                if not isinstance(child, (tk.Text, tk.Listbox)):
                    _bind_wheel_recursive(child)
        self.root.after(1000, lambda: _bind_wheel_recursive(left))

        # Вкладки (растягиваются!)
        self.tabs = ttk.Notebook(left)
        self.tabs.pack(fill=tk.BOTH, expand=True, padx=2, pady=(2, 0))
        self.tabs.bind("<<NotebookTabChanged>>", self._on_tab_change)

        # -- Картинка --
        img_tab = ttk.Frame(self.tabs, padding=8)
        self.tabs.add(img_tab, text="   Картинка   ")
        ttk.Button(img_tab, text="Выбрать файл",
                   command=self.on_load_image).pack(fill=tk.X, pady=5)
        self.file_lbl = ttk.Label(img_tab, text="Файл не выбран",
                                  wraplength=260, foreground="gray")
        self.file_lbl.pack(pady=2)
        ttk.Button(img_tab, text="Пакетная печать (несколько файлов)",
                   command=self.on_batch).pack(fill=tk.X, pady=5)

        # -- PDF --
        pdf_tab = ttk.Frame(self.tabs, padding=8)
        self.tabs.add(pdf_tab, text="   PDF   ")
        ttk.Button(pdf_tab, text="Выбрать PDF",
                   command=self.on_load_pdf).pack(fill=tk.X, pady=5)
        self.pdf_lbl = ttk.Label(pdf_tab, text="PDF не выбран",
                                 wraplength=260, foreground="gray")
        self.pdf_lbl.pack(pady=2)

        pg_f = ttk.Frame(pdf_tab)
        pg_f.pack(fill=tk.X, pady=5)
        ttk.Label(pg_f, text="Страницы:").pack(side=tk.LEFT)
        self.pdf_range_var = tk.StringVar(value="1")
        pdf_range_entry = ttk.Entry(pg_f, textvariable=self.pdf_range_var,
                                    font=("Arial", 11))
        pdf_range_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        pdf_range_entry.bind("<KeyRelease>", lambda e: self._schedule())

        self.pdf_pages_lbl = ttk.Label(pdf_tab, text="",
                                       foreground="gray", font=("Arial", 8))
        self.pdf_pages_lbl.pack(anchor=tk.W)
        ttk.Label(pdf_tab,
                  text='Примеры: "1", "1-3", "1,3,5", "all"',
                  foreground="gray", font=("Arial", 8)).pack(anchor=tk.W)

        self.pdf_path = None
        self.pdf_page_count = 0

        # -- Rich Text --
        rt_tab = ttk.Frame(self.tabs, padding=8)
        self.tabs.add(rt_tab, text="   Rich Text   ")

        self.rt_widget = tk.Text(
            rt_tab, height=5, width=30, wrap=tk.WORD,
            font=("Consolas", 10), undo=True, maxundo=50)
        self.rt_widget.pack(fill=tk.BOTH, expand=True, pady=(0, 4))
        self.rt_widget.insert("1.0",
            "<b>Жирный</b> и обычный\n"
            "<i>Курсив</i> и <u>подчёркнутый</u>\n"
            "[] Задача\n[x] Выполнена")
        self.rt_widget.bind("<KeyRelease>", lambda e: self._schedule())

        # Панель кнопок форматирования
        rt_btn_frame = ttk.Frame(rt_tab)
        rt_btn_frame.pack(fill=tk.X, pady=2)

        rt_buttons = [
            ("B", "b", True),
            ("I", "i", True),
            ("U", "u", True),
            ("S", "s", True),
            ("x²", "sup", True),
            ("x₂", "sub", True),
            ("Aa", "size:24", True),
        ]
        for text, tag, paired in rt_buttons:
            btn = ttk.Button(rt_btn_frame, text=text, width=3,
                command=lambda t=tag, p=paired: self._rt_insert_tag(t, p))
            btn.pack(side=tk.LEFT, padx=1)

        # Выравнивание
        rt_align_frame = ttk.Frame(rt_tab)
        rt_align_frame.pack(fill=tk.X, pady=2)
        for label, tag in [("Лево", "left"), ("Центр", "center"),
                           ("Право", "right")]:
            ttk.Button(rt_align_frame, text=label, width=6,
                command=lambda t=tag: self._rt_insert_tag(t, True)
            ).pack(side=tk.LEFT, padx=1)

        # Маркеры списков
        rt_list_frame = ttk.Frame(rt_tab)
        rt_list_frame.pack(fill=tk.X, pady=2)
        markers = [
            ("☐", "[] "), ("☑", "[x] "), ("•", "• "),
            ("–", "- "), ("▶", "> "), ("★", "★ "),
            ("○", "○ "), ("1.", "1. "),
        ]
        for label, marker in markers:
            ttk.Button(rt_list_frame, text=label, width=3,
                command=lambda m=marker: self._rt_insert_marker(m)
            ).pack(side=tk.LEFT, padx=1)

        # Шрифт для Rich Text
        rt_font_f = ttk.Frame(rt_tab)
        rt_font_f.pack(fill=tk.X, pady=2)
        ttk.Label(rt_font_f, text="Шрифт:").pack(side=tk.LEFT)
        self.rt_font_combo = ttk.Combobox(
            rt_font_f, values=self.font_names,
            state="readonly", width=18)
        self.rt_font_combo.pack(side=tk.LEFT, padx=5)
        for i, name in enumerate(self.font_names):
            if "arial" in name.lower() and "bold" not in name.lower():
                self.rt_font_combo.current(i)
                break
        self.rt_font_combo.bind("<<ComboboxSelected>>",
                                lambda e: self._schedule())

        rt_size_f = ttk.Frame(rt_tab)
        rt_size_f.pack(fill=tk.X, pady=2)
        ttk.Label(rt_size_f, text="Базовый размер:").pack(side=tk.LEFT)
        self.rt_font_size_var = tk.IntVar(value=24)
        ttk.Spinbox(rt_size_f, from_=8, to=96, width=4,
                    textvariable=self.rt_font_size_var,
                    command=self._schedule).pack(side=tk.LEFT, padx=5)

        ttk.Label(rt_tab,
                  text="Подсказка: выдели текст и нажми кнопку\n"
                  "для применения тега",
                  foreground="gray", font=("Arial", 8),
                  justify=tk.LEFT).pack(anchor=tk.W, pady=2)

        # -- Текст --
        txt_tab = ttk.Frame(self.tabs, padding=8)
        self.tabs.add(txt_tab, text="   Текст   ")

        self.text_widget = tk.Text(
            txt_tab, height=5, width=30, wrap=tk.WORD,
            font=("Arial", 11), undo=True, maxundo=50)
        self.text_widget.pack(fill=tk.BOTH, expand=True, pady=(0, 4))
        self.text_widget.insert("1.0", "Привет мир!")
        self.text_widget.bind("<KeyRelease>", lambda e: self._schedule())

        ff = ttk.Frame(txt_tab)
        ff.pack(fill=tk.X, pady=2)
        ttk.Label(ff, text="Шрифт:").pack(side=tk.LEFT)
        self._font_search_var = tk.StringVar()
        self._font_search_var.trace_add("write", self._filter_fonts)
        ttk.Entry(ff, textvariable=self._font_search_var).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=5)

        flf = ttk.Frame(txt_tab)
        flf.pack(fill=tk.X, pady=(0, 4))
        self.font_listbox = tk.Listbox(flf, height=4, exportselection=False)
        fls = ttk.Scrollbar(flf, command=self.font_listbox.yview)
        self.font_listbox.configure(yscrollcommand=fls.set)
        fls.pack(side=tk.RIGHT, fill=tk.Y)
        self.font_listbox.pack(fill=tk.X)
        for name in self.font_names:
            self.font_listbox.insert(tk.END, name)
        for i, name in enumerate(self.font_names):
            if "arial" in name.lower() and "bold" not in name.lower():
                self.font_listbox.selection_set(i)
                self.font_listbox.see(i)
                break
        self.font_listbox.bind("<<ListboxSelect>>",
                               lambda e: self._schedule())

        sf = ttk.Frame(txt_tab)
        sf.pack(fill=tk.X, pady=2)
        ttk.Label(sf, text="Размер:").pack(side=tk.LEFT)
        self.font_size_var = tk.IntVar(value=24)
        ttk.Spinbox(sf, from_=8, to=96, width=4,
                    textvariable=self.font_size_var,
                    command=self._schedule).pack(side=tk.LEFT, padx=5)

        bi = ttk.Frame(txt_tab)
        bi.pack(fill=tk.X, pady=2)
        self.bold_var = tk.BooleanVar()
        self.italic_var = tk.BooleanVar()
        ttk.Checkbutton(bi, text="Жирный", variable=self.bold_var,
                        command=self._schedule).pack(side=tk.LEFT, padx=5)
        ttk.Checkbutton(bi, text="Курсив", variable=self.italic_var,
                        command=self._schedule).pack(side=tk.LEFT, padx=5)

        al = ttk.Frame(txt_tab)
        al.pack(fill=tk.X, pady=2)
        ttk.Label(al, text="Выравн:").pack(side=tk.LEFT)
        self.align_var = tk.StringVar(value="left")
        for val, txt in [("left", " Лево "), ("center", " Центр "),
                         ("right", " Право ")]:
            ttk.Radiobutton(al, text=txt, value=val,
                            variable=self.align_var,
                            command=self._schedule).pack(side=tk.LEFT, padx=2)

        stf = ttk.Frame(txt_tab)
        stf.pack(fill=tk.X, pady=2)
        self.strip_var = tk.BooleanVar()
        ttk.Checkbutton(stf, text="Лента (90)",
                        variable=self.strip_var,
                        command=self._on_strip_toggle).pack(side=tk.LEFT)
        self.strip_info_lbl = ttk.Label(stf, text="", foreground="gray")
        self.strip_info_lbl.pack(side=tk.LEFT, padx=10)

        # -- QR --
        qr_tab = ttk.Frame(self.tabs, padding=8)
        self.tabs.add(qr_tab, text="   QR   ")

        ttk.Label(qr_tab, text="Данные:").pack(anchor=tk.W)
        self.qr_entry = tk.Text(qr_tab, height=3, width=30,
                                wrap=tk.WORD, font=("Arial", 11))
        self.qr_entry.pack(fill=tk.X, pady=(0, 5))
        self.qr_entry.insert("1.0", "https://example.com")
        self.qr_entry.bind("<KeyRelease>", lambda e: self._schedule())
        
        self.qr_text_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(qr_tab, text="Добавить текст под QR",
                        variable=self.qr_text_var,
                        command=self._schedule).pack(anchor=tk.W, pady=2)

        # -- Barcode --
        bc_tab = ttk.Frame(self.tabs, padding=8)
        self.tabs.add(bc_tab, text="   Barcode   ")

        ttk.Label(bc_tab, text="Данные:").pack(anchor=tk.W)
        self.bc_entry = ttk.Entry(bc_tab, font=("Arial", 11))
        self.bc_entry.pack(fill=tk.X, pady=(0, 5))
        self.bc_entry.insert(0, "123456789012")
        self.bc_entry.bind("<KeyRelease>", lambda e: self._schedule())
        
        bc_type_f = ttk.Frame(bc_tab)
        bc_type_f.pack(fill=tk.X, pady=2)
        ttk.Label(bc_type_f, text="Тип:").pack(side=tk.LEFT)
        self.bc_type_var = tk.StringVar(value="code128")
        from funnyprint.imaging import BARCODE_TYPES
        ttk.Combobox(bc_type_f, values=BARCODE_TYPES,
                     textvariable=self.bc_type_var,
                     state="readonly", width=12).pack(side=tk.LEFT, padx=5)
        self.bc_type_var.trace_add("write", lambda *a: self._schedule())

        self.bc_text_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(bc_tab, text="Показать текст",
                        variable=self.bc_text_var,
                        command=self._schedule).pack(anchor=tk.W, pady=2)

        # ── Настройки (под вкладками, не внутри) ──
        sett = ttk.LabelFrame(left, text="Настройки печати", padding=5)
        sett.pack(fill=tk.X, padx=2, pady=2)

        self._slider(sett, "Яркость (принтер)", 0, 7,
                     DEFAULT_DENSITY, "density_var", is_int=True)
        self._slider(sett, "Яркость (фильтр)", -100, 100, 0, "bright_var")
        self._slider(sett, "Контраст", -100, 100, 0, "contrast_var")
        self._slider(sett, "Резкость", -100, 100, 0, "sharp_var")

        # Художественный фильтр
        af = ttk.Frame(sett)
        af.pack(fill=tk.X, pady=2)
        ttk.Label(af, text="Фильтр:").pack(side=tk.LEFT)
        self.artistic_var = tk.StringVar(value="Нет")
        from funnyprint.imaging import ARTISTIC_FILTERS
        ttk.Combobox(af, values=ARTISTIC_FILTERS,
                     textvariable=self.artistic_var,
                     state="readonly", width=18).pack(side=tk.LEFT, padx=5)
        self.artistic_var.trace_add("write", lambda *a: self._schedule())
        
        # Рамка
        brf = ttk.Frame(sett)
        brf.pack(fill=tk.X, pady=2)
        ttk.Label(brf, text="Рамка:").pack(side=tk.LEFT)
        self.border_var = tk.StringVar(value="Нет")
        from funnyprint.borders import get_border_names
        ttk.Combobox(brf, values=get_border_names(),
                     textvariable=self.border_var,
                     state="readonly", width=18).pack(side=tk.LEFT, padx=5)
        self.border_var.trace_add("write", lambda *a: self._schedule())

        # Дизеринг
        df = ttk.Frame(sett)
        df.pack(fill=tk.X, pady=2)
        ttk.Label(df, text="Дизеринг:").pack(side=tk.LEFT)
        self.dither_var = tk.StringVar(value="Floyd-Steinberg")
        ttk.Combobox(df, values=DITHER_METHODS, textvariable=self.dither_var,
                     state="readonly", width=15).pack(side=tk.LEFT, padx=5)
        self.dither_var.trace_add("write", lambda *a: self._schedule())

        # Поворот
        rot_f = ttk.Frame(sett)
        rot_f.pack(fill=tk.X, pady=1)
        ttk.Label(rot_f, text="Поворот:").pack(side=tk.LEFT)
        self.rotation_var = tk.IntVar(value=0)
        self._rot_double = tk.DoubleVar(value=0)

        rot_spin = ttk.Spinbox(rot_f, from_=0, to=359, width=4, increment=1,
                               textvariable=self.rotation_var,
                               command=self._schedule)
        rot_spin.pack(side=tk.RIGHT)
        rot_spin.bind("<KeyRelease>", lambda e: self._schedule())
        ttk.Label(rot_f, text="°").pack(side=tk.RIGHT)

        def _rot_scale_changed(v):
            self.rotation_var.set(int(float(v)))
            self._schedule()

        def _rot_var_changed(*a):
            try:
                val = self.rotation_var.get()
                self._rot_double.set(float(val))
            except (ValueError, tk.TclError):
                pass

        self.rotation_var.trace_add("write", _rot_var_changed)

        ttk.Scale(rot_f, from_=0, to=359, variable=self._rot_double,
                  orient=tk.HORIZONTAL,
                  command=_rot_scale_changed
                  ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)

        pf = ttk.Frame(sett)
        pf.pack(fill=tk.X, pady=2)
        ttk.Label(pf, text="Промотка после:").pack(side=tk.LEFT)
        self.feed_var = tk.IntVar(value=DEFAULT_FEED_AFTER)
        feed_spin = ttk.Spinbox(pf, from_=0, to=500, width=5,
                                textvariable=self.feed_var,
                                command=self._schedule)
        feed_spin.pack(side=tk.LEFT, padx=5)
        feed_spin.bind("<KeyRelease>", lambda e: self._schedule())
        ttk.Label(pf, text="px").pack(side=tk.LEFT)
        ttk.Label(sett, text="(принтер также делает свою промотку\n"
                  "после каждой печати для отрыва)",
                  foreground="gray", font=("Arial", 8)).pack(anchor=tk.W)

        # ── Кнопки ──
        bf = ttk.Frame(left)
        bf.pack(fill=tk.X, padx=2, pady=2)

        self.print_btn = PrintButton(bf, text="ПЕЧАТАТЬ",
                                     command=self.on_print)
        self.print_btn.pack(fill=tk.X, pady=(0, 4))

        self.btn_feed = ttk.Button(bf, text="Промотать бумагу",
                                   command=self.on_feed)
        self.btn_feed.pack(fill=tk.X, pady=2)

        self.btn_cancel = tk.Button(
            bf, text="ПРЕРВАТЬ", font=("Arial", 10, "bold"),
            bg="#f44336", fg="white", activebackground="#c62828",
            activeforeground="white", relief=tk.FLAT,
            cursor="hand2", command=self._on_cancel,
            state=tk.DISABLED)
        self.btn_cancel.pack(fill=tk.X, pady=2)

        self.will_print_lbl = ttk.Label(
            left, text="", foreground="#555", wraplength=300)
        self.will_print_lbl.pack(pady=2, padx=2)

        # ══════ ПРАВАЯ ПАНЕЛЬ ══════
        right = ttk.LabelFrame(h_pane, text="Предпросмотр", padding=5)
        h_pane.add(right, minsize=250)

        zb = ttk.Frame(right)
        zb.pack(fill=tk.X)
        ttk.Button(zb, text=" - ", width=3,
                   command=self._zoom_out).pack(side=tk.LEFT)
        self.zoom_lbl = ttk.Label(zb, text="100%")
        self.zoom_lbl.pack(side=tk.LEFT, padx=5)
        ttk.Button(zb, text=" + ", width=3,
                   command=self._zoom_in).pack(side=tk.LEFT)
        ttk.Button(zb, text="1:1", width=3,
                   command=self._zoom_reset).pack(side=tk.LEFT, padx=5)

        cf = ttk.Frame(right)
        cf.pack(fill=tk.BOTH, expand=True)
        self.canvas = tk.Canvas(cf, bg="#e8e8e8", highlightthickness=1,
                                highlightbackground="#aaa")
        vs = ttk.Scrollbar(cf, orient=tk.VERTICAL, command=self.canvas.yview)
        hs = ttk.Scrollbar(cf, orient=tk.HORIZONTAL,
                           command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)
        vs.pack(side=tk.RIGHT, fill=tk.Y)
        hs.pack(side=tk.BOTTOM, fill=tk.X)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.size_lbl = ttk.Label(right, text="", foreground="gray")
        self.size_lbl.pack()

        # ══════ ЛОГ ══════
        log_frame = ttk.LabelFrame(
            main_pane, text="Лог  (тяни серую полосу)", padding=2)
        main_pane.add(log_frame, minsize=50)

        li = tk.Frame(log_frame)
        li.pack(fill=tk.BOTH, expand=True)
        self.log_text = tk.Text(li, height=3, wrap=tk.WORD,
                                state=tk.DISABLED, font=("Consolas", 9))
        ls = ttk.Scrollbar(li, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=ls.set)
        ls.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.pack(fill=tk.BOTH, expand=True)

        self._log_write("Готов. Нажми Подключить.")

        # ── Секрет ──
        secret = tk.Label(self.root, text=" \u2665 ", font=("Arial", 11),
                          fg="#d0d0d0", bg="#f0f0f0", cursor="hand2")
        secret.place(relx=1.0, rely=1.0, anchor="se", x=-4, y=-2)
        secret.bind("<Button-1>", self._on_secret)
        secret.bind("<Enter>", lambda e: secret.config(fg="#e06060"))
        secret.bind("<Leave>", lambda e: secret.config(fg="#d0d0d0"))

        # ── Глобальное колёсико ──
        self.root.bind_all("<MouseWheel>", self._on_global_wheel)

        # ── Горячие клавиши для любой раскладки ──
        self.root.bind_all("<Key>", self._on_global_key)
        # Горячие клавиши приложения
        self.root.bind("<Control-p>", lambda e: self.on_print())
        self.root.bind("<Control-P>", lambda e: self.on_print())
        self.root.bind("<Control-o>", lambda e: self._hotkey_open())
        self.root.bind("<Control-O>", lambda e: self._hotkey_open())

        self.root.after(500, self._update_preview)
        # Drag & Drop
        if self._dnd_available:
            from tkinterdnd2 import DND_FILES
            self.root.drop_target_register(DND_FILES)
            self.root.dnd_bind('<<Drop>>', self._on_drop)

    def _slider(self, parent, label, from_, to, default, var_name,
                is_int=False):
        f = ttk.Frame(parent)
        f.pack(fill=tk.X, pady=1)
        ttk.Label(f, text=label + ":").pack(side=tk.LEFT)
        var = tk.IntVar(value=default) if is_int else tk.DoubleVar(
            value=default)
        setattr(self, var_name, var)
        lbl = ttk.Label(f, text=str(default), width=5)
        lbl.pack(side=tk.RIGHT)

        def _ch(v):
            lbl.config(text=str(int(float(v))))
            self._schedule()
        ttk.Scale(f, from_=from_, to=to, variable=var,
                  orient=tk.HORIZONTAL, command=_ch
                  ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)

    # ══════════════════════════════════
    #  Колёсико + Ctrl+Key
    # ══════════════════════════════════
    def _is_over(self, widget, x, y):
        try:
            wx, wy = widget.winfo_rootx(), widget.winfo_rooty()
            return (wx <= x <= wx + widget.winfo_width()
                    and wy <= y <= wy + widget.winfo_height())
        except Exception:
            return False

    def _on_global_key(self, event):
        """Обработка Ctrl+клавиша в любой раскладке"""
        if not (event.state & 0x4):  # Ctrl не нажат
            return

        ch = event.char
        w = event.widget

        # Ctrl+A — выделить всё
        if ch == '\x01':
            if isinstance(w, (tk.Text,)):
                w.tag_add("sel", "1.0", "end")
                return "break"
            if isinstance(w, (ttk.Entry, tk.Entry)):
                w.selection_range(0, tk.END)
                return "break"

        # Ctrl+C — копировать
        if ch == '\x03':
            if isinstance(w, (tk.Text,)):
                try:
                    w.event_generate("<<Copy>>")
                except Exception:
                    pass
                return "break"
            if isinstance(w, (ttk.Entry, tk.Entry)):
                try:
                    w.event_generate("<<Copy>>")
                except Exception:
                    pass
                return "break"

        # Ctrl+V — вставить
        if ch == '\x16':
            if isinstance(w, (tk.Text,)):
                try:
                    w.event_generate("<<Paste>>")
                except Exception:
                    pass
                return "break"
            if isinstance(w, (ttk.Entry, tk.Entry)):
                try:
                    w.event_generate("<<Paste>>")
                except Exception:
                    pass
                return "break"

        # Ctrl+X — вырезать
        if ch == '\x18':
            if isinstance(w, (tk.Text,)):
                try:
                    w.event_generate("<<Cut>>")
                except Exception:
                    pass
                return "break"
            if isinstance(w, (ttk.Entry, tk.Entry)):
                try:
                    w.event_generate("<<Cut>>")
                except Exception:
                    pass
                return "break"

        # Ctrl+Z — отмена
        if ch == '\x1a':
            if isinstance(w, tk.Text) and w.cget("undo"):
                try:
                    w.edit_undo()
                except Exception:
                    pass
                return "break"

        # Ctrl+Y — повтор
        if ch == '\x19':
            if isinstance(w, tk.Text) and w.cget("undo"):
                try:
                    w.edit_redo()
                except Exception:
                    pass
                return "break"
            
        # Ctrl+P - печать
        if ch == '\x10':
            self.on_print()
            return "break"

        # Ctrl+O - открыть файл
        if ch == '\x0f':
            self._hotkey_open()
            return "break"

    def _on_global_wheel(self, event):
        if isinstance(event.widget, (tk.Text, tk.Listbox)):
            return
        x, y = event.x_root, event.y_root
        d = -(event.delta // 120)
        if self._is_over(self.canvas, x, y):
            if event.state & 0x4:
                self._zoom_in() if event.delta > 0 else self._zoom_out()
            elif event.state & 0x1:
                self.canvas.xview_scroll(d, "units")
            else:
                self.canvas.yview_scroll(d, "units")
            return "break"

    # ══════════════════════════════════
    #  Предпросмотр
    # ══════════════════════════════════
    def _schedule(self):
        if self._update_timer:
            self.root.after_cancel(self._update_timer)
        self._update_timer = self.root.after(300, self._update_preview)

    def _get_tab(self):
        try:
            return self.tabs.index(self.tabs.select())
        except Exception:
            return 0

    def _update_preview(self):
        self._update_timer = None
        tab = self._get_tab()
        self._last_tab = tab
        flt = self._get_filters()
        prep_flt = self._get_prepare_filters()
        feed = self.feed_var.get()
        try:
            if tab == 0:  # Картинка
                if self.batch_paths:
                    self._update_batch_preview()
                    return
                if not self.image_path:
                    self.canvas.delete("all")
                    self.size_lbl.config(text="")
                    self.current_lines = None
                    self.will_print_lbl.config(
                        text="Напечатается: [выбери картинку]")
                    return
                lines, preview = prepare_image(self.image_path, **prep_flt)
                self.will_print_lbl.config(
                    text=f"Напечатается: {os.path.basename(self.image_path)}")

            elif tab == 1:  # PDF
                if not self.pdf_path:
                    self.canvas.delete("all")
                    self.size_lbl.config(text="")
                    self.current_lines = None
                    self.will_print_lbl.config(
                        text="Напечатается: [выбери PDF]")
                    return
                range_str = self.pdf_range_var.get().strip()
                try:
                    pages = self._parse_page_range(
                        range_str, self.pdf_page_count)
                except (ValueError, AttributeError):
                    pages = [0]
                if not pages:
                    pages = [0]
                if len(pages) == 1:
                    from funnyprint.imaging import prepare_pdf_page
                    lines, preview = prepare_pdf_page(
                        self.pdf_path, page_num=pages[0], **prep_flt)
                    preview = add_feed_preview(preview, feed)
                else:
                    from funnyprint.imaging import prepare_batch_pdf
                    lines, preview = prepare_batch_pdf(
                        self.pdf_path, pages,
                        feed_between=feed, **prep_flt)
                self.will_print_lbl.config(
                    text=f"Напечатается: {os.path.basename(self.pdf_path)}"
                         f" ({len(pages)} стр.)")

            elif tab == 2:  # Rich Text
                rt = self.rt_widget.get("1.0", tk.END).strip()
                if not rt:
                    self.canvas.delete("all")
                    self.size_lbl.config(text="")
                    self.current_lines = None
                    self.will_print_lbl.config(
                        text="Напечатается: [введи rich text]")
                    return
                from funnyprint.richtext import render_rich_text, TextStyle
                fn = self.rt_font_combo.get() or self.font_names[0]
                fp = self.system_fonts.get(fn)
                rt_style = TextStyle(
                    font_path=fp,
                    font_size=self.rt_font_size_var.get(),
                    align="left")
                img = render_rich_text(rt, rt_style)
                from funnyprint.imaging import (
                    apply_filters, dither_image, pil_to_funny_lines,
                    _trim_whitespace, _fit_to_printer)
                img = apply_filters(img,
                    brightness=flt["brightness"],
                    contrast=flt["contrast"],
                    sharpness=flt["sharpness"])
                from funnyprint.imaging import apply_artistic_filter
                img = apply_artistic_filter(img, flt.get("artistic", "Нет"))
                border = flt.get("border", "Нет")
                if border != "Нет":
                    from funnyprint.borders import apply_border
                    img = apply_border(img, border)
                    img = _fit_to_printer(img)
                rotation = flt["rotation"]
                if rotation:
                    from funnyprint.imaging import _rotate_and_fit
                    img = _rotate_and_fit(img, rotation)
                else:
                    img = _trim_whitespace(img)
                    img = _fit_to_printer(img)
                gray = img.convert("L")
                preview = dither_image(gray, flt["dither"])
                lines = pil_to_funny_lines(preview)
                self.will_print_lbl.config(
                    text=f"Напечатается: rich text [{fn}]")

            elif tab == 3:  # Текст
                text = self.text_widget.get("1.0", tk.END).strip()
                if not text:
                    self.canvas.delete("all")
                    self.size_lbl.config(text="")
                    self.current_lines = None
                    self.will_print_lbl.config(
                        text="Напечатается: [введи текст]")
                    return
                sel = self.font_listbox.curselection()
                fn = (self.font_listbox.get(sel[0])
                      if sel else self.font_names[0])
                fp = self.system_fonts.get(fn)
                lines, preview = prepare_text(
                    text, font_path=fp,
                    font_size=self.font_size_var.get(),
                    bold=self.bold_var.get(),
                    italic=self.italic_var.get(),
                    align=self.align_var.get(),
                    strip_mode=self.strip_var.get(), **prep_flt)
                mode = " (лента)" if self.strip_var.get() else ""
                self.will_print_lbl.config(
                    text=f"Напечатается: текст [{fn}]{mode}")

            elif tab == 4:  # QR
                data = self.qr_entry.get("1.0", tk.END).strip()
                if not data:
                    self.canvas.delete("all")
                    self.size_lbl.config(text="")
                    self.current_lines = None
                    self.will_print_lbl.config(
                        text="Напечатается: [введи данные QR]")
                    return
                from funnyprint.imaging import prepare_qr
                lines, preview = prepare_qr(
                    data, add_text=self.qr_text_var.get(), **prep_flt)
                self.will_print_lbl.config(text="Напечатается: QR-код")

            elif tab == 5:  # Barcode
                data = self.bc_entry.get().strip()
                if not data:
                    self.canvas.delete("all")
                    self.size_lbl.config(text="")
                    self.current_lines = None
                    self.will_print_lbl.config(
                        text="Напечатается: [введи данные штрих-кода]")
                    return
                from funnyprint.imaging import prepare_barcode
                lines, preview = prepare_barcode(
                    data, barcode_type=self.bc_type_var.get(),
                    add_text=self.bc_text_var.get(), **prep_flt)
                self.will_print_lbl.config(text="Напечатается: штрих-код")

            else:
                return

            self.current_lines = lines
            from funnyprint.imaging import add_feed_preview
            preview_with_feed = add_feed_preview(preview, feed)
            self.current_preview = preview_with_feed
            self._show_preview(preview_with_feed)

        except ValueError as e:
            self.log(f"Ошибка данных: {e}")
            self.canvas.delete("all")
            self.current_lines = None
        except Exception as e:
            self.log(f"Ошибка предпросмотра: {e}")

    def _show_preview(self, pil_img):
        if not pil_img:
            return
        w, h = pil_img.size
        zw, zh = max(1, int(w * self._zoom)), max(1, int(h * self._zoom))
        display = pil_img.convert("RGB").resize((zw, zh), Image.NEAREST)
        self._preview_tk = ImageTk.PhotoImage(display)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self._preview_tk)
        self.canvas.configure(scrollregion=(0, 0, zw, zh))
        mm_w = w / PRINTER_DPI * 25.4
        mm_h = h / PRINTER_DPI * 25.4
        self.size_lbl.config(
            text=f"{w}x{h}px | {mm_w:.0f}x{mm_h:.0f}mm | "
                 f"Zoom {int(self._zoom * 100)}%")

    def _zoom_in(self):
        self._zoom = min(10.0, self._zoom * 1.5)
        self._refresh_zoom()

    def _zoom_out(self):
        self._zoom = max(0.25, self._zoom / 1.5)
        self._refresh_zoom()

    def _zoom_reset(self):
        self._zoom = 1.0
        self._refresh_zoom()

    def _refresh_zoom(self):
        self.zoom_lbl.config(text=f"{int(self._zoom * 100)}%")
        if self.current_preview:
            self._show_preview(self.current_preview)

    def _on_tab_change(self, event=None):
        if self._update_timer:
            self.root.after_cancel(self._update_timer)
        self._update_timer = self.root.after(200, self._update_preview)

    def _on_strip_toggle(self):
        if self.strip_var.get():
            self.strip_info_lbl.config(
                text=f"(влезет {get_strip_info(self.font_size_var.get())} строк)")
        else:
            self.strip_info_lbl.config(text="")
        self._schedule()

    def _filter_fonts(self, *args):
        q = self._font_search_var.get().lower()
        self.font_listbox.delete(0, tk.END)
        for name in self.font_names:
            if q in name.lower():
                self.font_listbox.insert(tk.END, name)

    def _on_drop(self, event):
        path = event.data.strip('{}').strip('"')
        ext = os.path.splitext(path)[1].lower()

        if ext == ".pdf":
            from funnyprint.imaging import get_pdf_page_count
            self.pdf_path = path
            self.pdf_page_count = get_pdf_page_count(path)
            self.pdf_lbl.config(
                text=os.path.basename(path), foreground="black")
            self.pdf_pages_lbl.config(
                text=f"Всего страниц: {self.pdf_page_count}")
            self.pdf_range_var.set(
                "1" if self.pdf_page_count == 1 else "all")
            self.tabs.select(1)
            self.log(f"PDF (drop): {os.path.basename(path)}")

        elif ext in (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"):
            self.image_path = path
            self.file_lbl.config(
                text=os.path.basename(path), foreground="black")
            self.tabs.select(0)  # Image tab
            self.log(f"Картинка (drop): {os.path.basename(path)}")

        self._update_preview()

    def on_load_image(self):
        path = filedialog.askopenfilename(
            title="Выбери картинку",
            filetypes=[("Картинки", "*.png *.jpg *.jpeg *.bmp *.gif *.webp"),
                       ("Все файлы", "*.*")])
        if not path:
            return
        self.image_path = path
        self.batch_paths = None
        self.file_lbl.config(text=os.path.basename(path), foreground="black")
        self.log(f"Загружено: {os.path.basename(path)}")
        self._update_preview()
    
    def on_load_pdf(self):
        path = filedialog.askopenfilename(
            title="Выбери PDF",
            filetypes=[("PDF", "*.pdf"), ("Все файлы", "*.*")])
        if not path:
            return
        from funnyprint.imaging import get_pdf_page_count
        self.pdf_path = path
        self.pdf_page_count = get_pdf_page_count(path)
        self.pdf_lbl.config(
            text=os.path.basename(path), foreground="black")
        self.pdf_pages_lbl.config(
            text=f"Всего страниц: {self.pdf_page_count}")
        if self.pdf_page_count == 1:
            self.pdf_range_var.set("1")
        else:
            self.pdf_range_var.set("all")
        self.log(f"PDF: {os.path.basename(path)}, {self.pdf_page_count} стр.")
        self._update_preview()

    def _hotkey_open(self):
        """Ctrl+O — открыть файл в зависимости от вкладки"""
        tab = self._get_tab()
        if tab == 0:
            self.on_load_image()
        elif tab == 1:
            self.on_load_pdf()
        elif tab == 0 and self.batch_paths:
            self.on_batch()

    # ══════════════════════════════════
    #  BLE
    # ══════════════════════════════════
    def on_connect(self):
        if self.busy:
            return
        self._set_busy(True)
        self.btn_connect.config(state=tk.DISABLED)
        self._run_async(self._do_connect())

    async def _do_connect(self):
        try:
            self.printer = await find_and_connect(
                on_log=self.log, on_progress=self._set_progress)
            if self.printer:
                self._set_status(True)
                self.root.after(0, lambda: self.battery_lbl.config(
                    text=f"Батарея: {self.printer.battery}%"))
            else:
                self._set_status(False)
        except Exception as e:
            self.log(f"Ошибка: {e}")
            self._set_status(False)
        finally:
            self._set_busy(False)

    def on_disconnect(self):
        self._run_async(self._do_disconnect())

    async def _do_disconnect(self):
        try:
            if self.printer and self.printer.client:
                if self.printer.client.is_connected:
                    await self.printer.client.disconnect()
            self.log("Отключено")
        except Exception as e:
            self.log(f"Ошибка: {e}")
        self.printer = None
        self._set_status(False)

    def on_print(self):
        if not self.connected:
            self.log("Сначала подключись!")
            return
        if self.busy:
            return
        self._update_preview()
        if not self.current_lines:
            self.log("Нечего печатать!")
            return
        self._set_busy(True)
        self.print_btn.set_progress(0)
        self._run_async(self._do_print(
            self.current_lines,
            int(self.density_var.get()),
            self.feed_var.get()))

    async def _do_print(self, lines, density, feed):
        try:
            self.log(f"Печать: {len(lines) * 2}px, яркость={density}")
            await self.printer.print_lines(lines, density, feed)
            self.root.after(0, lambda: self.battery_lbl.config(
                text=f"Батарея: {self.printer.battery}%"))
        except Exception as e:
            self.log(f"Ошибка: {e}")
            if self.printer and self.printer.client:
                if not self.printer.client.is_connected:
                    self._set_status(False)
        finally:
            self._set_busy(False)

    def on_feed(self):
        if not self.connected:
            self.log("Сначала подключись!")
            return
        if self.busy:
            return
        self._set_busy(True)
        self._run_async(self._do_feed(self.feed_var.get()))

    async def _do_feed(self, px):
        try:
            await self.printer.feed(px)
        except Exception as e:
            self.log(f"Ошибка: {e}")
        finally:
            self._set_busy(False)

    def on_batch(self):
        """Пакетная печать картинок — загрузка и превью"""
        paths = filedialog.askopenfilenames(
            title="Выбери картинки",
            filetypes=[
                ("Картинки", "*.png *.jpg *.jpeg *.bmp *.gif *.webp"),
                ("Все файлы", "*.*")])
        if not paths:
            return

        self.batch_paths = list(paths)
        self.log(f"Пакет: загружено {len(self.batch_paths)} картинок")
        self._update_batch_preview()

    def _update_batch_preview(self):
        if not self.batch_paths:
            return
        flt = self._get_filters()
        feed = self.feed_var.get()
        try:
            from funnyprint.imaging import prepare_batch_images
            lines, preview = prepare_batch_images(
                self.batch_paths, feed_between=feed, **self._get_prepare_filters())
            from funnyprint.imaging import add_feed_preview
            preview = add_feed_preview(preview, feed)
            self.current_lines = lines
            self.current_preview = preview
            self._show_preview(preview)
            self.will_print_lbl.config(
                text=f"Напечатается: пакет ({len(self.batch_paths)} картинок)")
        except Exception as e:
            self.log(f"Ошибка пакета: {e}")

    def _get_filters(self):
        return dict(
            brightness=int(self.bright_var.get()),
            contrast=int(self.contrast_var.get()),
            sharpness=int(self.sharp_var.get()),
            dither=self.dither_var.get(),
            rotation=int(self.rotation_var.get()),
            artistic=self.artistic_var.get(),
            border=self.border_var.get(),
        )

    def _get_prepare_filters(self):
        """Фильтры для функций prepare_*"""
        return self._get_filters()

    def _parse_page_range(self, range_str, max_pages):
        """Парсит '1-3,5,7-9' → список номеров страниц (0-based)"""
        if range_str.strip().lower() == "all":
            return list(range(max_pages))
        pages = set()
        for part in range_str.split(","):
            part = part.strip()
            if "-" in part:
                start, end = part.split("-", 1)
                start = max(1, int(start.strip()))
                end = min(max_pages, int(end.strip()))
                for p in range(start, end + 1):
                    pages.add(p - 1)
            else:
                p = int(part.strip())
                if 1 <= p <= max_pages:
                    pages.add(p - 1)
        return sorted(pages)

    def _rt_insert_tag(self, tag, paired=True):
        """Вставляет тег в Rich Text поле"""
        w = self.rt_widget
        try:
            sel_start = w.index(tk.SEL_FIRST)
            sel_end = w.index(tk.SEL_LAST)
            selected = w.get(sel_start, sel_end)
            if tag.startswith("size:"):
                open_tag = f"<{tag}>"
                close_tag = "</size>"
            else:
                open_tag = f"<{tag}>"
                close_tag = f"</{tag}>"
            w.delete(sel_start, sel_end)
            w.insert(sel_start, open_tag + selected + close_tag)
        except tk.TclError:
            # Нет выделения — вставляем пустые теги
            if tag.startswith("size:"):
                open_tag = f"<{tag}>"
                close_tag = "</size>"
            else:
                open_tag = f"<{tag}>"
                close_tag = f"</{tag}>"
            pos = w.index(tk.INSERT)
            w.insert(pos, open_tag + close_tag)
            # Курсор между тегами
            w.mark_set(tk.INSERT, f"{pos}+{len(open_tag)}c")
        w.focus_set()
        self._schedule()

    def _rt_insert_marker(self, marker):
        """Вставляет маркер списка в начало строки"""
        w = self.rt_widget
        try:
            sel_start = w.index(tk.SEL_FIRST)
            sel_end = w.index(tk.SEL_LAST)
            # Вставляем маркер в начало каждой выделенной строки
            start_line = int(sel_start.split('.')[0])
            end_line = int(sel_end.split('.')[0])
            for line_no in range(start_line, end_line + 1):
                w.insert(f"{line_no}.0", marker)
        except tk.TclError:
            # Нет выделения — вставляем в начало текущей строки
            pos = w.index(tk.INSERT)
            line_no = pos.split('.')[0]
            w.insert(f"{line_no}.0", marker)
        w.focus_set()
        self._schedule()

    def _on_cancel(self):
        if self.printer:
            self.printer.cancel()
            self.log("Отмена печати...")

    def _on_secret(self, event=None):
        if not self.connected or self.busy:
            return
        self.log("Секретная печать!")
        self._set_busy(True)
        self.print_btn.set_progress(0)
        lines, _ = prepare_text(SECRET_TEXT, font_size=20, align="center")
        self._run_async(self._do_print(
            lines, int(self.density_var.get()), self.feed_var.get()))

    def _on_close(self):
        if self.connected:
            future = self._run_async(self._do_disconnect())
            try:
                future.result(timeout=2)
            except Exception:
                pass
        try:
            self._ble_loop.call_soon_threadsafe(self._ble_loop.stop)
        except Exception:
            pass
        self.root.destroy()

    def run(self):
        self.root.mainloop()