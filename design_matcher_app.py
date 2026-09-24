"""Design Matcher: find the design in your folders that matches a customer's photo.

Run:  python design_matcher_app.py
"""

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

NAVY = "#1A3A8C"
NAVY_DARK = "#142D6E"
NAVY_SOFT = "#E8EDF8"
NAVY_MUTED = "#C9D3EE"
INK = "#222222"
MUTED = "#6B7280"
LINE = "#E3E5EA"
BG = "#F5F5F5"
WHITE = "#FFFFFF"
TILE = "#EEF0F3"
FONT = "Segoe UI"

TOP_N = 30
CARD_W, THUMB_H, GAP = 196, 184, 14
PHOTO_BOX = 256
SETTINGS = matcher.data_dir() / "settings.json"


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


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Design Matcher")
        self.geometry("1280x820")
        self.minsize(980, 720)
        self.configure(bg=BG)

        self.settings = load_settings()
        self.folder = tk.StringVar(value=self.settings.get("folder", ""))
        self.status = tk.StringVar()
        self.ref_img = None
        self.events = queue.Queue()
        self.thumb_jobs = queue.Queue()
        self.thumbs = {}
        self.pending_thumbs = set()
        self.card_imgs = {}
        self.cards = []
        self.results = []
        self.pending_results = None
        self.compare_index = None
        self.cmp_img = None
        self.stop_flag = threading.Event()
        self.worker = None
        self.embedder = None
        self.cache = None
        self.searching = False
        self.search_started = 0.0
        self._last_grid = 0.0
        self._fit_job = None
        self._close_tries = 0

        self._fonts()
        self._style()
        self._build()

        threading.Thread(target=self._thumb_worker, daemon=True).start()
        self.after(80, self._poll)
        self.bind_all("<Control-v>", self.paste_photo)
        self.bind_all("<MouseWheel>", self._wheel)
        self.bind("<Escape>", lambda e: self.show_grid())
        self.bind("<Left>", lambda e: self.step(-1))
        self.bind("<Right>", lambda e: self.step(1))
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    # ---------- look ----------

    def _fonts(self):
        self.f_title = tkfont.Font(family=FONT, size=15, weight="bold")
        self.f_sub = tkfont.Font(family=FONT, size=10)
        self.f_head = tkfont.Font(family=FONT, size=11, weight="bold")
        self.f_body = tkfont.Font(family=FONT, size=10)
        self.f_bold = tkfont.Font(family=FONT, size=10, weight="bold")
        self.f_small = tkfont.Font(family=FONT, size=9)

    def _style(self):
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure("TButton", font=(FONT, 10), padding=(12, 7), background=WHITE, foreground=INK,
                    bordercolor=LINE, lightcolor=WHITE, darkcolor=WHITE, focuscolor=WHITE)
        s.map("TButton", background=[("disabled", BG), ("active", NAVY_SOFT)],
              foreground=[("disabled", "#A0A4AB")])
        s.configure("Accent.TButton", font=(FONT, 11, "bold"), padding=(12, 10), background=NAVY,
                    foreground=WHITE, bordercolor=NAVY, lightcolor=NAVY, darkcolor=NAVY, focuscolor=NAVY)
        s.map("Accent.TButton", background=[("disabled", "#9AA6C8"), ("active", NAVY_DARK)],
              lightcolor=[("active", NAVY_DARK)], darkcolor=[("active", NAVY_DARK)],
              foreground=[("disabled", WHITE)])
        s.configure("Stop.TButton", font=(FONT, 11, "bold"), padding=(12, 10), background=WHITE,
                    foreground=NAVY, bordercolor=NAVY, lightcolor=WHITE, darkcolor=WHITE, focuscolor=WHITE)
        s.map("Stop.TButton", background=[("active", NAVY_SOFT), ("disabled", BG)],
              foreground=[("disabled", "#A0A4AB")])
        s.configure("TEntry", fieldbackground=WHITE, bordercolor=LINE, lightcolor=LINE, darkcolor=LINE,
                    padding=6)
        s.configure("Navy.Horizontal.TProgressbar", troughcolor="#E6E8EC", background=NAVY,
                    bordercolor="#E6E8EC", lightcolor=NAVY, darkcolor=NAVY)
        s.configure("Vertical.TScrollbar", background="#D5D8DE", troughcolor=BG, bordercolor=BG,
                    arrowcolor=MUTED, lightcolor="#D5D8DE", darkcolor="#D5D8DE")

    def _build(self):
        header = tk.Frame(self, bg=NAVY, height=64)
        header.pack(fill="x")
        header.pack_propagate(False)
        tk.Label(header, text="Design Matcher", bg=NAVY, fg=WHITE, font=self.f_title).pack(side="left", padx=(22, 14))
        tk.Label(header, text="Find the design in your folders that matches a photo", bg=NAVY,
                 fg=NAVY_MUTED, font=self.f_sub).pack(side="left", pady=(4, 0))
        tk.Label(header, text="AZ INSPIRED", bg=NAVY, fg=NAVY_MUTED, font=(FONT, 9, "bold")).pack(side="right", padx=22)

        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True)
        side = tk.Frame(body, bg=WHITE, width=300, highlightthickness=1, highlightbackground=LINE)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        self._build_sidebar(side)

        self.main = tk.Frame(body, bg=BG)
        self.main.pack(side="left", fill="both", expand=True)
        self._build_grid_view()
        self._build_compare_view()
        self.grid_view.pack(fill="both", expand=True)

    def _section(self, parent, number, title, top):
        row = tk.Frame(parent, bg=WHITE)
        row.pack(fill="x", padx=22, pady=(top, 10))
        tk.Label(row, text=number, bg=NAVY, fg=WHITE, font=self.f_bold, width=2).pack(side="left")
        tk.Label(row, text=title, bg=WHITE, fg=INK, font=self.f_head).pack(side="left", padx=(10, 0))

    def _build_sidebar(self, side):
        pad = {"padx": 22}
        self._section(side, "1", "Customer photo", 22)
        box = tk.Frame(side, bg=TILE, width=PHOTO_BOX, height=PHOTO_BOX, cursor="hand2")
        box.pack(**pad)
        box.pack_propagate(False)
        self.photo_box = tk.Label(box, bg=TILE, fg=MUTED, font=self.f_body, justify="center", cursor="hand2",
                                  text="No photo yet\n\nClick here to choose one,\nor copy a photo and press Ctrl+V")
        self.photo_box.pack(fill="both", expand=True)
        for w in (box, self.photo_box):
            w.bind("<Button-1>", lambda e: self.choose_photo())
        self.photo_name = tk.Label(side, bg=WHITE, fg=MUTED, font=self.f_small, anchor="w")
        self.photo_name.pack(fill="x", pady=(6, 0), **pad)
        row = tk.Frame(side, bg=WHITE)
        row.pack(fill="x", pady=(6, 0), **pad)
        ttk.Button(row, text="Choose photo…", command=self.choose_photo).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Paste", command=self.paste_photo).pack(side="left", padx=(8, 0))

        self._section(side, "2", "Search in folder", 24)
        self.folder_entry = ttk.Entry(side, textvariable=self.folder, font=(FONT, 10))
        self.folder_entry.pack(fill="x", **pad)
        self.after_idle(lambda: self.folder_entry.xview_moveto(1))
        ttk.Button(side, text="Choose folder…", command=self.choose_folder).pack(fill="x", pady=(8, 0), **pad)
        tk.Label(side, text="Subfolders and every PDF page are searched too.", bg=WHITE, fg=MUTED,
                 font=self.f_small, anchor="w", justify="left", wraplength=PHOTO_BOX - 8).pack(fill="x", pady=(6, 0), **pad)

        self.search_btn = ttk.Button(side, text="Search", style="Accent.TButton", command=self.toggle_search)
        self.search_btn.pack(fill="x", pady=(26, 0), **pad)
        self.progress = ttk.Progressbar(side, style="Navy.Horizontal.TProgressbar", mode="determinate")
        self.progress.pack(fill="x", pady=(14, 0), **pad)
        tk.Label(side, textvariable=self.status, bg=WHITE, fg=MUTED, font=self.f_small, anchor="w",
                 justify="left", wraplength=PHOTO_BOX - 8).pack(fill="x", pady=(8, 0), **pad)

    def _build_grid_view(self):
        v = self.grid_view = tk.Frame(self.main, bg=BG)
        top = tk.Frame(v, bg=BG)
        top.pack(fill="x", padx=24, pady=(18, 12))
        tk.Label(top, text="Closest matches", bg=BG, fg=INK, font=self.f_head).pack(side="left")
        self.results_note = tk.Label(top, bg=BG, fg=MUTED, font=self.f_small)
        self.results_note.pack(side="left", padx=(12, 0), pady=(2, 0))

        wrap = tk.Frame(v, bg=BG)
        wrap.pack(fill="both", expand=True, padx=(24, 8), pady=(0, 14))
        self.canvas = tk.Canvas(wrap, bg=BG, highlightthickness=0, yscrollincrement=24)
        sb = ttk.Scrollbar(wrap, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.grid_frame = tk.Frame(self.canvas, bg=BG)
        self.canvas.create_window((0, 0), window=self.grid_frame, anchor="nw")
        self.grid_frame.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self._layout_cards())
        self.empty = tk.Label(self.canvas, bg=BG, fg=MUTED, font=self.f_body, justify="center",
                              text="Choose a customer photo and a folder, then press Search.\n\n"
                                   "The closest designs appear here, best first.")
        self.empty.place(relx=0.5, rely=0.4, anchor="center")

    def _build_compare_view(self):
        v = self.compare_view = tk.Frame(self.main, bg=BG)
        bar = tk.Frame(v, bg=BG)
        bar.pack(fill="x", padx=24, pady=(16, 12))
        ttk.Button(bar, text="←  Back to results", command=self.show_grid).pack(side="left")
        ttk.Button(bar, text="Next  ›", command=lambda: self.step(1)).pack(side="right")
        ttk.Button(bar, text="‹  Previous", command=lambda: self.step(-1)).pack(side="right", padx=(0, 8))
        self.cmp_pos = tk.Label(bar, bg=BG, fg=MUTED, font=self.f_body)
        self.cmp_pos.pack(side="right", padx=14)

        panes = tk.Frame(v, bg=BG)
        panes.pack(fill="both", expand=True, padx=24)
        panes.columnconfigure((0, 1), weight=1, uniform="pane")
        panes.rowconfigure(1, weight=1)
        tk.Label(panes, text="Customer photo", bg=BG, fg=INK, font=self.f_bold, anchor="w").grid(
            row=0, column=0, sticky="w", pady=(0, 6))
        self.cmp_title = tk.Label(panes, bg=BG, fg=INK, font=self.f_bold, anchor="w")
        self.cmp_title.grid(row=0, column=1, sticky="w", padx=(10, 0), pady=(0, 6))
        self.cmp_boxes = []
        for col in (0, 1):
            f = tk.Frame(panes, bg=TILE)
            f.grid(row=1, column=col, sticky="nsew", padx=(0, 10) if col == 0 else (10, 0))
            f.pack_propagate(False)
            lbl = tk.Label(f, bg=TILE, fg=MUTED, font=self.f_body)
            lbl.pack(fill="both", expand=True)
            f.bind("<Configure>", lambda e: self._schedule_fit())
            self.cmp_boxes.append((f, lbl))

        bottom = tk.Frame(v, bg=BG)
        bottom.pack(fill="x", padx=24, pady=(12, 18))
        ttk.Button(bottom, text="Show in folder", command=self.show_in_folder).pack(side="right")
        ttk.Button(bottom, text="Open file", style="Accent.TButton", command=self.open_file).pack(
            side="right", padx=(0, 8))
        self.cmp_path = tk.Label(bottom, bg=BG, fg=MUTED, font=self.f_small, anchor="w")
        self.cmp_path.pack(side="left", fill="x", expand=True)

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
        self.status.set("There's no picture on the clipboard. Copy a photo first, then press Ctrl+V.")

    def _set_photo(self, loader, name):
        try:
            img = loader()
        except Exception as e:
            self.status.set(f"Couldn't open that photo: {e}")
            return
        self.ref_img = img
        self.photo_tk = ImageTk.PhotoImage(ImageOps.contain(img, (PHOTO_BOX - 12, PHOTO_BOX - 12)))
        self.photo_box.configure(image=self.photo_tk, text="")
        self.photo_name.configure(text=fit_text(name, self.f_small, PHOTO_BOX))
        self.status.set("")

    def choose_folder(self):
        start = self.folder.get() if Path(self.folder.get() or ".").is_dir() else None
        p = filedialog.askdirectory(title="Choose the folder to search", initialdir=start)
        if p:
            self.folder.set(str(Path(p)))
            self.folder_entry.xview_moveto(1)

    # ---------- searching ----------

    def toggle_search(self):
        if self.searching:
            self.stop_flag.set()
            self.search_btn.configure(text="Stopping…", state="disabled")
        else:
            self.start_search()

    def start_search(self):
        folder = self.folder.get().strip()
        if self.ref_img is None:
            self.status.set("Choose the customer photo first.")
            return
        if not folder or not Path(folder).is_dir():
            self.status.set("Choose a folder that exists.")
            return
        self.settings["folder"] = folder
        save_settings(self.settings)
        self.searching = True
        self.stop_flag.clear()
        self.search_started = time.monotonic()
        self.search_btn.configure(text="Stop", style="Stop.TButton")
        self.progress.configure(value=0, maximum=1)
        self.status.set("Starting…")
        self.show_grid()
        self._set_results([])
        self.empty.configure(text="Searching…")
        self.worker = threading.Thread(target=self._search_worker, args=(self.ref_img, folder), daemon=True)
        self.worker.start()

    def _search_worker(self, ref_img, folder):
        try:
            if self.embedder is None:
                self.events.put(("status", "Loading the matching model…"))
                self.embedder = matcher.Embedder()
                self.cache = matcher.Cache()
            done = total = 0
            scored = []
            last = 0.0
            for done, total, scored in matcher.search(ref_img, folder, self.embedder, self.cache,
                                                       self.stop_flag.is_set):
                now = time.monotonic()
                if now - last > 0.25:
                    last = now
                    self.events.put(("progress", done, total, heapq.nlargest(TOP_N, scored)))
            self.events.put(("done", done, total, heapq.nlargest(TOP_N, scored), self.stop_flag.is_set()))
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
        self.status.set(text)

    def _on_progress(self, done, total, top):
        self.progress.configure(maximum=max(total, 1), value=done)
        text = f"Checked {done:,} of {total:,} files."
        elapsed = time.monotonic() - self.search_started
        if elapsed > 8 and done:
            left = elapsed / done * (total - done)
            text += f" About {left / 60:.0f} min left." if left >= 90 else f" About {left:.0f} s left."
        self.status.set(text + "\nThe first search of a folder is the slow one; after that only new "
                               "or changed files are read.")
        if time.monotonic() - self._last_grid > 1.5:
            self._set_results(top)

    def _on_done(self, done, total, top, stopped):
        self._finish()
        self.progress.configure(maximum=max(total, 1), value=done)
        if stopped:
            self.status.set(f"Stopped after {done:,} of {total:,} files. Showing the best so far.")
            if not top:
                self.empty.configure(text="Stopped before any files were checked.")
        elif total == 0:
            self.status.set("No images or PDFs found in that folder.")
            self.empty.configure(text="No images or PDFs found in that folder.")
        else:
            self.status.set(f"Searched {total:,} files in {time.monotonic() - self.search_started:.0f} s. "
                            "Look through the top few yourself; the percentage is only a guide.")
        self._set_results(top)

    def _on_error(self, text):
        self._finish()
        self.progress.configure(value=0)
        self.status.set(text)
        self.empty.configure(text=text)

    def _finish(self):
        self.searching = False
        self.search_btn.configure(text="Search", style="Accent.TButton", state="normal")

    # ---------- results grid ----------

    def _set_results(self, top):
        if self.compare_index is not None:
            self.pending_results = top
            return
        self._last_grid = time.monotonic()
        if [(p, pg) for _, p, pg in top] == [(p, pg) for _, p, pg in self.results] and self.cards:
            return
        self.results = top
        for c in self.cards:
            c.destroy()
        self.card_imgs = {}
        self.cards = [self._make_card(i, *r) for i, r in enumerate(top)]
        self._layout_cards()
        self.canvas.yview_moveto(0)
        if top:
            self.empty.place_forget()
            self.results_note.configure(text=f"{len(top)} shown, best first  ·  click one to compare it with the photo")
        else:
            self.empty.place(relx=0.5, rely=0.4, anchor="center")
            self.results_note.configure(text="")

    def _make_card(self, i, score, path, page):
        c = tk.Frame(self.grid_frame, bg=WHITE, highlightthickness=1, highlightbackground=LINE, cursor="hand2")
        tile = tk.Frame(c, bg=TILE, width=CARD_W, height=THUMB_H)
        tile.pack()
        tile.pack_propagate(False)
        img = tk.Label(tile, bg=TILE, fg=MUTED, font=self.f_small, text="Loading…")
        img.pack(fill="both", expand=True)
        key = (path, page)
        self.card_imgs[key] = img
        if key in self.thumbs:
            self._show_thumb(img, self.thumbs[key])
        elif key not in self.pending_thumbs:
            self.pending_thumbs.add(key)
            self.thumb_jobs.put(key)

        info = tk.Frame(c, bg=WHITE)
        info.pack(fill="x", padx=10, pady=(8, 10))
        head = tk.Frame(info, bg=WHITE)
        head.pack(fill="x")
        tk.Label(head, text=f"#{i + 1}", bg=WHITE, fg=NAVY, font=self.f_bold).pack(side="left")
        if page >= 0:
            tk.Label(head, text=f"page {page + 1}", bg=NAVY_SOFT, fg=NAVY, font=self.f_small, padx=5).pack(
                side="left", padx=(8, 0))
        tk.Label(head, text=f"{score * 100:.0f}% similar", bg=WHITE, fg=MUTED, font=self.f_small).pack(side="right")
        tk.Label(info, text=fit_text(Path(path).name, self.f_bold, CARD_W - 20), bg=WHITE, fg=INK, font=self.f_bold,
                 anchor="w").pack(fill="x", pady=(4, 0))
        tk.Label(info, text=fit_text(str(Path(path).parent), self.f_small, CARD_W - 20, keep_end=True),
                 bg=WHITE, fg=MUTED, font=self.f_small, anchor="w").pack(fill="x")

        def hover(on):
            c.configure(highlightbackground=NAVY if on else LINE)

        def bind_all_children(w):
            w.bind("<Button-1>", lambda e: self.open_compare(i))
            for child in w.winfo_children():
                bind_all_children(child)

        bind_all_children(c)
        c.bind("<Enter>", lambda e: hover(True))
        c.bind("<Leave>", lambda e: hover(self._pointer_inside(c, e)))
        return c

    def _pointer_inside(self, widget, event):
        w = self.winfo_containing(event.x_root, event.y_root)
        while w is not None:
            if w is widget:
                return True
            w = w.master
        return False

    def _layout_cards(self):
        cols = max(1, (self.canvas.winfo_width() + GAP) // (CARD_W + 2 + GAP))
        for i, c in enumerate(self.cards):
            c.grid(row=i // cols, column=i % cols, padx=(0, GAP), pady=(0, GAP), sticky="n")

    def _wheel(self, event):
        if self.compare_index is None:
            self.canvas.yview_scroll(int(-event.delta / 120), "units")

    def _thumb_worker(self):
        while True:
            key = self.thumb_jobs.get()
            try:
                im = ImageOps.contain(matcher.load_preview(*key, THUMB_H * 2), (CARD_W - 12, THUMB_H - 12),
                                      Image.LANCZOS)
            except Exception:
                im = None
            self.events.put(("thumb", key, im))

    def _on_thumb(self, key, im):
        self.pending_thumbs.discard(key)
        self.thumbs[key] = ImageTk.PhotoImage(im) if im is not None else None
        lbl = self.card_imgs.get(key)
        if lbl is not None and lbl.winfo_exists():
            self._show_thumb(lbl, self.thumbs[key])

    def _show_thumb(self, label, photo):
        if photo is None:
            label.configure(text="No preview")
        else:
            label.configure(image=photo, text="")

    # ---------- compare view ----------

    def open_compare(self, i):
        if not 0 <= i < len(self.results):
            return
        self.compare_index = i
        score, path, page = self.results[i]
        try:
            self.cmp_img = matcher.load_preview(path, page, 1400)
        except Exception:
            self.cmp_img = None
            self.cmp_boxes[1][1].configure(image="", text="Couldn't open this file")
        name = Path(path).name + (f"  ·  page {page + 1}" if page >= 0 else "")
        self.cmp_title.configure(text=f"#{i + 1}   {name}   ({score * 100:.0f}% similar)")
        self.update_idletasks()
        room = self.main.winfo_width() - 330
        self.cmp_path.configure(text=fit_text(matcher.label(path, page), self.f_small, room, keep_end=True))
        self.cmp_pos.configure(text=f"{i + 1} of {len(self.results)}")
        self.grid_view.pack_forget()
        self.compare_view.pack(fill="both", expand=True)
        self._schedule_fit()

    def _schedule_fit(self):
        if self._fit_job:
            self.after_cancel(self._fit_job)
        self._fit_job = self.after(40, self._fit_compare)

    def _fit_compare(self):
        self._fit_job = None
        if self.compare_index is None:
            return
        for (frame, lbl), im in zip(self.cmp_boxes, (self.ref_img, self.cmp_img)):
            w, h = frame.winfo_width() - 20, frame.winfo_height() - 20
            if im is None or w < 20 or h < 20:
                continue
            photo = ImageTk.PhotoImage(ImageOps.contain(im, (w, h), Image.LANCZOS))
            lbl.configure(image=photo, text="")
            lbl.image = photo

    def show_grid(self):
        if self.compare_index is None:
            return
        self.compare_index = None
        self.compare_view.pack_forget()
        self.grid_view.pack(fill="both", expand=True)
        if self.pending_results is not None:
            top, self.pending_results = self.pending_results, None
            self._set_results(top)

    def step(self, delta):
        if self.compare_index is None or isinstance(self.focus_get(), (tk.Entry, ttk.Entry)):
            return
        self.open_compare(min(max(self.compare_index + delta, 0), len(self.results) - 1))

    def open_file(self):
        if self.compare_index is not None:
            os.startfile(self.results[self.compare_index][1])

    def show_in_folder(self):
        if self.compare_index is not None:
            subprocess.Popen(f'explorer /select,"{self.results[self.compare_index][1]}"')

    def on_close(self):
        # let a running search stop and save its index, so the work isn't lost
        if self.worker is not None and self.worker.is_alive() and self._close_tries < 50:
            self._close_tries += 1
            self.stop_flag.set()
            self.status.set("Saving the index…")
            self.after(100, self.on_close)
            return
        self.destroy()


if __name__ == "__main__":
    App().mainloop()
