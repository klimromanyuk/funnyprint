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
from funnyprint.service import PrintService


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

        self.connected = False
        self.busy = False
        self.image_path = None
        self.batch_paths = None
        self.chunk_index = 0
        self._cancel_all = False
        self.total_chunks = 1
        self.all_lines_cache = None  # для маленьких данных
        self.current_lines = None
        self.current_preview = None
        self._preview_tk = None
        self._update_timer = None
        self._preview_busy = False
        self._zoom = 1.0
        self._last_tab = -1

        self.system_fonts = get_system_fonts()
        self.font_names = list(self.system_fonts.keys())

        self._build_ui()

        self.service = PrintService(
            on_log=self.log, on_progress=self._set_progress)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

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
            self.btn_print_all.config(state=st)
            self.btn_cancel.config(state=tk.NORMAL if busy else tk.DISABLED)
            if not busy:
                self.root.after(1500, lambda: self.print_btn.set_progress(0))
        self.root.after(0, _u)

    def _build_ui(self):
        conn = self._build_connection()
        conn.pack(fill=tk.X, padx=5, pady=(5, 2))

        main_pane = tk.PanedWindow(
            self.root, orient=tk.VERTICAL,
            sashwidth=8, sashrelief=tk.RAISED, bg="#b0b0b0",
            sashcursor="sb_v_double_arrow")
        main_pane.pack(fill=tk.BOTH, expand=True, padx=5, pady=2)

        upper = tk.Frame(main_pane)
        main_pane.add(upper, minsize=250)

        h_pane = tk.PanedWindow(
            upper, orient=tk.HORIZONTAL,
            sashwidth=8, sashrelief=tk.RAISED, bg="#b0b0b0",
            sashcursor="sb_h_double_arrow")
        h_pane.pack(fill=tk.BOTH, expand=True)

        left = self._build_left_panel(h_pane)
        right = self._build_preview_panel(h_pane)
        h_pane.add(left, minsize=250, width=340)
        h_pane.add(right, minsize=250)

        self._build_log(main_pane)
        self._build_secret()
        self._bind_global_keys()

        self.root.after(500, self._start_preview)
        if self._dnd_available:
            from tkinterdnd2 import DND_FILES
            self.root.drop_target_register(DND_FILES)
            self.root.dnd_bind('<<Drop>>', self._on_drop)

    def _build_connection(self):
        conn = ttk.LabelFrame(self.root, text="Подключение", padding=5)
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
        return conn

    def _build_left_panel(self, parent):
        left_outer = tk.Frame(parent)
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

        def _resize_inner(e):
            left_canvas.itemconfig("inner", width=e.width)
        left_canvas.bind("<Configure>", _resize_inner)

        def _left_wheel(e):
            left_canvas.yview_scroll(-(e.delta // 120), "units")
            return "break"
        left_canvas.bind("<MouseWheel>", _left_wheel)
        left.bind("<MouseWheel>", _left_wheel)

        def _bind_wheel_recursive(widget):
            widget.bind("<MouseWheel>", _left_wheel)
            for child in widget.winfo_children():
                if not isinstance(child, (tk.Text, tk.Listbox)):
                    _bind_wheel_recursive(child)
        self.root.after(1000, lambda: _bind_wheel_recursive(left))

        self._build_tabs(left)
        self._build_settings(left)
        self._build_buttons(left)

        self.will_print_lbl = ttk.Label(
            left, text="", foreground="#555", wraplength=300)
        self.will_print_lbl.pack(pady=2, padx=2)

        return left_outer

    def _build_tabs(self, parent):
        self.tabs = ttk.Notebook(parent)
        self.tabs.pack(fill=tk.BOTH, expand=True, padx=2, pady=(2, 0))
        self.tabs.bind("<<NotebookTabChanged>>", self._on_tab_change)

        self._build_tab_image()
        self._build_tab_pdf()
        self._build_tab_richtext()
        self._build_tab_text()
        self._build_tab_qr()
        self._build_tab_barcode()

    def _build_tab_image(self):
        t = ttk.Frame(self.tabs, padding=8)
        self.tabs.add(t, text="   Картинка   ")
        ttk.Button(t, text="Выбрать файл",
                   command=self.on_load_image).pack(fill=tk.X, pady=5)
        self.file_lbl = ttk.Label(t, text="Файл не выбран",
                                  wraplength=260, foreground="gray")
        self.file_lbl.pack(pady=2)
        ttk.Button(t, text="Пакетная печать (несколько файлов)",
                   command=self.on_batch).pack(fill=tk.X, pady=5)

    def _build_tab_pdf(self):
        t = ttk.Frame(self.tabs, padding=8)
        self.tabs.add(t, text="   PDF   ")
        ttk.Button(t, text="Выбрать PDF",
                   command=self.on_load_pdf).pack(fill=tk.X, pady=5)
        self.pdf_lbl = ttk.Label(t, text="PDF не выбран",
                                 wraplength=260, foreground="gray")
        self.pdf_lbl.pack(pady=2)

        pg_f = ttk.Frame(t)
        pg_f.pack(fill=tk.X, pady=5)
        ttk.Label(pg_f, text="Страницы:").pack(side=tk.LEFT)
        self.pdf_range_var = tk.StringVar(value="1")
        e = ttk.Entry(pg_f, textvariable=self.pdf_range_var,
                       font=("Arial", 11))
        e.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        e.bind("<KeyRelease>", lambda e: self._schedule())

        self.pdf_pages_lbl = ttk.Label(t, text="",
                                       foreground="gray", font=("Arial", 8))
        self.pdf_pages_lbl.pack(anchor=tk.W)
        ttk.Label(t, text='Примеры: "1", "1-3", "1,3,5", "all"',
                  foreground="gray", font=("Arial", 8)).pack(anchor=tk.W)
        self.pdf_path = None
        self.pdf_page_count = 0

    def _build_tab_richtext(self):
        t = ttk.Frame(self.tabs, padding=8)
        self.tabs.add(t, text="   Rich Text   ")

        self.rt_widget = tk.Text(t, height=5, width=30, wrap=tk.WORD,
                                 font=("Consolas", 10), undo=True, maxundo=50)
        self.rt_widget.pack(fill=tk.BOTH, expand=True, pady=(0, 4))
        self.rt_widget.insert("1.0",
            "<b>Жирный</b> и обычный\n"
            "<i>Курсив</i> и <u>подчёркнутый</u>\n"
            "[] Задача\n[x] Выполнена")
        self.rt_widget.bind("<KeyRelease>", lambda e: self._schedule())

        bf = ttk.Frame(t)
        bf.pack(fill=tk.X, pady=2)
        for text, tag in [("B","b"),("I","i"),("U","u"),("S","s"),
                          ("x²","sup"),("x₂","sub"),("Aa","size:24")]:
            ttk.Button(bf, text=text, width=3,
                command=lambda tg=tag: self._rt_insert_tag(tg, True)
            ).pack(side=tk.LEFT, padx=1)

        af = ttk.Frame(t)
        af.pack(fill=tk.X, pady=2)
        for label, tag in [("Лево","left"),("Центр","center"),
                           ("Право","right")]:
            ttk.Button(af, text=label, width=6,
                command=lambda tg=tag: self._rt_insert_tag(tg, True)
            ).pack(side=tk.LEFT, padx=1)

        lf = ttk.Frame(t)
        lf.pack(fill=tk.X, pady=2)
        for label, marker in [("☐","[] "),("☑","[x] "),("•","• "),
                               ("–","- "),("▶","> "),("★","★ "),
                               ("○","○ "),("1.","1. ")]:
            ttk.Button(lf, text=label, width=3,
                command=lambda m=marker: self._rt_insert_marker(m)
            ).pack(side=tk.LEFT, padx=1)

        ff = ttk.Frame(t)
        ff.pack(fill=tk.X, pady=2)
        ttk.Label(ff, text="Шрифт:").pack(side=tk.LEFT)
        self.rt_font_combo = ttk.Combobox(ff, values=self.font_names,
                                          state="readonly", width=18)
        self.rt_font_combo.pack(side=tk.LEFT, padx=5)
        for i, name in enumerate(self.font_names):
            if "arial" in name.lower() and "bold" not in name.lower():
                self.rt_font_combo.current(i)
                break
        self.rt_font_combo.bind("<<ComboboxSelected>>",
                                lambda e: self._schedule())

        sf = ttk.Frame(t)
        sf.pack(fill=tk.X, pady=2)
        ttk.Label(sf, text="Базовый размер:").pack(side=tk.LEFT)
        self.rt_font_size_var = tk.IntVar(value=24)
        ttk.Spinbox(sf, from_=8, to=96, width=4,
                    textvariable=self.rt_font_size_var,
                    command=self._schedule).pack(side=tk.LEFT, padx=5)

        ttk.Label(t, text="Подсказка: выдели текст и нажми кнопку\n"
                  "для применения тега",
                  foreground="gray", font=("Arial", 8),
                  justify=tk.LEFT).pack(anchor=tk.W, pady=2)

    def _build_tab_text(self):
        t = ttk.Frame(self.tabs, padding=8)
        self.tabs.add(t, text="   Текст   ")

        self.text_widget = tk.Text(t, height=5, width=30, wrap=tk.WORD,
                                   font=("Arial", 11), undo=True, maxundo=50)
        self.text_widget.pack(fill=tk.BOTH, expand=True, pady=(0, 4))
        self.text_widget.insert("1.0", "Привет мир!")
        self.text_widget.bind("<KeyRelease>", lambda e: self._schedule())

        ff = ttk.Frame(t)
        ff.pack(fill=tk.X, pady=2)
        ttk.Label(ff, text="Шрифт:").pack(side=tk.LEFT)
        self._font_search_var = tk.StringVar()
        self._font_search_var.trace_add("write", self._filter_fonts)
        ttk.Entry(ff, textvariable=self._font_search_var).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=5)

        flf = ttk.Frame(t)
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

        sf = ttk.Frame(t)
        sf.pack(fill=tk.X, pady=2)
        ttk.Label(sf, text="Размер:").pack(side=tk.LEFT)
        self.font_size_var = tk.IntVar(value=24)
        ttk.Spinbox(sf, from_=8, to=96, width=4,
                    textvariable=self.font_size_var,
                    command=self._schedule).pack(side=tk.LEFT, padx=5)

        bi = ttk.Frame(t)
        bi.pack(fill=tk.X, pady=2)
        self.bold_var = tk.BooleanVar()
        self.italic_var = tk.BooleanVar()
        ttk.Checkbutton(bi, text="Жирный", variable=self.bold_var,
                        command=self._schedule).pack(side=tk.LEFT, padx=5)
        ttk.Checkbutton(bi, text="Курсив", variable=self.italic_var,
                        command=self._schedule).pack(side=tk.LEFT, padx=5)

        al = ttk.Frame(t)
        al.pack(fill=tk.X, pady=2)
        ttk.Label(al, text="Выравн:").pack(side=tk.LEFT)
        self.align_var = tk.StringVar(value="left")
        for val, txt in [("left"," Лево "),("center"," Центр "),
                         ("right"," Право ")]:
            ttk.Radiobutton(al, text=txt, value=val,
                            variable=self.align_var,
                            command=self._schedule).pack(side=tk.LEFT, padx=2)

        stf = ttk.Frame(t)
        stf.pack(fill=tk.X, pady=2)
        self.strip_var = tk.BooleanVar()
        ttk.Checkbutton(stf, text="Лента (90)",
                        variable=self.strip_var,
                        command=self._on_strip_toggle).pack(side=tk.LEFT)
        self.strip_info_lbl = ttk.Label(stf, text="", foreground="gray")
        self.strip_info_lbl.pack(side=tk.LEFT, padx=10)

    def _build_tab_qr(self):
        t = ttk.Frame(self.tabs, padding=8)
        self.tabs.add(t, text="   QR   ")
        ttk.Label(t, text="Данные:").pack(anchor=tk.W)
        self.qr_entry = tk.Text(t, height=3, width=30,
                                wrap=tk.WORD, font=("Arial", 11))
        self.qr_entry.pack(fill=tk.X, pady=(0, 5))
        self.qr_entry.insert("1.0", "https://example.com")
        self.qr_entry.bind("<KeyRelease>", lambda e: self._schedule())
        ttk.Label(t, text="Несколько QR — каждый на новой строке",
                  foreground="gray", font=("Arial", 8)).pack(anchor=tk.W)
        self.qr_text_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(t, text="Добавить текст под QR",
                        variable=self.qr_text_var,
                        command=self._schedule).pack(anchor=tk.W, pady=2)

    def _build_tab_barcode(self):
        t = ttk.Frame(self.tabs, padding=8)
        self.tabs.add(t, text="   Barcode   ")
        ttk.Label(t, text="Данные:").pack(anchor=tk.W)
        self.bc_entry = tk.Text(t, height=3, width=30,
                                wrap=tk.WORD, font=("Arial", 11))
        self.bc_entry.pack(fill=tk.X, pady=(0, 5))
        self.bc_entry.insert("1.0", "123456789012")
        self.bc_entry.bind("<KeyRelease>", lambda e: self._schedule())
        ttk.Label(t, text="Латиница и цифры. Несколько кодов —\n"
                  "каждый на новой строке или через запятую",
                  foreground="gray", font=("Arial", 8)).pack(anchor=tk.W)

        tf = ttk.Frame(t)
        tf.pack(fill=tk.X, pady=2)
        ttk.Label(tf, text="Тип:").pack(side=tk.LEFT)
        self.bc_type_var = tk.StringVar(value="code128")
        from funnyprint.imaging import BARCODE_TYPES
        ttk.Combobox(tf, values=BARCODE_TYPES,
                     textvariable=self.bc_type_var,
                     state="readonly", width=12).pack(side=tk.LEFT, padx=5)
        self.bc_type_var.trace_add("write", lambda *a: self._schedule())

        self.bc_text_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(t, text="Показать текст",
                        variable=self.bc_text_var,
                        command=self._schedule).pack(anchor=tk.W, pady=2)

    def _build_settings(self, parent):
        sett = ttk.LabelFrame(parent, text="Настройки печати", padding=5)
        sett.pack(fill=tk.X, padx=2, pady=2)

        self._slider(sett, "Интенсивность (принтер)", 0, 7,
                     DEFAULT_DENSITY, "density_var", is_int=True,
                     schedule=False)
        self._slider(sett, "Яркость (фильтр)", -100, 100, 0, "bright_var")
        self._slider(sett, "Контраст", -100, 100, 0, "contrast_var")
        self._slider(sett, "Резкость", -100, 100, 0, "sharp_var")

        af = ttk.Frame(sett)
        af.pack(fill=tk.X, pady=2)
        ttk.Label(af, text="Фильтр:").pack(side=tk.LEFT)
        self.artistic_var = tk.StringVar(value="Нет")
        from funnyprint.imaging import ARTISTIC_FILTERS
        ttk.Combobox(af, values=ARTISTIC_FILTERS,
                     textvariable=self.artistic_var,
                     state="readonly", width=18).pack(side=tk.LEFT, padx=5)
        self.artistic_var.trace_add("write", lambda *a: self._schedule())

        brf = ttk.Frame(sett)
        brf.pack(fill=tk.X, pady=2)
        ttk.Label(brf, text="Рамка:").pack(side=tk.LEFT)
        self.border_var = tk.StringVar(value="Нет")
        from funnyprint.borders import get_border_names
        ttk.Combobox(brf, values=get_border_names(),
                     textvariable=self.border_var,
                     state="readonly", width=18).pack(side=tk.LEFT, padx=5)
        self.border_var.trace_add("write", lambda *a: self._schedule())

        df = ttk.Frame(sett)
        df.pack(fill=tk.X, pady=2)
        ttk.Label(df, text="Дизеринг:").pack(side=tk.LEFT)
        self.dither_var = tk.StringVar(value="Floyd-Steinberg")
        ttk.Combobox(df, values=DITHER_METHODS, textvariable=self.dither_var,
                     state="readonly", width=15).pack(side=tk.LEFT, padx=5)
        self.dither_var.trace_add("write", lambda *a: self._schedule())

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
            try: self._rot_double.set(float(self.rotation_var.get()))
            except (ValueError, tk.TclError): pass
        self.rotation_var.trace_add("write", _rot_var_changed)
        ttk.Scale(rot_f, from_=0, to=359, variable=self._rot_double,
                  orient=tk.HORIZONTAL,
                  command=_rot_scale_changed
                  ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)

        cp_f = ttk.Frame(sett)
        cp_f.pack(fill=tk.X, pady=2)
        ttk.Label(cp_f, text="Копий:").pack(side=tk.LEFT)
        self.copies_var = tk.IntVar(value=1)
        cs = ttk.Spinbox(cp_f, from_=1, to=99, width=4,
                         textvariable=self.copies_var,
                         command=self._schedule)
        cs.pack(side=tk.LEFT, padx=5)
        cs.bind("<KeyRelease>", lambda e: self._schedule())
        ttk.Label(cp_f, text="(дублирует контент)",
                  foreground="gray", font=("Arial", 8)).pack(side=tk.LEFT)

        pf = ttk.Frame(sett)
        pf.pack(fill=tk.X, pady=2)
        ttk.Label(pf, text="Промотка после:").pack(side=tk.LEFT)
        self.feed_var = tk.IntVar(value=DEFAULT_FEED_AFTER)
        fs = ttk.Spinbox(pf, from_=0, to=500, width=5,
                         textvariable=self.feed_var,
                         command=self._schedule)
        fs.pack(side=tk.LEFT, padx=5)
        fs.bind("<KeyRelease>", lambda e: self._schedule())
        ttk.Label(pf, text="px").pack(side=tk.LEFT)
        ttk.Label(sett, text="(принтер также делает свою промотку\n"
                  "после каждой печати для отрыва)",
                  foreground="gray", font=("Arial", 8)).pack(anchor=tk.W)

    def _build_buttons(self, parent):
        bf = ttk.Frame(parent)
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

        chunk_print_f = ttk.Frame(bf)
        chunk_print_f.pack(fill=tk.X, pady=2)
        self.btn_print_all = ttk.Button(
            chunk_print_f, text="Печатать все части",
            command=self._on_print_all_chunks)
        self.btn_print_all.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.chunk_range_var = tk.StringVar(value="all")
        ttk.Entry(chunk_print_f, textvariable=self.chunk_range_var,
                  width=8).pack(side=tk.LEFT, padx=3)
        self.chunk_print_f = chunk_print_f
        chunk_print_f.pack_forget()

        self.total_length_lbl = ttk.Label(
            bf, text="", foreground="gray", font=("Arial", 8))
        self.total_length_lbl.pack()
        self.btn_cancel.pack(fill=tk.X, pady=2)

    def _build_preview_panel(self, parent):
        right = ttk.LabelFrame(parent, text="Предпросмотр", padding=5)

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

        self.chunk_frame = ttk.Frame(zb)
        self.chunk_frame.pack(side=tk.RIGHT)
        self.btn_prev_chunk = ttk.Button(
            self.chunk_frame, text="◀", width=2, command=self._prev_chunk)
        self.btn_prev_chunk.pack(side=tk.LEFT)
        self.chunk_lbl = ttk.Label(self.chunk_frame, text="")
        self.chunk_lbl.pack(side=tk.LEFT, padx=3)
        self.btn_next_chunk = ttk.Button(
            self.chunk_frame, text="▶", width=2, command=self._next_chunk)
        self.btn_next_chunk.pack(side=tk.LEFT)
        self.chunk_frame.pack_forget()

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
        self.loading_lbl = ttk.Label(
            right, text="", foreground="orange",
            font=("Arial", 10, "bold"))
        self.loading_lbl.pack()

        return right

    def _build_log(self, parent):
        log_frame = ttk.LabelFrame(
            parent, text="Лог  (тяни серую полосу)", padding=2)
        parent.add(log_frame, minsize=50)

        li = tk.Frame(log_frame)
        li.pack(fill=tk.BOTH, expand=True)
        self.log_text = tk.Text(li, height=3, wrap=tk.WORD,
                                state=tk.DISABLED, font=("Consolas", 9))
        ls = ttk.Scrollbar(li, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=ls.set)
        ls.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.pack(fill=tk.BOTH, expand=True)
        self._log_write("Готов. Нажми Подключить.")

    def _build_secret(self):
        secret = tk.Label(self.root, text=" \u2665 ", font=("Arial", 11),
                          fg="#d0d0d0", bg="#f0f0f0", cursor="hand2")
        secret.place(relx=1.0, rely=1.0, anchor="se", x=-4, y=-2)
        secret.bind("<Button-1>", self._on_secret)
        secret.bind("<Enter>", lambda e: secret.config(fg="#e06060"))
        secret.bind("<Leave>", lambda e: secret.config(fg="#d0d0d0"))

    def _bind_global_keys(self):
        self.root.bind_all("<MouseWheel>", self._on_global_wheel)
        self.root.bind_all("<Key>", self._on_global_key)

    def _slider(self, parent, label, from_, to, default, var_name,
                is_int=False, schedule=True):
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
            if schedule:
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
        if not (event.state & 0x4):
            return

        ch = event.char
        w = event.widget
        is_text = isinstance(w, tk.Text)
        is_entry = isinstance(w, (ttk.Entry, tk.Entry))
        is_input = is_text or is_entry

        # Ctrl+A
        if ch == '\x01':
            if is_text:
                w.tag_add("sel", "1.0", "end")
                return "break"
            if is_entry:
                w.selection_range(0, tk.END)
                return "break"

        # Ctrl+C/V/X — clipboard
        clip_map = {'\x03': "<<Copy>>", '\x16': "<<Paste>>",
                    '\x18': "<<Cut>>"}
        if ch in clip_map and is_input:
            try:
                w.event_generate(clip_map[ch])
            except Exception:
                pass
            return "break"

        # Ctrl+Z/Y — undo/redo
        if ch == '\x1a' and is_text and w.cget("undo"):
            try: w.edit_undo()
            except Exception: pass
            return "break"
        if ch == '\x19' and is_text and w.cget("undo"):
            try: w.edit_redo()
            except Exception: pass
            return "break"

        # Ctrl+P / Ctrl+O
        if ch == '\x10':
            self.on_print()
            return "break"
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
        tab = self._get_tab()
        delay = 800 if tab in (4, 5) else 300
        self._update_timer = self.root.after(delay, self._start_preview)

    def _get_tab(self):
        try:
            return self.tabs.index(self.tabs.select())
        except Exception:
            return 0

    def _start_preview(self):
        """Запускает _update_preview в фоновом потоке."""
        if self._preview_busy:
            self._schedule()
            return
        self._preview_busy = True
        self.loading_lbl.config(text="Загрузка...")
        threading.Thread(target=self._bg_preview, daemon=True).start()

    def _bg_preview(self):
        try:
            self._update_preview()
        except Exception as e:
            self.root.after(0, lambda: self.log(f"Ошибка превью: {e}"))
        finally:
            self.root.after(0, self._preview_done)

    def _preview_done(self):
        self._preview_busy = False
        self.loading_lbl.config(text="")

    def _update_preview(self):
        self._update_timer = None
        tab = self._get_tab()
        copies = self.copies_var.get()
        heavy = (
            (tab == 1 and self.pdf_path and self.pdf_page_count > 5)
            or (tab == 0 and self.batch_paths
                and len(self.batch_paths) > 10)
            or copies > 5
            or (tab == 4 and len(
                self.qr_entry.get("1.0", tk.END).strip().split('\n')) > 5)
            or (tab == 5 and len(
                self.bc_entry.get("1.0", tk.END).strip()
                .replace('\n', ',').split(',')) > 5))
        if heavy:
            self.loading_lbl.config(text="Загрузка...")
            self.root.update_idletasks()
        self._last_tab = tab

        try:
            _handlers = [
                self._preview_tab_image, self._preview_tab_pdf,
                self._preview_tab_richtext, self._preview_tab_text,
                self._preview_tab_qr, self._preview_tab_barcode,
            ]
            if tab >= len(_handlers):
                return
            result = _handlers[tab]()
            if result is None:
                self.loading_lbl.config(text="")
                return

            lines, preview = result

            # Копии
            if copies > 1:
                feed = self.feed_var.get()
                repeated = []
                blank = bytes(96)
                gap = feed // 2 if feed > 0 else 0
                for c in range(copies):
                    repeated.extend(lines)
                    if c < copies - 1 and gap > 0:
                        repeated.extend(blank for _ in range(gap))
                lines = repeated

            # Финальное чанкование
            from funnyprint.chunked import (
                needs_chunking, MAX_CHUNK_LINES, estimate_chunks)
            if needs_chunking(lines):
                total_ch = estimate_chunks(len(lines))
                if self.chunk_index >= total_ch:
                    self.chunk_index = total_ch - 1
                s = self.chunk_index * MAX_CHUNK_LINES
                lines = lines[s:min(s + MAX_CHUNK_LINES, len(lines))]
                from funnyprint.imaging import _lines_to_preview
                preview = _lines_to_preview(lines)
                self._update_chunk_nav(total_ch, self.chunk_index)
            else:
                self._update_chunk_nav(1, 0)
                if copies > 1:
                    from funnyprint.imaging import _lines_to_preview
                    preview = _lines_to_preview(lines)

            self.current_lines = lines
            from funnyprint.imaging import add_feed_preview
            self.current_preview = add_feed_preview(
                preview, self.feed_var.get())
            self._show_preview(self.current_preview)
            self.loading_lbl.config(text="")

        except ValueError as e:
            self.log(f"Ошибка данных: {e}")
            self.canvas.delete("all")
            self.current_lines = None
            self.loading_lbl.config(text="")
        except Exception as e:
            self.log(f"Ошибка предпросмотра: {e}")
            self.loading_lbl.config(text="")

    # ── Хелперы превью ──

    def _clear_preview(self, msg=""):
        def _do():
            self.canvas.delete("all")
            self.size_lbl.config(text="")
            self.will_print_lbl.config(text=f"Напечатается: {msg}")
        self.current_lines = None
        self.root.after(0, _do)

    def _apply_chunking(self, all_lines, full_preview, label):
        from funnyprint.chunked import (
            needs_chunking, MAX_CHUNK_LINES, estimate_chunks)
        if needs_chunking(all_lines):
            total_ch = estimate_chunks(len(all_lines))
            if self.chunk_index >= total_ch:
                self.chunk_index = total_ch - 1
            s = self.chunk_index * MAX_CHUNK_LINES
            chunk = all_lines[s:min(s + MAX_CHUNK_LINES, len(all_lines))]
            from funnyprint.imaging import _lines_to_preview
            self._update_chunk_nav(total_ch, self.chunk_index)
            self.root.after(0, lambda: self.will_print_lbl.config(
                text=f"{label} — часть {self.chunk_index + 1}/{total_ch}"))
            return chunk, _lines_to_preview(chunk)
        self.root.after(0, lambda: self.will_print_lbl.config(
            text=f"Напечатается: {label}"))
        return all_lines, full_preview

    def _combine_items(self, bw_images, feed_gap):
        total_h = sum(b.height for b in bw_images)
        if feed_gap > 0:
            total_h += feed_gap * (len(bw_images) - 1)
        if total_h % 2:
            total_h += 1
        combined = Image.new("1", (PRINTER_WIDTH, total_h), color=1)
        y = 0
        for i, bw in enumerate(bw_images):
            combined.paste(bw, (0, y))
            y += bw.height
            if i < len(bw_images) - 1 and feed_gap > 0:
                y += feed_gap
        from funnyprint.imaging import pil_to_funny_lines
        return pil_to_funny_lines(combined), combined

    # ── Методы вкладок (возвращают (lines, preview) или None) ──

    def _preview_tab_image(self):
        if self.batch_paths:
            self._update_batch_preview()
            return None
        if not self.image_path:
            self._clear_preview("[выбери картинку]")
            return None
        all_lines, full_preview = prepare_image(
            self.image_path, **self._get_filters())
        return self._apply_chunking(
            all_lines, full_preview, os.path.basename(self.image_path))

    def _preview_tab_pdf(self):
        if not self.pdf_path:
            self._clear_preview("[выбери PDF]")
            return None
        range_str = self.pdf_range_var.get().strip()
        try:
            pages = self._parse_page_range(range_str, self.pdf_page_count)
        except (ValueError, AttributeError):
            pages = [0]
        if not pages:
            pages = [0]
        flt = self._get_filters()
        feed = self.feed_var.get()
        name = os.path.basename(self.pdf_path)

        if len(pages) == 1:
            from funnyprint.imaging import prepare_pdf_page
            lines, preview = prepare_pdf_page(
                self.pdf_path, page_num=pages[0], **flt)
            self.root.after(0, lambda: self.will_print_lbl.config(
                text=f"Напечатается: {name}"))
            return lines, preview

        import fitz
        from funnyprint.chunked import MAX_CHUNK_LINES, needs_chunking
        from funnyprint.imaging import prepare_batch_pdf

        doc = fitz.open(self.pdf_path)
        plc = []
        for pg in pages:
            p = doc[pg]
            plc.append(
                (int(p.rect.height * PRINTER_WIDTH / p.rect.width) + 1) // 2)
        doc.close()

        fl = feed // 2 if feed > 0 else 0
        if needs_chunking(sum(plc) + fl * (len(pages) - 1)):
            chunks_pages, cur_ch, cur_cnt = [], [], 0
            for i, lc in enumerate(plc):
                if cur_cnt + lc > MAX_CHUNK_LINES and cur_ch:
                    chunks_pages.append(cur_ch)
                    cur_ch, cur_cnt = [], 0
                cur_ch.append(pages[i])
                cur_cnt += lc + fl
            if cur_ch:
                chunks_pages.append(cur_ch)
            tc = len(chunks_pages)
            if self.chunk_index >= tc:
                self.chunk_index = tc - 1
            cp = chunks_pages[self.chunk_index]
            lines, preview = prepare_batch_pdf(
                self.pdf_path, cp, feed_between=feed, **flt)
            self._update_chunk_nav(tc, self.chunk_index)
            msg = (f"{name} — часть {self.chunk_index + 1}/{tc} "
                   f"({len(cp)} стр.)")
            self.root.after(0, lambda: self.will_print_lbl.config(text=msg))
        else:
            lines, preview = prepare_batch_pdf(
                self.pdf_path, pages, feed_between=feed, **flt)
            msg = f"Напечатается: {name} ({len(pages)} стр.)"
            self.root.after(0, lambda: self.will_print_lbl.config(text=msg))
        return lines, preview

    def _preview_tab_richtext(self):
        rt = self.rt_widget.get("1.0", tk.END).strip()
        if not rt:
            self._clear_preview("[введи rich text]")
            return None
        from funnyprint.richtext import render_rich_text, TextStyle
        from funnyprint.imaging import finalize_image, pil_to_funny_lines
        fn = self.rt_font_combo.get() or self.font_names[0]
        fp = self.system_fonts.get(fn)
        img = render_rich_text(
            rt, TextStyle(font_path=fp,
                          font_size=self.rt_font_size_var.get(),
                          align="left"))
        flt = self._get_filters()
        lines, bw = finalize_image(img, **flt, trim=True)
        return self._apply_chunking(lines, bw, f"rich text [{fn}]")

    def _preview_tab_text(self):
        text = self.text_widget.get("1.0", tk.END).strip()
        if not text:
            self._clear_preview("[введи текст]")
            return None
        sel = self.font_listbox.curselection()
        fn = self.font_listbox.get(sel[0]) if sel else self.font_names[0]
        all_lines, full_preview = prepare_text(
            text, font_path=self.system_fonts.get(fn),
            font_size=self.font_size_var.get(),
            bold=self.bold_var.get(), italic=self.italic_var.get(),
            align=self.align_var.get(), strip_mode=self.strip_var.get(),
            **self._get_filters())
        mode = " (лента)" if self.strip_var.get() else ""
        return self._apply_chunking(
            all_lines, full_preview, f"текст [{fn}]{mode}")

    def _preview_tab_qr(self):
        data = self.qr_entry.get("1.0", tk.END).strip()
        if not data:
            self._clear_preview("[введи данные QR]")
            return None
        from funnyprint.imaging import prepare_qr
        flt = self._get_filters()
        qr_items = [d.strip() for d in data.split('\n') if d.strip()]
        if len(qr_items) <= 1:
            lines, preview = prepare_qr(
                data, add_text=self.qr_text_var.get(), **flt)
            self.root.after(0, lambda: self.will_print_lbl.config(
                text="Напечатается: QR-код"))
            return lines, preview
        all_bw = []
        for item in qr_items:
            _, bw = prepare_qr(
                item, add_text=self.qr_text_var.get(), **flt)
            all_bw.append(bw)
        lines, preview = self._combine_items(all_bw, self.feed_var.get())
        msg = f"Напечатается: {len(qr_items)} QR-кодов"
        self.root.after(0, lambda: self.will_print_lbl.config(text=msg))
        return lines, preview

    def _preview_tab_barcode(self):
        data = self.bc_entry.get("1.0", tk.END).strip()
        if not data:
            self._clear_preview("[введи данные штрих-кода]")
            return None
        from funnyprint.imaging import prepare_barcode
        flt = self._get_filters()
        items = [d.strip() for d in data.replace('\n', ',').split(',')
                 if d.strip()]
        if len(items) <= 1:
            lines, preview = prepare_barcode(
                data, barcode_type=self.bc_type_var.get(),
                add_text=self.bc_text_var.get(), **flt)
            self.root.after(0, lambda: self.will_print_lbl.config(
                text="Напечатается: штрих-код"))
            return lines, preview
        all_bw = []
        for item in items:
            try:
                _, bw = prepare_barcode(
                    item, barcode_type=self.bc_type_var.get(),
                    add_text=self.bc_text_var.get(), **flt)
                all_bw.append(bw)
            except ValueError:
                pass
        if not all_bw:
            self.root.after(0, lambda: self.log(
                "Ни один штрих-код не валиден"))
            return None
        lines, preview = self._combine_items(all_bw, self.feed_var.get())
        msg = f"Напечатается: {len(all_bw)} штрих-кодов"
        self.root.after(0, lambda: self.will_print_lbl.config(text=msg))
        return lines, preview

    def _show_preview(self, pil_img):
        if not pil_img:
            return
        w, h = pil_img.size
        zw, zh = max(1, int(w * self._zoom)), max(1, int(h * self._zoom))
        display = pil_img.convert("RGB").resize((zw, zh), Image.NEAREST)
        def _do():
            self._preview_tk = ImageTk.PhotoImage(display)
            self.canvas.delete("all")
            self.canvas.create_image(0, 0, anchor=tk.NW,
                                     image=self._preview_tk)
            self.canvas.configure(scrollregion=(0, 0, zw, zh))
            mm_w = w / PRINTER_DPI * 25.4
            mm_h = h / PRINTER_DPI * 25.4
            self.size_lbl.config(
                text=f"{w}x{h}px | {mm_w:.0f}x{mm_h:.0f}mm | "
                     f"Zoom {int(self._zoom * 100)}%")
        self.root.after(0, _do)

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

    def _prev_chunk(self):
        if self.chunk_index > 0:
            self.chunk_index -= 1
            self._update_preview()

    def _next_chunk(self):
        if self.chunk_index < self.total_chunks - 1:
            self.chunk_index += 1
            self._update_preview()

    def _update_chunk_nav(self, total, current):
        self.total_chunks = total
        self.chunk_index = current
        def _do():
            if total <= 1:
                self.chunk_frame.pack_forget()
                self.chunk_print_f.pack_forget()
                self.total_length_lbl.config(text="")
            else:
                self.chunk_frame.pack(side=tk.RIGHT)
                self.chunk_lbl.config(text=f"{current + 1}/{total}")
                self.btn_prev_chunk.config(
                    state=tk.NORMAL if current > 0 else tk.DISABLED)
                self.btn_next_chunk.config(
                    state=tk.NORMAL if current < total - 1 else tk.DISABLED)
                self.chunk_print_f.pack(fill=tk.X, pady=2)
                self.total_length_lbl.config(
                    text=f"{total} частей. После каждой части\n"
                         f"принтер делает свою промотку.")
        self.root.after(0, _do)

    def _on_tab_change(self, event=None):
        if self._update_timer:
            self.root.after_cancel(self._update_timer)
        self.chunk_index = 0
        self._update_chunk_nav(1, 0)
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
        self.service.run_async(self._do_connect())

    async def _do_connect(self):
        try:
            ok = await self.service.connect()
            if ok:
                self._set_status(True)
                self.root.after(0, lambda: self.battery_lbl.config(
                    text=f"Батарея: {self.service.battery}%"))
            else:
                self._set_status(False)
        except Exception as e:
            self.log(f"Ошибка: {e}")
            self._set_status(False)
        finally:
            self._set_busy(False)

    def on_disconnect(self):
        self.service.run_async(self._do_disconnect())

    async def _do_disconnect(self):
        await self.service.disconnect()
        self._set_status(False)

    def on_print(self):
        if not self.connected:
            self.log("Сначала подключись!")
            return
        if self.busy:
            return
        if not self.current_lines:
            self.log("Нечего печатать!")
            return

        # Если чанки — печатаем текущий
        if self.total_chunks > 1:
            self.log(f"Печать части {self.chunk_index + 1}/{self.total_chunks}")
        self._set_busy(True)
        self.print_btn.set_progress(0)
        self.service.run_async(self._do_print(
            self.current_lines,
            int(self.density_var.get()),
            self.feed_var.get()))

    async def _do_print(self, lines, density, feed):
        try:
            self.log(f"Печать: {len(lines) * 2}px, яркость={density}")
            await self.service.print_lines(lines, density, feed)
            self.root.after(0, lambda: self.battery_lbl.config(
                text=f"Батарея: {self.service.battery}%"))
        except Exception as e:
            self.log(f"Ошибка: {e}")
            if not self.service.is_connected:
                self._set_status(False)
        finally:
            self._cancel_all = False
            self._set_busy(False)

    def on_feed(self):
        if not self.connected:
            self.log("Сначала подключись!")
            return
        if self.busy:
            return
        self._set_busy(True)
        self.service.run_async(self._do_feed(self.feed_var.get()))

    async def _do_feed(self, px):
        try:
            await self.service.feed(px)
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
        self.chunk_index = 0
        self.log(f"Пакет: загружено {len(self.batch_paths)} картинок")
        self._update_batch_preview()

    def _update_batch_preview(self):
        if not self.batch_paths:
            return
        flt = self._get_filters()
        feed = self.feed_var.get()
        try:
            from funnyprint.chunked import needs_chunking
            from funnyprint.imaging import (
                prepare_batch_images, prepare_batch_images_chunked,
                add_feed_preview)

            # Оцениваем размер
            if len(self.batch_paths) > 20:
                # Большой пакет — чанками
                lines, preview, total_chunks, total_files = \
                    prepare_batch_images_chunked(
                        self.batch_paths,
                        chunk_index=self.chunk_index,
                        feed_between=feed, **flt)
                self.current_lines = lines
                self.current_preview = preview
                self._show_preview(preview)
                self._update_chunk_nav(total_chunks, self.chunk_index)
                self.will_print_lbl.config(
                    text=f"Пакет: {total_files} картинок, "
                         f"часть {self.chunk_index + 1}/{total_chunks}")
                if total_chunks > 1:
                    self.log(f"Большой пакет: {total_files} файлов, "
                             f"{total_chunks} частей. "
                             f"Каждая часть печатается отдельно.")
            else:
                lines, preview = prepare_batch_images(
                    self.batch_paths, feed_between=feed, **flt)
                preview = add_feed_preview(preview, feed)
                self.current_lines = lines
                self.current_preview = preview
                self._show_preview(preview)
                self._update_chunk_nav(1, 0)
                self.will_print_lbl.config(
                    text=f"Пакет: {len(self.batch_paths)} картинок")
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

    def _on_print_all_chunks(self):
        if not self.connected:
            self.log("Сначала подключись!")
            return
        if self.busy:
            return

        range_str = self.chunk_range_var.get().strip()
        try:
            chunks_to_print = self._parse_page_range(
                range_str, self.total_chunks)
        except (ValueError, AttributeError):
            chunks_to_print = list(range(self.total_chunks))
        if not chunks_to_print:
            chunks_to_print = list(range(self.total_chunks))

        self._set_busy(True)
        self.print_btn.set_progress(0)
        density = int(self.density_var.get())
        feed = self.feed_var.get()
        self.service.run_async(
            self._do_print_all_chunks(chunks_to_print, density, feed))

    async def _do_print_all_chunks(self, chunks, density, feed):
        try:
            total = len(chunks)
            for i, chunk_idx in enumerate(chunks):
                if self._cancel_all:
                    self.log("Печать прервана!")
                    break
                self.log(f"Часть {chunk_idx + 1} [{i + 1}/{total}]")

                # Переключаем на нужный чанк и обновляем данные
                self.chunk_index = chunk_idx
                # Обновляем превью синхронно через событие
                done_event = asyncio.Event()
                def _do_update():
                    self._update_preview()
                    self.service._ble_loop.call_soon_threadsafe(done_event.set)
                self.root.after(0, _do_update)
                await done_event.wait()

                if not self.current_lines:
                    self.log(f"Часть {chunk_idx + 1} пуста, пропуск")
                    continue

                await self.service.print_lines(
                    self.current_lines, density, feed)
                if self._cancel_all:
                    self.log("Печать прервана после части!")
                    break
                self._set_progress(100 * (i + 1) // total)

                if i < total - 1:
                    await asyncio.sleep(3)

            self.log(f"Печать завершена ({total} частей)")
            self.root.after(0, lambda: self.battery_lbl.config(
                text=f"Батарея: {self.service.battery}%"))
        except Exception as e:
            self.log(f"Ошибка: {e}")
        finally:
            self._cancel_all = False
            self._set_busy(False)

    def _on_cancel(self):
        self._cancel_all = True
        self.service.cancel()
        self.log("Отмена печати...")

    def _on_secret(self, event=None):
        if not self.connected or self.busy:
            return
        self.log("Секретная печать!")
        self._set_busy(True)
        self.print_btn.set_progress(0)
        lines, _ = prepare_text(SECRET_TEXT, font_size=20, align="center")
        self.service.run_async(self._do_print(
            lines, int(self.density_var.get()), self.feed_var.get()))

    def _on_close(self):
        if self.connected:
            future = self.service.run_async(self._do_disconnect())
            try:
                future.result(timeout=2)
            except Exception:
                pass
        self.service.stop()
        self.root.destroy()

    def run(self):
        self.root.mainloop()