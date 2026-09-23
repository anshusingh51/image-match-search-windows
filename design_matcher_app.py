"""
Design Matcher — simple desktop app to find a design in your catalog
that matches a customer's photo.

Run:
    python design_matcher_app.py

- Pick the customer's photo
- Pick the folder to search (e.g. your Doors design folder)
- Click "Search"
- Results show as ranked thumbnails; double-click a result to open the file
"""

import os
import sys
import threading
from pathlib import Path

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import numpy as np
from PIL import Image, ImageTk
import cv2

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tiff", ".gif"}
PDF_EXTS = {".pdf"}

_ORB = cv2.ORB_create(nfeatures=1000)
_BF = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)


def pil_to_gray_cv(img: Image.Image, max_dim=800):
    w, h = img.size
    scale = min(1.0, max_dim / max(w, h))
    if scale < 1.0:
        img = img.resize((int(w * scale), int(h * scale)))
    return np.array(img.convert("L"))


def orb_descriptors(img: Image.Image):
    gray = pil_to_gray_cv(img)
    kp, des = _ORB.detectAndCompute(gray, None)
    return des


def orb_similarity(des_ref, des_cand, ratio=0.75):
    if des_ref is None or des_cand is None or len(des_ref) < 2 or len(des_cand) < 2:
        return 0
    matches = _BF.knnMatch(des_ref, des_cand, k=2)
    good = 0
    for m_n in matches:
        if len(m_n) != 2:
            continue
        m, n = m_n
        if m.distance < ratio * n.distance:
            good += 1
    return good


def iter_candidates(folder: Path):
    """Yield (display_path, PIL.Image) for every image and PDF page found."""
    for path in folder.rglob("*"):
        if not path.is_file():
            continue
        ext = path.suffix.lower()
        if ext in IMAGE_EXTS:
            try:
                img = Image.open(path).convert("RGB")
                yield str(path), img
            except Exception:
                continue
        elif ext in PDF_EXTS:
            try:
                import fitz
                doc = fitz.open(path)
                for page_num in range(len(doc)):
                    page = doc[page_num]
                    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
                    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                    yield f"{path} [page {page_num + 1}]", img
                doc.close()
            except Exception:
                continue


class DesignMatcherApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("AZ Inspired — Design Matcher")
        self.geometry("900x700")

        self.ref_path = tk.StringVar()
        self.folder_path = tk.StringVar()
        self.status = tk.StringVar(value="Pick a reference photo and a folder to search.")
        self.thumbnails = []  # keep refs so images aren't garbage collected

        self._build_ui()

    def _build_ui(self):
        top = ttk.Frame(self, padding=10)
        top.pack(fill="x")

        ttk.Label(top, text="Customer photo:").grid(row=0, column=0, sticky="w")
        ttk.Entry(top, textvariable=self.ref_path, width=60).grid(row=0, column=1, padx=5)
        ttk.Button(top, text="Browse...", command=self.pick_ref).grid(row=0, column=2)

        ttk.Label(top, text="Search folder:").grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(top, textvariable=self.folder_path, width=60).grid(row=1, column=1, padx=5, pady=(6, 0))
        ttk.Button(top, text="Browse...", command=self.pick_folder).grid(row=1, column=2, pady=(6, 0))

        self.search_btn = ttk.Button(top, text="Search", command=self.start_search)
        self.search_btn.grid(row=2, column=1, pady=10)

        ttk.Label(self, textvariable=self.status, padding=(10, 0)).pack(fill="x")

        self.progress = ttk.Progressbar(self, mode="determinate")
        self.progress.pack(fill="x", padx=10)

        # Scrollable results area
        container = ttk.Frame(self)
        container.pack(fill="both", expand=True, padx=10, pady=10)

        canvas = tk.Canvas(container, borderwidth=0)
        scrollbar = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
        self.results_frame = ttk.Frame(canvas)

        self.results_frame.bind(
            "<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        canvas.create_window((0, 0), window=self.results_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

    def pick_ref(self):
        path = filedialog.askopenfilename(
            title="Select customer photo",
            filetypes=[("Images", "*.jpg *.jpeg *.png *.bmp *.webp")],
        )
        if path:
            self.ref_path.set(path)

    def pick_folder(self):
        path = filedialog.askdirectory(title="Select folder to search")
        if path:
            self.folder_path.set(path)

    def start_search(self):
        ref = self.ref_path.get().strip()
        folder = self.folder_path.get().strip()
        if not ref or not Path(ref).is_file():
            messagebox.showerror("Error", "Please select a valid reference photo.")
            return
        if not folder or not Path(folder).is_dir():
            messagebox.showerror("Error", "Please select a valid folder.")
            return

        for w in self.results_frame.winfo_children():
            w.destroy()
        self.thumbnails.clear()

        self.search_btn.config(state="disabled")
        self.status.set("Searching... this can take a while for large folders.")
        self.progress["value"] = 0

        t = threading.Thread(target=self._run_search, args=(ref, folder), daemon=True)
        t.start()

    def _run_search(self, ref, folder):
        try:
            ref_img = Image.open(ref).convert("RGB")
            ref_des = orb_descriptors(ref_img)
            if ref_des is None or len(ref_des) < 2:
                self._set_status("Reference image has too few distinctive features.")
                return

            results = []
            count = 0
            for label, img in iter_candidates(Path(folder)):
                count += 1
                try:
                    des = orb_descriptors(img)
                    score = orb_similarity(ref_des, des)
                except Exception:
                    continue
                results.append((score, label))
                if count % 20 == 0:
                    self._set_status(f"Scanned {count} images...")

            results.sort(key=lambda x: -x[0])
            top = results[:30]

            self.after(0, self._show_results, top, count)
        except Exception as e:
            self._set_status(f"Error: {e}")
            self.after(0, lambda: self.search_btn.config(state="normal"))

    def _set_status(self, text):
        self.after(0, lambda: self.status.set(text))

    def _show_results(self, results, total_scanned):
        self.search_btn.config(state="normal")
        self.status.set(f"Scanned {total_scanned} images. Showing top {len(results)} matches "
                         f"(higher score = more similar). Double-click to open.")

        if not results:
            ttk.Label(self.results_frame, text="No candidate images found.").pack()
            return

        for score, label in results:
            row = ttk.Frame(self.results_frame, padding=5, relief="ridge")
            row.pack(fill="x", pady=3)

            file_path = label.split(" [page")[0]
            thumb = self._make_thumbnail(file_path, label)
            if thumb:
                img_label = tk.Label(row, image=thumb)
                img_label.image = thumb
                img_label.pack(side="left", padx=5)

            tag = "STRONG MATCH" if score >= 40 else ("LIKELY MATCH" if score >= 20 else "possible")
            text = f"[{score}] {tag}\n{label}"
            lbl = ttk.Label(row, text=text, justify="left")
            lbl.pack(side="left", padx=10)

            def open_file(p=file_path):
                os.startfile(p)

            row.bind("<Double-Button-1>", lambda e, p=file_path: os.startfile(p))
            lbl.bind("<Double-Button-1>", lambda e, p=file_path: os.startfile(p))

    def _make_thumbnail(self, file_path, label):
        try:
            if "[page" in label:
                import fitz
                page_num = int(label.split("[page")[1].strip(" ]")) - 1
                doc = fitz.open(file_path)
                pix = doc[page_num].get_pixmap(matrix=fitz.Matrix(0.5, 0.5))
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                doc.close()
            else:
                img = Image.open(file_path).convert("RGB")
            img.thumbnail((120, 120))
            tkimg = ImageTk.PhotoImage(img)
            self.thumbnails.append(tkimg)
            return tkimg
        except Exception:
            return None


if __name__ == "__main__":
    app = DesignMatcherApp()
    app.mainloop()
