"""Design Matcher: find the design in your folders that matches a customer's photo.

Run:  python design_matcher_app.py
"""

import ctypes
import heapq
import json
import os
import queue
import subprocess
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, font as tkfont, ttk

from PIL import Image, ImageGrab, ImageOps, ImageTk

import matcher

VERSION = "1.2"

# The same colours as AZ Studio, so the AZ apps look like one family
BG = "#0d1018"          # window
PANEL = "#141824"       # the three panels
LINE = "#232a3a"        # panel and card borders
WELL = "#090b11"        # behind pictures
ROOM = "#10141e"        # cards, fields
BTN = "#1b2130"
BTN_LINE = "#2a3245"
BTN_HOVER = "#242b3d"
HOVER_LINE = "#3a4460"
INK = "#dfe3ec"
HEAD = "#f2f4f8"
MUTED = "#8a91a5"
SUB = "#9aa1b4"
VIOLET = "#6c4cff"
VIOLET_HOVER = "#7d61ff"
VIOLET_SOFT = "#2a2452"
VIOLET_TEXT = "#b9a8ff"
GREEN = "#4cd964"
PDF_RED = "#ff5a5f"
PIC_BLUE = "#4f8dff"
FONT = "Segoe UI"

# Segoe Fluent Icons (Windows 11) / Segoe MDL2 Assets (Windows 10) share these code points
ICONS = {"photo": "", "paste": "", "folder": "", "search": "", "close": "",
         "check": "", "down": "", "up": "", "left": "", "right": "",
         "open": "", "pdf": "", "picture": "", "compare": "", "index": "",
         "zoom": "", "info": "", "matches": ""}

TOP_N = 30
CARD_MIN, CARD_MAX, CARD_DEFAULT = 150, 300, 196
PREVIEW_PX = 480                        # thumbnails are read once at this size, then shrunk to the card size
SETTINGS = matcher.data_dir() / "settings.json"
ASSETS = matcher.app_dir() / "assets"

try:                                     # sharp text on scaled (4K / 150 %) screens
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    pass


def fit_text(text, fnt, width, keep_end=False):
    """Shorten text with an ellipsis so it fits in width pixels."""
    if fnt.measure(text) <= width:
        return text
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        cand = "…" + text[-mid:] if keep_end else text[:mid] + "…"
        if fnt.measure(cand) <= width:
            lo = mid
        else:
            hi = mid - 1
    if lo == 0:
        return "…"
    return "…" + text[-lo:] if keep_end else text[:lo] + "…"


def load_settings():
    try:
        return json.loads(SETTINGS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_settings(data):
    try:
        SETTINGS.write_text(json.dumps(data), encoding="utf-8")
    except OSError:
        pass


def rounded(canvas, x0, y0, x1, y1, r, **kw):
    """A rounded rectangle on a canvas (a smoothed polygon)."""
    r = max(0, min(r, (x1 - x0) / 2, (y1 - y0) / 2))
    pts = [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1, x1 - r, y1, x0 + r, y1, x0, y1,
           x0, y1 - r, x0, y0 + r, x0, y0]
    return canvas.create_polygon(pts, smooth=True, **kw)


class Button(tk.Canvas):
    """A flat rounded button in AZ Studio's style. kind: normal, accent (violet) or chip (a toggle)."""

    COLOURS = {"normal": (BTN, BTN_HOVER, BTN_LINE, INK),
               "accent": (VIOLET, VIOLET_HOVER, VIOLET, "#ffffff"),
               "chip": (ROOM, BTN, LINE, SUB),
               "chip_on": (VIOLET, VIOLET_HOVER, VIOLET, "#ffffff"),
               "ghost": (PANEL, BTN, PANEL, SUB)}

    def __init__(self, parent, app, text="", command=None, kind="normal", icon=None, height=34, font=None,
                 width=None, bg=PANEL):
        super().__init__(parent, height=app.px(height), bg=bg, highlightthickness=0, bd=0, cursor="hand2")
        self.app, self.text, self.command, self.kind, self.icon = app, text, command, kind, icon
        self.font = font or app.f_body
        self.hover = False
        self.enabled = True
        if width is None:
            width = self._natural_width()
        self.configure(width=app.px(width) if isinstance(width, int) and width < 2000 and width > 0 else width)
        self.bind("<Configure>", lambda e: self.draw())
        self.bind("<Enter>", lambda e: self._hover(True))
        self.bind("<Leave>", lambda e: self._hover(False))
        self.bind("<ButtonRelease-1>", self._click)

    def _natural_width(self):
        w = self.font.measure(self.text) if self.text else 0
        if self.icon and self.app.icon_font:
            w += self.app.f_icon.measure(ICONS[self.icon]) + (8 if self.text else 0)
        return round((w + self.app.px(28)) / self.app.scale)

    def _hover(self, on):
        self.hover = on
        self.draw()

    def _click(self, e):
        if self.enabled and self.command and 0 <= e.x <= self.winfo_width() and 0 <= e.y <= self.winfo_height():
            self.command()

    def set(self, text=None, kind=None, enabled=None, icon=None):
        if text is not None:
            self.text = text
        if kind is not None:
            self.kind = kind
        if enabled is not None:
            self.enabled = enabled
            self.configure(cursor="hand2" if enabled else "arrow")
        if icon is not None:
            self.icon = icon
        self.draw()

    def draw(self):
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w < 4 or h < 4:
            return
        fill, hover, line, ink = self.COLOURS[self.kind]
        if self.hover and self.enabled:
            fill, line = hover, (HOVER_LINE if self.kind in ("normal", "chip") else hover)
        if not self.enabled:
            fill, line, ink = (BTN, BTN_LINE, "#5d6478") if self.kind != "accent" else ("#252046", "#252046", "#6f6898")
        rounded(self, 1, 1, w - 1, h - 1, self.app.px(8), fill=line, outline="")
        rounded(self, 2, 2, w - 2, h - 2, self.app.px(7), fill=fill, outline="")
        parts = []
        if self.icon and self.app.icon_font:
            parts.append((ICONS[self.icon], self.app.f_icon))
        if self.text:
            parts.append((self.text, self.font))
        gap = self.app.px(8)
        total = sum(f.measure(t) for t, f in parts) + gap * (len(parts) - 1)
        x = (w - total) / 2
        for t, f in parts:
            self.create_text(x, h / 2 + (1 if f is self.app.f_icon else 0), text=t, font=f, fill=ink, anchor="w")
            x += f.measure(t) + gap


class Slider(tk.Canvas):
    """A thin track with a round knob, as in AZ Studio. command(value) is called while dragging."""

    def __init__(self, parent, app, lo, hi, value, command, length=150, bg=PANEL):
        super().__init__(parent, width=app.px(length), height=app.px(22), bg=bg, highlightthickness=0, cursor="hand2")
        self.app, self.lo, self.hi, self.value, self.command = app, lo, hi, value, command
        self.bind("<Configure>", lambda e: self.draw())
        self.bind("<Button-1>", self._drag)
        self.bind("<B1-Motion>", self._drag)

    def _ends(self):
        r = self.app.px(7)
        return r + 1, self.winfo_width() - r - 1

    def _drag(self, e):
        a, b = self._ends()
        t = min(max((e.x - a) / max(b - a, 1), 0.0), 1.0)
        self.set(self.lo + t * (self.hi - self.lo))
        self.command(self.value)

    def set(self, value):
        self.value = min(max(value, self.lo), self.hi)
        self.draw()

    def get(self):
        return self.value

    def draw(self):
        self.delete("all")
        a, b = self._ends()
        y, r, t = self.winfo_height() / 2, self.app.px(7), self.app.px(2)
        x = a + (self.value - self.lo) / (self.hi - self.lo) * (b - a)
        self.create_rectangle(a, y - t, b, y + t, fill=BTN_LINE, outline="")
        self.create_rectangle(a, y - t, x, y + t, fill=VIOLET, outline="")
        self.create_oval(x - r, y - r, x + r, y + r, fill="#ffffff", outline=VIOLET, width=self.app.px(2))


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Design Matcher")
        self.scale = max(1.0, self.winfo_fpixels("1i") / 96.0)
        self.geometry(f"{self.px(1440)}x{self.px(880)}")
        self.minsize(self.px(1180), self.px(720))
        self.configure(bg=BG)
        try:
            self.iconbitmap(default=str(ASSETS / "az.ico"))
        except tk.TclError:
            pass

        self.settings = load_settings()
        self.folder = tk.StringVar(value=self.settings.get("folder", ""))
        self.status = tk.StringVar()
        self.card_w = int(self.settings.get("card_w", CARD_DEFAULT))
        self.compare_open = bool(self.settings.get("compare_open", True))
        self.filter = "all"
        self.ref_img = None
        self.events = queue.Queue()
        self.thumb_jobs = queue.Queue()
        self.thumb_src = {}                  # (path, page) -> PIL preview, or None when unreadable
        self.thumb_tk = {}                   # (path, page, size) -> PhotoImage
        self.pending_thumbs = set()
        self.card_imgs = {}
        self.cards = []
        self.tops = {"all": [], "img": [], "pdf": []}
        self.results = []
        self.selected = None                 # (path, page) of the match shown in Compare
        self.large = False                   # the big side-by-side view is showing
        self.pending_tops = None
        self.cmp_img = None
        self.cmp_key = None
        self.split = 0.5
        self._split_imgs = None
        self.stop_flag = threading.Event()
        self.worker = None
        self.embedder = None
        self.cache = None
        self.searching = False
        self.search_started = 0.0
        self._last_grid = 0.0
        self._fit_job = None
        self._split_job = None
        self._size_job = None
        self._close_tries = 0

        self._fonts()
        self._style()
        self._build()

        threading.Thread(target=self._thumb_worker, daemon=True).start()
        self._cache_thread = threading.Thread(target=self._load_index, daemon=True)
        self._cache_thread.start()
        self.after(80, self._poll)
        self.after(10, self._dark_title_bar)
        self.bind_all("<Control-v>", self.paste_photo)
        self.bind_all("<MouseWheel>", self._wheel)
        self.bind("<Escape>", lambda e: self.show_grid())
        self.bind("<Return>", lambda e: self.open_large())
        self.bind("<Left>", lambda e: self.step(-1))
        self.bind("<Right>", lambda e: self.step(1))
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def px(self, n):
        return round(n * self.scale)

    # ---------- look ----------

    def _fonts(self):
        self.f_title = tkfont.Font(family=FONT, size=17, weight="bold")
        self.f_sub = tkfont.Font(family=FONT, size=10)
        self.f_head = tkfont.Font(family=FONT, size=12, weight="bold")
        self.f_body = tkfont.Font(family=FONT, size=10)
        self.f_bold = tkfont.Font(family=FONT, size=10, weight="bold")
        self.f_big = tkfont.Font(family=FONT, size=12, weight="bold")
        self.f_small = tkfont.Font(family=FONT, size=9)
        self.f_tiny = tkfont.Font(family=FONT, size=8, weight="bold")
        families = set(tkfont.families())
        self.icon_font = next((f for f in ("Segoe Fluent Icons", "Segoe MDL2 Assets") if f in families), None)
        self.f_icon = tkfont.Font(family=self.icon_font or FONT, size=11)
        self.f_icon_small = tkfont.Font(family=self.icon_font or FONT, size=9)

    def _style(self):
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure("Violet.Horizontal.TProgressbar", troughcolor=ROOM, background=VIOLET, bordercolor=LINE,
                    lightcolor=VIOLET, darkcolor=VIOLET, thickness=self.px(8))
        s.configure("Dark.Vertical.TScrollbar", background=BTN, troughcolor=PANEL, bordercolor=PANEL,
                    arrowcolor=MUTED, lightcolor=BTN, darkcolor=BTN, gripcount=0)
        s.map("Dark.Vertical.TScrollbar", background=[("active", BTN_LINE)])

    def _dark_title_bar(self):
        try:
            hwnd = ctypes.windll.user32.GetParent(self.winfo_id())
            on = ctypes.c_int(1)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(on), ctypes.sizeof(on))
            self.withdraw()                  # the title bar only repaints dark after a show
            self.deiconify()
        except Exception:
            pass

    def _icon(self, parent, name, fg=MUTED, bg=PANEL, small=False):
        return tk.Label(parent, text=ICONS[name] if self.icon_font else "", bg=bg, fg=fg,
                        font=self.f_icon_small if small else self.f_icon)

    def _panel(self, parent):
        return tk.Frame(parent, bg=PANEL, highlightthickness=1, highlightbackground=LINE)

    def _build(self):
        header = tk.Frame(self, bg=BG, height=self.px(70))
        header.pack(fill="x")
        header.pack_propagate(False)
        try:
            mark = Image.open(ASSETS / "az_mark.png")
            mark = mark.resize((round(mark.width * self.px(30) / mark.height), self.px(30)), Image.LANCZOS)
            self.logo = ImageTk.PhotoImage(mark)
            tk.Label(header, image=self.logo, bg=BG).pack(side="left", padx=(self.px(18), self.px(10)))
            tk.Label(header, text="AZ Inspired", bg=BG, fg=SUB, font=self.f_small).pack(
                side="left", pady=(self.px(14), 0))
        except Exception:
            tk.Label(header, text="AZ Inspired", bg=BG, fg=SUB, font=self.f_bold).pack(side="left", padx=self.px(18))
        tk.Frame(header, bg=LINE, width=1).pack(side="left", fill="y", pady=self.px(16), padx=self.px(18))
        titles = tk.Frame(header, bg=BG)
        titles.pack(side="left")
        tk.Label(titles, text="Design Matcher", bg=BG, fg=HEAD, font=self.f_title).pack(anchor="w")
        tk.Label(titles, text="Find the design that matches a photo  ·  AI, runs offline", bg=BG, fg=SUB,
                 font=self.f_sub).pack(anchor="w")

        status = tk.Frame(self, bg=PANEL, height=self.px(32), highlightthickness=1, highlightbackground=LINE)
        status.pack(side="bottom", fill="x", padx=self.px(12), pady=(0, self.px(10)))
        status.pack_propagate(False)
        self._icon(status, "index", small=True).pack(side="left", padx=(self.px(12), self.px(6)))
        self.index_dot = tk.Label(status, text="●", bg=PANEL, fg=MUTED, font=self.f_small)
        self.index_dot.pack(side="left")
        self.index_note = tk.Label(status, text="Index: reading…", bg=PANEL, fg=SUB, font=self.f_small)
        self.index_note.pack(side="left", padx=(self.px(4), 0))
        tk.Label(status, text=f"AZ Inspired   |   Design Matcher v{VERSION}  ·  works offline, nothing is uploaded",
                 bg=PANEL, fg=MUTED, font=self.f_small).pack(side="right", padx=self.px(12))

        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=self.px(12), pady=(0, self.px(10)))
        side = self._panel(body)
        side.configure(width=self.px(316))
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        self._build_sidebar(side)

        self.cmp_panel = self._panel(body)
        self.cmp_panel.pack(side="right", fill="y")
        self.cmp_panel.pack_propagate(False)
        self._build_compare_panel(self.cmp_panel)

        self.main = self._panel(body)
        self.main.pack(side="left", fill="both", expand=True, padx=self.px(10))
        self._build_grid_view()
        self._build_large_view()
        self.grid_view.pack(fill="both", expand=True)
        self._show_compare_panel(self.compare_open)

    def _step_head(self, parent, number, title, note, top):
        row = tk.Frame(parent, bg=PANEL)
        row.pack(fill="x", padx=self.px(18), pady=(top, 0))
        c = tk.Canvas(row, width=self.px(24), height=self.px(24), bg=PANEL, highlightthickness=0)
        c.create_oval(1, 1, self.px(24) - 1, self.px(24) - 1, fill=VIOLET, outline="")
        c.create_text(self.px(12), self.px(12), text=number, fill="#ffffff", font=self.f_bold)
        c.pack(side="left")
        tk.Label(row, text=title, bg=PANEL, fg=HEAD, font=self.f_head).pack(side="left", padx=(self.px(10), 0))
        tk.Label(parent, text=note, bg=PANEL, fg=MUTED, font=self.f_small, anchor="w", justify="left",
                 wraplength=self.px(270)).pack(fill="x", padx=self.px(18), pady=(self.px(4), self.px(10)))

    def _build_sidebar(self, side):
        pad = {"padx": self.px(18)}
        self._step_head(side, "1", "Customer photo", "Add the customer's photo, e.g. from WhatsApp", self.px(18))
        box = tk.Frame(side, bg=WELL, height=self.px(236), highlightthickness=1, highlightbackground=LINE,
                       cursor="hand2")
        box.pack(fill="x", **pad)
        box.pack_propagate(False)
        self.photo_box = tk.Label(box, bg=WELL, fg=MUTED, font=self.f_body, justify="center", cursor="hand2",
                                  text="No photo yet\n\nClick here to choose one,\nor copy a photo and press Ctrl+V")
        self.photo_box.pack(fill="both", expand=True)
        for w in (box, self.photo_box):
            w.bind("<Button-1>", lambda e: self.choose_photo())
        self.photo_clear = tk.Label(box, text=ICONS["close"] if self.icon_font else "×", bg=BTN, fg=INK,
                                    font=self.f_icon_small, cursor="hand2", padx=self.px(5), pady=self.px(3))
        self.photo_clear.bind("<Button-1>", lambda e: self.clear_photo())
        self.photo_name = tk.Label(side, bg=PANEL, fg=MUTED, font=self.f_small, anchor="w")
        self.photo_name.pack(fill="x", pady=(self.px(5), 0), **pad)
        row = tk.Frame(side, bg=PANEL)
        row.pack(fill="x", pady=(self.px(6), 0), **pad)
        row.columnconfigure((0, 1), weight=1, uniform="b")
        Button(row, self, "Choose photo", self.choose_photo, icon="photo", width=10).grid(
            row=0, column=0, sticky="ew", padx=(0, self.px(4)))
        Button(row, self, "Paste (Ctrl+V)", self.paste_photo, icon="paste", width=10).grid(
            row=0, column=1, sticky="ew", padx=(self.px(4), 0))

        tk.Frame(side, bg=LINE, height=1).pack(fill="x", padx=self.px(18), pady=(self.px(18), 0))
        self._step_head(side, "2", "Search in folder", "Choose the folder that holds your designs (images or PDF files)",
                        self.px(16))
        row = tk.Frame(side, bg=PANEL)
        row.pack(fill="x", **pad)
        # the button first, so it keeps its whole width and the field takes what is left
        Button(row, self, "Choose", self.choose_folder, icon="folder", width=None).pack(
            side="right", padx=(self.px(8), 0), fill="y")
        field = tk.Frame(row, bg=ROOM, highlightthickness=1, highlightbackground=BTN_LINE)
        field.pack(side="left", fill="x", expand=True, ipady=self.px(4))
        self._icon(field, "folder", fg=SUB, bg=ROOM, small=True).pack(side="left", padx=(self.px(8), 0))
        self.folder_entry = tk.Entry(field, textvariable=self.folder, font=self.f_body, bg=ROOM, fg=INK, bd=0,
                                     insertbackground=INK, relief="flat", highlightthickness=0,
                                     selectbackground=VIOLET, selectforeground="#ffffff")
        self.folder_entry.pack(side="left", fill="x", expand=True, padx=self.px(6))
        self.after_idle(lambda: self.folder_entry.xview_moveto(1))
        tk.Label(side, text="Subfolders and every PDF page are searched too.", bg=PANEL, fg=MUTED,
                 font=self.f_small, anchor="w").pack(fill="x", pady=(self.px(6), 0), **pad)

        self.search_btn = Button(side, self, "Find matches", self.toggle_search, kind="accent", icon="search",
                                 height=46, font=self.f_big, width=100)
        self.search_btn.pack(fill="x", pady=(self.px(22), 0), **pad)
        line = tk.Frame(side, bg=PANEL)
        line.pack(fill="x", pady=(self.px(14), 0), **pad)
        self.status_icon = self._icon(line, "check", fg=GREEN, small=True)
        self.status_label = tk.Label(line, textvariable=self.status, bg=PANEL, fg=SUB, font=self.f_small,
                                     anchor="w", justify="left", wraplength=self.px(250))
        self.status_label.pack(side="left", fill="x", expand=True)
        prow = tk.Frame(side, bg=PANEL)
        prow.pack(fill="x", pady=(self.px(8), 0), **pad)
        self.progress = ttk.Progressbar(prow, style="Violet.Horizontal.TProgressbar", mode="determinate")
        self.progress.pack(side="left", fill="x", expand=True)
        self.progress_pct = tk.Label(prow, text="", bg=PANEL, fg=SUB, font=self.f_small, width=5, anchor="e")
        self.progress_pct.pack(side="left")

    def _build_grid_view(self):
        v = self.grid_view = tk.Frame(self.main, bg=PANEL)
        top = tk.Frame(v, bg=PANEL)
        top.pack(fill="x", padx=self.px(18), pady=(self.px(16), 0))
        self._icon(top, "matches", fg=VIOLET_TEXT).pack(side="left", padx=(0, self.px(8)))
        tk.Label(top, text="Closest matches", bg=PANEL, fg=HEAD, font=self.f_head).pack(side="left")
        tk.Label(top, text="  —  best first", bg=PANEL, fg=SUB, font=self.f_body).pack(side="left", pady=(self.px(2), 0))
        self.results_note = tk.Label(top, bg=PANEL, fg=MUTED, font=self.f_small)
        self.results_note.pack(side="right")

        bar = tk.Frame(v, bg=PANEL)
        bar.pack(fill="x", padx=self.px(18), pady=(self.px(12), self.px(12)))
        tk.Label(bar, text="Type:", bg=PANEL, fg=SUB, font=self.f_body).pack(side="left", padx=(0, self.px(8)))
        self.chips = {}
        for key, text, icon in (("all", "All", None), ("img", "Images", "picture"), ("pdf", "PDF pages", "pdf")):
            b = Button(bar, self, text, lambda k=key: self.set_filter(k), kind="chip", icon=icon, height=30,
                       font=self.f_small)
            b.pack(side="left", padx=(0, self.px(6)))
            self.chips[key] = b
        self.chips["all"].set(kind="chip_on")
        self.size_note = tk.Label(bar, bg=PANEL, fg=MUTED, font=self.f_small, width=7, anchor="e")
        self.size_note.pack(side="right")
        self.size_scale = Slider(bar, self, CARD_MIN, CARD_MAX, self.card_w, self._size_moved)
        self.size_scale.pack(side="right", padx=(self.px(8), self.px(6)))
        tk.Label(bar, text="Size:", bg=PANEL, fg=SUB, font=self.f_body).pack(side="right")
        self.size_note.configure(text=f"{self.card_w} px")

        wrap = tk.Frame(v, bg=PANEL)
        wrap.pack(fill="both", expand=True, padx=(self.px(18), self.px(6)), pady=(0, self.px(12)))
        self.canvas = tk.Canvas(wrap, bg=PANEL, highlightthickness=0, yscrollincrement=self.px(24))
        sb = ttk.Scrollbar(wrap, orient="vertical", command=self.canvas.yview, style="Dark.Vertical.TScrollbar")
        self.canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.grid_frame = tk.Frame(self.canvas, bg=PANEL)
        self.canvas.create_window((0, 0), window=self.grid_frame, anchor="nw")
        self.grid_frame.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self._layout_cards())
        self.empty = tk.Label(self.canvas, bg=PANEL, fg=MUTED, font=self.f_body, justify="center",
                              text="Choose a customer photo and a folder, then press Find matches.\n\n"
                                   "The closest designs appear here, best first.")
        self.empty.place(relx=0.5, rely=0.4, anchor="center")

    def _build_compare_panel(self, p):
        self.cmp_full = tk.Frame(p, bg=PANEL)
        head = tk.Frame(self.cmp_full, bg=PANEL)
        head.pack(fill="x", padx=self.px(16), pady=(self.px(16), 0))
        self._icon(head, "compare", fg=VIOLET_TEXT).pack(side="left", padx=(0, self.px(8)))
        tk.Label(head, text="Compare", bg=PANEL, fg=HEAD, font=self.f_head).pack(side="left")
        Button(head, self, "", lambda: self._show_compare_panel(False), kind="ghost", icon="right", height=28,
               width=30).pack(side="right")
        tk.Label(self.cmp_full, text="Customer photo vs. selected match  ·  drag the line", bg=PANEL, fg=MUTED,
                 font=self.f_small, anchor="w").pack(fill="x", padx=self.px(16), pady=(self.px(4), self.px(10)))

        tog = tk.Frame(self.cmp_full, bg=PANEL)
        tog.pack(fill="x", padx=self.px(16))
        tog.columnconfigure((0, 1), weight=1, uniform="t")
        self.tog_photo = Button(tog, self, "Customer photo", lambda: self._set_split(1.0), kind="chip", height=28,
                                font=self.f_small, width=10)
        self.tog_photo.grid(row=0, column=0, sticky="ew", padx=(0, self.px(4)))
        self.tog_match = Button(tog, self, "Match", lambda: self._set_split(0.0), kind="chip", height=28,
                                font=self.f_small, width=10)
        self.tog_match.grid(row=0, column=1, sticky="ew", padx=(self.px(4), 0))

        self.split_canvas = tk.Canvas(self.cmp_full, bg=WELL, highlightthickness=1, highlightbackground=LINE,
                                      cursor="sb_h_double_arrow")
        self.split_canvas.pack(fill="both", expand=True, padx=self.px(16), pady=(self.px(10), 0))
        self.split_canvas.bind("<Configure>", lambda e: self._schedule_split(rebuild=True))
        self.split_canvas.bind("<B1-Motion>", self._split_drag)
        self.split_canvas.bind("<Button-1>", self._split_drag)
        self.split_canvas.bind("<Double-Button-1>", lambda e: self.open_large())

        info = tk.Frame(self.cmp_full, bg=PANEL)
        info.pack(fill="x", padx=self.px(16), pady=(self.px(10), 0))
        self.cmp_name = tk.Label(info, bg=PANEL, fg=HEAD, font=self.f_bold, anchor="w")
        self.cmp_name.pack(fill="x")
        self.cmp_where = tk.Label(info, bg=PANEL, fg=MUTED, font=self.f_small, anchor="w")
        self.cmp_where.pack(fill="x")
        srow = tk.Frame(info, bg=PANEL)
        srow.pack(fill="x", pady=(self.px(8), self.px(3)))
        tk.Label(srow, text="Similarity (AI match)", bg=PANEL, fg=SUB, font=self.f_small).pack(side="left")
        self.cmp_pct = tk.Label(srow, bg=PANEL, fg=HEAD, font=self.f_big)
        self.cmp_pct.pack(side="right")
        self.cmp_bar = tk.Canvas(info, height=self.px(6), bg=PANEL, highlightthickness=0)
        self.cmp_bar.pack(fill="x")
        self.cmp_bar.bind("<Configure>", lambda e: self._draw_cmp_bar())

        self.open_btn = Button(self.cmp_full, self, "Open file", self.open_file, kind="accent", icon="open", height=38,
                               width=100)
        self.open_btn.pack(fill="x", padx=self.px(16), pady=(self.px(12), 0))
        self.folder_btn = Button(self.cmp_full, self, "Show in folder", self.show_in_folder, icon="folder", height=34,
                                 width=100)
        self.folder_btn.pack(fill="x", padx=self.px(16), pady=(self.px(6), 0))
        self.large_btn = Button(self.cmp_full, self, "View side by side", self.open_large, icon="zoom", height=34,
                                width=100)
        self.large_btn.pack(fill="x", padx=self.px(16), pady=(self.px(6), self.px(16)))

        self.cmp_mini = tk.Frame(p, bg=PANEL)
        Button(self.cmp_mini, self, "", lambda: self._show_compare_panel(True), kind="ghost", icon="left", height=30,
               width=30).pack(pady=(self.px(14), self.px(8)))
        c = tk.Canvas(self.cmp_mini, width=self.px(24), height=self.px(90), bg=PANEL, highlightthickness=0)
        c.create_text(self.px(12), self.px(45), text="Compare", angle=90, fill=SUB, font=self.f_small)
        c.pack()
        c.bind("<Button-1>", lambda e: self._show_compare_panel(True))
        self._update_compare()

    def _show_compare_panel(self, on):
        self.compare_open = on
        self.settings["compare_open"] = on
        save_settings(self.settings)
        if on:
            self.cmp_mini.pack_forget()
            self.cmp_panel.configure(width=self.px(340))
            self.cmp_full.pack(fill="both", expand=True)
        else:
            self.cmp_full.pack_forget()
            self.cmp_panel.configure(width=self.px(44))
            self.cmp_mini.pack(fill="both", expand=True)

    def _build_large_view(self):
        v = self.large_view = tk.Frame(self.main, bg=PANEL)
        bar = tk.Frame(v, bg=PANEL)
        bar.pack(fill="x", padx=self.px(18), pady=(self.px(14), self.px(12)))
        Button(bar, self, "Back to results", self.show_grid, icon="left").pack(side="left")
        Button(bar, self, "Next", lambda: self.step(1), icon="right").pack(side="right")
        Button(bar, self, "Previous", lambda: self.step(-1), icon="left").pack(side="right", padx=(0, self.px(8)))
        self.large_pos = tk.Label(bar, bg=PANEL, fg=MUTED, font=self.f_body)
        self.large_pos.pack(side="right", padx=self.px(14))

        panes = tk.Frame(v, bg=PANEL)
        panes.pack(fill="both", expand=True, padx=self.px(18), pady=(0, self.px(18)))
        panes.columnconfigure((0, 1), weight=1, uniform="pane")
        panes.rowconfigure(1, weight=1)
        tk.Label(panes, text="Customer photo", bg=PANEL, fg=HEAD, font=self.f_bold, anchor="w").grid(
            row=0, column=0, sticky="w", pady=(0, self.px(6)))
        self.large_title = tk.Label(panes, bg=PANEL, fg=HEAD, font=self.f_bold, anchor="w")
        self.large_title.grid(row=0, column=1, sticky="w", padx=(self.px(10), 0), pady=(0, self.px(6)))
        self.large_boxes = []
        for col in (0, 1):
            f = tk.Frame(panes, bg=WELL, highlightthickness=1, highlightbackground=LINE)
            f.grid(row=1, column=col, sticky="nsew", padx=(0, self.px(10)) if col == 0 else (self.px(10), 0))
            f.pack_propagate(False)
            lbl = tk.Label(f, bg=WELL, fg=MUTED, font=self.f_body)
            lbl.pack(fill="both", expand=True)
            f.bind("<Configure>", lambda e: self._schedule_fit())
            self.large_boxes.append((f, lbl))

    # ---------- index (what has already been read) ----------

    def _load_index(self):
        try:
            cache = matcher.Cache()
            self.events.put(("index", cache, None))
        except Exception as e:
            self.events.put(("index", None, str(e)))

    def _on_index(self, cache, error):
        if cache is not None and self.cache is None:
            self.cache = cache
        if error:
            self.index_note.configure(text=f"Index: couldn't read it ({error}); it will be rebuilt")
        else:
            n = len(self.cache.entries) if self.cache else 0
            self.index_dot.configure(fg=GREEN if n else MUTED)
            self.index_note.configure(text=f"Index: {n:,} files remembered" if n else
                                      "Index: empty  ·  the first search of a folder builds it")

    # ---------- photo and folder ----------

    def choose_photo(self):
        p = filedialog.askopenfilename(
            title="Choose the customer's photo",
            filetypes=[("Images", "*.jpg *.jpeg *.png *.webp *.bmp *.tif *.tiff"), ("All files", "*.*")])
        if p:
            self._set_photo(lambda: matcher.open_photo(p), Path(p).name)

    def paste_photo(self, event=None):
        if event is not None and isinstance(self.focus_get(), (tk.Entry, ttk.Entry)):
            return  # normal text paste into the folder box
        clip = ImageGrab.grabclipboard()
        if isinstance(clip, Image.Image):
            self._set_photo(lambda: clip.convert("RGB"), "Pasted photo")
            return
        if isinstance(clip, list):
            files = [f for f in clip if Path(f).suffix.lower() in matcher.IMAGE_EXTS]
            if files:
                self._set_photo(lambda: matcher.open_photo(files[0]), Path(files[0]).name)
                return
        self._say("There's no picture on the clipboard. Copy a photo first, then press Ctrl+V.")

    def _set_photo(self, loader, name):
        try:
            img = loader()
        except Exception as e:
            self._say(f"Couldn't open that photo: {e}")
            return
        self.ref_img = img
        self.update_idletasks()
        box = self.photo_box.master
        w, h = box.winfo_width() - self.px(16), box.winfo_height() - self.px(16)
        self.photo_tk = ImageTk.PhotoImage(ImageOps.contain(img, (max(w, 50), max(h, 50)), Image.LANCZOS))
        self.photo_box.configure(image=self.photo_tk, text="")
        self.photo_clear.place(relx=1.0, x=-self.px(8), y=self.px(8), anchor="ne")
        self.photo_name.configure(text=fit_text(name, self.f_small, self.px(270)))
        self._say("")
        self._split_imgs = None
        self._schedule_split(rebuild=True)

    def clear_photo(self):
        self.ref_img = None
        self.photo_tk = None
        self.photo_box.configure(image="", text="No photo yet\n\nClick here to choose one,\n"
                                                 "or copy a photo and press Ctrl+V")
        self.photo_clear.place_forget()
        self.photo_name.configure(text="")
        self._schedule_split(rebuild=True)

    def choose_folder(self):
        start = self.folder.get() if Path(self.folder.get() or ".").is_dir() else None
        p = filedialog.askdirectory(title="Choose the folder to search", initialdir=start)
        if p:
            self.folder.set(str(Path(p)))
            self.folder_entry.xview_moveto(1)

    def _say(self, text, done=False):
        self.status.set(text)
        if done:
            self.status_icon.pack(side="left", padx=(0, self.px(6)), before=self.status_label)
        else:
            self.status_icon.pack_forget()

    # ---------- searching ----------

    def toggle_search(self):
        if self.searching:
            self.stop_flag.set()
            self.search_btn.set(text="Stopping…", enabled=False)
        else:
            self.start_search()

    def start_search(self):
        folder = self.folder.get().strip()
        if self.ref_img is None:
            self._say("Choose the customer photo first.")
            return
        if not folder or not Path(folder).is_dir():
            self._say("Choose a folder that exists.")
            return
        self.settings["folder"] = folder
        save_settings(self.settings)
        self.searching = True
        self.stop_flag.clear()
        self.search_started = time.monotonic()
        self.search_btn.set(text="Stop", kind="normal", icon="close")
        self.progress.configure(value=0, maximum=1)
        self.progress_pct.configure(text="0%")
        self._say("Starting…")
        self.show_grid()
        self.selected = None
        self._set_results({"all": [], "img": [], "pdf": []})
        self.empty.configure(text="Searching…")
        self.worker = threading.Thread(target=self._search_worker, args=(self.ref_img, folder), daemon=True)
        self.worker.start()

    @staticmethod
    def _tops(scored):
        return {"all": heapq.nlargest(TOP_N, scored),
                "img": heapq.nlargest(TOP_N, (s for s in scored if s[2] < 0)),
                "pdf": heapq.nlargest(TOP_N, (s for s in scored if s[2] >= 0))}

    def _search_worker(self, ref_img, folder):
        try:
            self._cache_thread.join()
            if self.embedder is None:
                self.events.put(("status", "Loading the matching model…"))
                self.embedder = matcher.Embedder()
            if self.cache is None:
                self.cache = matcher.Cache()
            done = total = 0
            scored = []
            last = 0.0
            for done, total, scored in matcher.search(ref_img, folder, self.embedder, self.cache,
                                                       self.stop_flag.is_set):
                now = time.monotonic()
                if now - last > 0.25:
                    last = now
                    self.events.put(("progress", done, total, self._tops(scored)))
            self.events.put(("done", done, total, len(scored), self._tops(scored), self.stop_flag.is_set()))
        except Exception as e:
            self.events.put(("error", f"Search failed: {e}"))

    def _poll(self):
        try:
            while True:
                event = self.events.get_nowait()
                getattr(self, "_on_" + event[0])(*event[1:])
        except queue.Empty:
            pass
        self.after(80, self._poll)

    def _on_status(self, text):
        self._say(text)

    def _on_progress(self, done, total, tops):
        self.progress.configure(maximum=max(total, 1), value=done)
        self.progress_pct.configure(text=f"{done * 100 // max(total, 1)}%")
        text = f"Checked {done:,} of {total:,} files."
        elapsed = time.monotonic() - self.search_started
        if elapsed > 8 and done:
            left = elapsed / done * (total - done)
            text += f" About {left / 60:.0f} min left." if left >= 90 else f" About {left:.0f} s left."
        self._say(text + "\nThe first search of a folder is the slow one; after that only new or changed "
                         "files are read.")
        if time.monotonic() - self._last_grid > 1.5:
            self._set_results(tops)

    def _on_done(self, done, total, items, tops, stopped):
        self._finish()
        self.progress.configure(maximum=max(total, 1), value=done)
        self.progress_pct.configure(text=f"{done * 100 // max(total, 1)}%")
        took = time.monotonic() - self.search_started
        took = f"{took:.1f} s" if took < 10 else f"{took:.0f} s" if took < 120 else f"{took / 60:.0f} min"
        if stopped:
            self._say(f"Stopped after {done:,} of {total:,} files. Showing the best so far.")
            if not tops["all"]:
                self.empty.configure(text="Stopped before any files were checked.")
        elif total == 0:
            self._say("No images or PDFs found in that folder.")
            self.empty.configure(text="No images or PDFs found in that folder.")
        else:
            self._say(f"{items:,} images & PDF pages searched in {took}. Look through the top few yourself; "
                      "the percentage is only a guide.", done=True)
        self._set_results(tops)
        if self.cache is not None:
            n = len(self.cache.entries)
            self.index_dot.configure(fg=GREEN)
            self.index_note.configure(text=f"Index: {n:,} files remembered" +
                                      ("" if stopped else f"  ·  up to date for {Path(self.folder.get()).name or self.folder.get()}"))
        if self.results and self.selected is None:
            self.select(0)

    def _on_error(self, text):
        self._finish()
        self.progress.configure(value=0)
        self.progress_pct.configure(text="")
        self._say(text)
        self.empty.configure(text=text)

    def _finish(self):
        self.searching = False
        self.search_btn.set(text="Find matches", kind="accent", enabled=True, icon="search")

    # ---------- results grid ----------

    def set_filter(self, key):
        self.filter = key
        for k, b in self.chips.items():
            b.set(kind="chip_on" if k == key else "chip")
        self._set_results(self.tops, force=True)

    def _size_moved(self, value):
        w = int(float(value))
        if w == self.card_w:
            return
        self.card_w = w
        self.size_note.configure(text=f"{w} px")
        if self._size_job:
            self.after_cancel(self._size_job)
        self._size_job = self.after(120, self._size_done)

    def _size_done(self):
        self._size_job = None
        self.settings["card_w"] = self.card_w
        save_settings(self.settings)
        self._set_results(self.tops, force=True)

    def _set_results(self, tops, force=False):
        if self.large:
            self.pending_tops = tops
            return
        self._last_grid = time.monotonic()
        self.tops = tops
        top = tops[self.filter]
        same = [(p, pg) for _, p, pg in top] == [(p, pg) for _, p, pg in self.results]
        self.results = top
        if same and self.cards and not force:
            return
        for c in self.cards:
            c.destroy()
        self.card_imgs = {}
        self.cards = [self._make_card(i, *r) for i, r in enumerate(top)]
        self._layout_cards()
        if not same:
            self.canvas.yview_moveto(0)
        if top:
            self.empty.place_forget()
            self.results_note.configure(text=f"{len(top)} shown  ·  click one to compare  ·  double-click to enlarge")
        else:
            self.empty.place(relx=0.5, rely=0.4, anchor="center")
            self.results_note.configure(text="")
            if tops["all"] and not self.searching:     # matches exist, just none of this type
                self.empty.configure(text="No " + ("PDF pages" if self.filter == "pdf" else "images") +
                                          " among the files searched.")
        self._update_compare()

    def _thumb_size(self):
        cw = self.px(self.card_w)
        return cw, round(cw * 0.92)

    def _make_card(self, i, score, path, page):
        cw, th = self._thumb_size()
        key = (path, page)
        sel = key == self.selected
        c = tk.Frame(self.grid_frame, bg=ROOM, highlightthickness=self.px(2),
                     highlightbackground=VIOLET if sel else LINE, cursor="hand2")
        tile = tk.Frame(c, bg=WELL, width=cw, height=th)
        tile.pack()
        tile.pack_propagate(False)
        img = tk.Label(tile, bg=WELL, fg=MUTED, font=self.f_small, text="Loading…")
        img.pack(fill="both", expand=True)
        badge = tk.Label(tile, text=f"#{i + 1}", bg=VIOLET if sel else "#2b3246", fg="#ffffff", font=self.f_tiny,
                         padx=self.px(6), pady=self.px(1))
        badge.place(x=self.px(6), y=self.px(6))
        self.card_imgs[key] = img
        self._fill_thumb(key, img)

        info = tk.Frame(c, bg=ROOM, width=cw)
        info.pack(fill="x", padx=self.px(10), pady=(self.px(8), self.px(10)))
        row = tk.Frame(info, bg=ROOM)
        row.pack(fill="x")
        tk.Label(row, text="Similarity", bg=ROOM, fg=MUTED, font=self.f_small).pack(side="left")
        tk.Label(row, text=f"{score * 100:.0f}%", bg=ROOM, fg=HEAD, font=self.f_bold).pack(side="right")
        bar = tk.Canvas(info, height=self.px(4), bg=ROOM, highlightthickness=0, width=cw - self.px(20))
        bar.pack(fill="x", pady=(self.px(3), self.px(7)))
        bw = cw - self.px(20)
        rounded(bar, 0, 0, bw, self.px(4), self.px(2), fill=BTN_LINE, outline="")
        rounded(bar, 0, 0, max(self.px(4), bw * min(max(score, 0.0), 1.0)), self.px(4), self.px(2), fill=VIOLET,
                outline="")
        name = tk.Frame(info, bg=ROOM)
        name.pack(fill="x")
        is_pdf = page >= 0
        self._icon(name, "pdf" if is_pdf else "picture", fg=PDF_RED if is_pdf else PIC_BLUE, bg=ROOM,
                   small=True).pack(side="left", padx=(0, self.px(6)))
        tk.Label(name, text=fit_text(Path(path).name, self.f_bold, cw - self.px(44)), bg=ROOM, fg=INK,
                 font=self.f_bold, anchor="w").pack(side="left", fill="x")
        where = tk.Frame(info, bg=ROOM)
        where.pack(fill="x", pady=(self.px(2), 0))
        self._icon(where, "folder", fg=MUTED, bg=ROOM, small=True).pack(side="left", padx=(0, self.px(6)))
        room = cw - self.px(44)
        if is_pdf:
            tag = tk.Label(where, text=f"PDF page {page + 1}", bg=VIOLET_SOFT, fg=VIOLET_TEXT, font=self.f_tiny,
                           padx=self.px(5))
            tag.pack(side="right")
            room -= self.f_tiny.measure(f"PDF page {page + 1}") + self.px(16)
        tk.Label(where, text=fit_text(str(Path(path).parent), self.f_small, max(room, 30), keep_end=True),
                 bg=ROOM, fg=MUTED, font=self.f_small, anchor="w").pack(side="left", fill="x")

        def hover(on):
            if (path, page) != self.selected:
                c.configure(highlightbackground=HOVER_LINE if on else LINE)

        def bind_all_children(w):
            w.bind("<Button-1>", lambda e: self.select(i))
            w.bind("<Double-Button-1>", lambda e: self.open_large(i))
            for child in w.winfo_children():
                bind_all_children(child)

        bind_all_children(c)
        c.bind("<Enter>", lambda e: hover(True))
        c.bind("<Leave>", lambda e: hover(self._pointer_inside(c, e)))
        c.badge = badge
        c.key = key
        return c

    def _pointer_inside(self, widget, event):
        w = self.winfo_containing(event.x_root, event.y_root)
        while w is not None:
            if w is widget:
                return True
            w = w.master
        return False

    def _layout_cards(self):
        gap = self.px(12)
        cw = self.px(self.card_w) + 2 * self.px(2)
        cols = max(1, (self.canvas.winfo_width() + gap) // (cw + gap))
        for i, c in enumerate(self.cards):
            c.grid(row=i // cols, column=i % cols, padx=(0, gap), pady=(0, gap), sticky="n")

    def _wheel(self, event):
        if self.large:
            return
        w = self.winfo_containing(event.x_root, event.y_root)
        while w is not None:
            if w is self.grid_view:
                self.canvas.yview_scroll(int(-event.delta / 120), "units")
                return
            w = w.master

    def _thumb_worker(self):
        while True:
            key = self.thumb_jobs.get()
            try:
                im = matcher.load_preview(*key, PREVIEW_PX)
            except Exception:
                im = None
            self.events.put(("thumb", key, im))

    def _fill_thumb(self, key, label):
        if key not in self.thumb_src:
            if key not in self.pending_thumbs:
                self.pending_thumbs.add(key)
                self.thumb_jobs.put(key)
            return
        src = self.thumb_src[key]
        if src is None:
            label.configure(text="No preview", image="")
            return
        cw, th = self._thumb_size()
        tk_key = (key, cw)
        if tk_key not in self.thumb_tk:
            self.thumb_tk[tk_key] = ImageTk.PhotoImage(
                ImageOps.contain(src, (cw - self.px(10), th - self.px(10)), Image.LANCZOS))
        label.configure(image=self.thumb_tk[tk_key], text="")

    def _on_thumb(self, key, im):
        self.pending_thumbs.discard(key)
        self.thumb_src[key] = im
        lbl = self.card_imgs.get(key)
        if lbl is not None and lbl.winfo_exists():
            self._fill_thumb(key, lbl)

    # ---------- compare ----------

    def _index_of(self, key):
        for i, (_, p, pg) in enumerate(self.results):
            if (p, pg) == key:
                return i
        return None

    def select(self, i):
        if not 0 <= i < len(self.results):
            return
        _, path, page = self.results[i]
        self.selected = (path, page)
        for c in self.cards:
            on = c.key == self.selected
            c.configure(highlightbackground=VIOLET if on else LINE)
            c.badge.configure(bg=VIOLET if on else "#2b3246")
        self._update_compare()
        self._see_card(i)

    def _see_card(self, i):
        if not 0 <= i < len(self.cards):
            return
        self.update_idletasks()
        c = self.cards[i]
        total = max(self.grid_frame.winfo_height(), 1)
        top, bottom = c.winfo_y(), c.winfo_y() + c.winfo_height()
        v0, v1 = self.canvas.yview()
        if top < v0 * total:
            self.canvas.yview_moveto(top / total)
        elif bottom > v1 * total:
            self.canvas.yview_moveto((bottom - (v1 - v0) * total) / total)

    def _current(self):
        i = self._index_of(self.selected) if self.selected else None
        return (i, *self.results[i]) if i is not None else None

    def _update_compare(self):
        cur = self._current()
        on = cur is not None
        was = self.cmp_key
        for b in (self.open_btn, self.folder_btn, self.large_btn):
            b.set(enabled=on)
        if not on:
            self.cmp_key = None
            self.cmp_img = None
            self.cmp_name.configure(text="No match picked yet")
            self.cmp_where.configure(text="Click a match to compare it with the photo")
            self.cmp_pct.configure(text="")
            self.tog_match.set(text="Match")
        else:
            i, score, path, page = cur
            if self.cmp_key != (path, page):
                self.cmp_key = (path, page)
                try:
                    self.cmp_img = matcher.load_preview(path, page, 1400)
                except Exception:
                    self.cmp_img = None
                self._split_imgs = None
            name = Path(path).name + (f"  ·  page {page + 1}" if page >= 0 else "")
            self.cmp_name.configure(text=fit_text(name, self.f_bold, self.px(300)))
            self.cmp_where.configure(text=fit_text(str(Path(path).parent), self.f_small, self.px(300), keep_end=True))
            self.cmp_pct.configure(text=f"{score * 100:.0f}%")
            self.tog_match.set(text=f"Match (#{i + 1})")
        self._draw_cmp_bar()
        self._schedule_split(rebuild=self.cmp_key != was)
        if self.large:
            self._show_large()

    def _draw_cmp_bar(self):
        c = self.cmp_bar
        c.delete("all")
        w, h = c.winfo_width(), self.px(6)
        if w < 4:
            return
        rounded(c, 0, 0, w, h, h / 2, fill=BTN_LINE, outline="")
        cur = self._current()
        if cur is not None:
            rounded(c, 0, 0, max(h, w * min(max(cur[1], 0.0), 1.0)), h, h / 2, fill=VIOLET, outline="")

    def _set_split(self, value):
        self.split = value
        self._schedule_split()

    def _split_drag(self, e):
        w = self.split_canvas.winfo_width()
        if w > 4:
            self.split = min(max(e.x / w, 0.0), 1.0)
            self._draw_split()

    def _schedule_split(self, rebuild=False):
        if rebuild:
            self._split_imgs = None
        if self._split_job:
            self.after_cancel(self._split_job)
        self._split_job = self.after(30, self._draw_split)

    def _draw_split(self):
        self._split_job = None
        c = self.split_canvas
        w, h = c.winfo_width() - 2, c.winfo_height() - 2
        c.delete("all")
        self.tog_photo.set(kind="chip_on" if self.split >= 0.999 else "chip")
        self.tog_match.set(kind="chip_on" if self.split <= 0.001 else "chip")
        if w < 20 or h < 20:
            return
        if self.ref_img is None and self.cmp_img is None:
            c.create_text(w / 2, h / 2, text="The photo and the match\nshow here side by side", fill=MUTED,
                          font=self.f_small, justify="center")
            return
        if self._split_imgs is None or self._split_imgs[0] != (w, h):
            def framed(im):
                base = Image.new("RGB", (w, h), WELL)
                if im is not None:
                    fit = ImageOps.contain(im, (w, h), Image.LANCZOS)
                    base.paste(fit, ((w - fit.width) // 2, (h - fit.height) // 2))
                return base
            self._split_imgs = ((w, h), framed(self.ref_img), framed(self.cmp_img))
        _, photo, match = self._split_imgs
        x = round(w * self.split)
        out = match.copy()
        if x > 0:
            out.paste(photo.crop((0, 0, x, h)), (0, 0))
        self._split_tk = ImageTk.PhotoImage(out)
        c.create_image(1, 1, image=self._split_tk, anchor="nw")
        if 0 < x < w:
            c.create_line(x + 1, 0, x + 1, h + 2, fill="#ffffff", width=self.px(2))
            r = self.px(13)
            c.create_oval(x + 1 - r, h / 2 - r, x + 1 + r, h / 2 + r, fill="#ffffff", outline="")
            c.create_text(x + 1, h / 2, text="‹ ›", fill=VIOLET, font=self.f_bold)
        pad = self.px(8)
        if x > self.px(90):
            c.create_text(pad, pad, text="Photo", fill="#ffffff", font=self.f_tiny, anchor="nw")
        if w - x > self.px(90):
            c.create_text(w - pad, pad, text="Match", fill="#ffffff", font=self.f_tiny, anchor="ne")

    # ---------- big side-by-side view ----------

    def open_large(self, i=None):
        if isinstance(self.focus_get(), (tk.Entry, ttk.Entry)):
            return
        if i is not None:
            self.select(i)
        if self._current() is None:
            return
        self.large = True
        self.grid_view.pack_forget()
        self.large_view.pack(fill="both", expand=True)
        self._show_large()

    def _show_large(self):
        i, score, path, page = self._current()
        name = Path(path).name + (f"  ·  page {page + 1}" if page >= 0 else "")
        self.large_title.configure(text=f"#{i + 1}   {name}   ({score * 100:.0f}% similar)")
        self.large_pos.configure(text=f"{i + 1} of {len(self.results)}")
        self._schedule_fit()

    def _schedule_fit(self):
        if self._fit_job:
            self.after_cancel(self._fit_job)
        self._fit_job = self.after(40, self._fit_large)

    def _fit_large(self):
        self._fit_job = None
        if not self.large:
            return
        for (frame, lbl), im in zip(self.large_boxes, (self.ref_img, self.cmp_img)):
            w, h = frame.winfo_width() - self.px(20), frame.winfo_height() - self.px(20)
            if im is None or w < 20 or h < 20:
                lbl.configure(image="", text="Couldn't open this file" if im is None and lbl is self.large_boxes[1][1]
                              else "")
                continue
            photo = ImageTk.PhotoImage(ImageOps.contain(im, (w, h), Image.LANCZOS))
            lbl.configure(image=photo, text="")
            lbl.image = photo

    def show_grid(self):
        if not self.large:
            return
        self.large = False
        self.large_view.pack_forget()
        self.grid_view.pack(fill="both", expand=True)
        if self.pending_tops is not None:
            tops, self.pending_tops = self.pending_tops, None
            self._set_results(tops)

    def step(self, delta):
        if isinstance(self.focus_get(), (tk.Entry, ttk.Entry)) or not self.results:
            return
        i = self._index_of(self.selected) if self.selected else None
        self.select(0 if i is None else min(max(i + delta, 0), len(self.results) - 1))

    def open_file(self):
        cur = self._current()
        if cur is not None:
            os.startfile(cur[2])

    def show_in_folder(self):
        cur = self._current()
        if cur is not None:
            subprocess.Popen(f'explorer /select,"{cur[2]}"')

    def on_close(self):
        # let a running search stop and save its index, so the work isn't lost
        if self.worker is not None and self.worker.is_alive() and self._close_tries < 50:
            self._close_tries += 1
            self.stop_flag.set()
            self._say("Saving the index…")
            self.after(100, self.on_close)
            return
        self.destroy()


if __name__ == "__main__":
    App().mainloop()
