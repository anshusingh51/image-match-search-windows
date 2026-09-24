"""Matching engine: ranks images and PDF pages by how much they look like a reference photo.

Each image is described by a DINOv2 model looking at three squares along its long side
(top, middle, bottom of a door). Two images are compared square by square. Descriptions
are cached on disk, so only new or changed files are processed on later searches.
"""

import os
import sys
from pathlib import Path

import numpy as np
import onnxruntime as ort
import pymupdf
from PIL import Image, ImageOps

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tiff", ".tif", ".gif"}
PDF_EXTS = {".pdf"}
MODEL_FILE = "dinov2-small-quantized.onnx"
CACHE_NAME = "index-dinov2s-3sq-v1.npz"
SQUARES = 3
DIM = 384

_MEAN = np.array([0.485, 0.456, 0.406], np.float32)
_STD = np.array([0.229, 0.224, 0.225], np.float32)


def app_dir():
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))


def data_dir():
    d = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "DesignMatcher"
    d.mkdir(parents=True, exist_ok=True)
    return d


def label(path, page):
    return f"{path} [page {page + 1}]" if page >= 0 else str(path)


def list_files(folder):
    exts = IMAGE_EXTS | PDF_EXTS
    return sorted(p for p in Path(folder).resolve().rglob("*") if p.suffix.lower() in exts and p.is_file())


def open_photo(path):
    return ImageOps.exif_transpose(Image.open(path)).convert("RGB")


def _open_image(path, size):
    im = Image.open(path)
    im.draft("RGB", (size, size))
    return ImageOps.exif_transpose(im).convert("RGB")


def _render_page(page, short_side=None, long_side=None):
    r = page.rect
    zoom = short_side / max(1.0, min(r.width, r.height)) if short_side else long_side / max(1.0, r.width, r.height)
    zoom = min(zoom, 2000 / max(1.0, r.width, r.height))
    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


def iter_images(path, size=320):
    """Yield (page, image) for a file; page is -1 for a plain image."""
    if Path(path).suffix.lower() in PDF_EXTS:
        with pymupdf.open(path) as doc:
            for i, page in enumerate(doc):
                yield i, _render_page(page, short_side=size)
    else:
        yield -1, _open_image(path, size)


def load_preview(path, page, size):
    """An image of the file (or PDF page) that fits in a size x size box."""
    if page >= 0:
        with pymupdf.open(path) as doc:
            return _render_page(doc[page], long_side=size)
    im = _open_image(path, size)
    im.thumbnail((size, size), Image.LANCZOS)
    return im


def _squares(img):
    w, h = img.size
    s = 256 / min(w, h)
    img = img.resize((max(256, round(w * s)), max(256, round(h * s))), Image.BICUBIC)
    w, h = img.size
    out = []
    for k in range(SQUARES):
        if h >= w:
            left, top = (w - 224) // 2, round((h - 224) * k / (SQUARES - 1))
        else:
            left, top = round((w - 224) * k / (SQUARES - 1)), (h - 224) // 2
        out.append(img.crop((left, top, left + 224, top + 224)))
    return out


class Embedder:
    def __init__(self, model_path=None):
        path = model_path or app_dir() / "models" / MODEL_FILE
        self.session = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])

    def embed(self, img):
        x = np.stack([(np.asarray(c, np.float32) / 255 - _MEAN) / _STD for c in _squares(img)])
        v = self.session.run(None, {"pixel_values": x.transpose(0, 3, 1, 2)})[0][:, 0]
        return v / np.linalg.norm(v, axis=1, keepdims=True)


class Cache:
    """Per-file descriptions, keyed by path + size + modified time so edited files are redone."""

    def __init__(self, path=None):
        self.path = Path(path) if path else data_dir() / CACHE_NAME
        self.entries = {}
        self.used = set()
        try:
            with np.load(self.path, allow_pickle=False) as z:
                keys, counts, pages, vecs = z["keys"], z["counts"], z["pages"], z["vecs"]
            ends = np.cumsum(counts)
            for key, end, n in zip(keys, ends, counts):
                self.entries[str(key)] = (pages[end - n:end], vecs[end - n:end])
        except FileNotFoundError:
            pass
        except Exception:
            self.entries = {}  # unreadable cache: rebuild it

    def get(self, path, embedder):
        st = path.stat()
        key = f"{path}|{st.st_size}|{st.st_mtime_ns}"
        self.used.add(key)
        if key not in self.entries:
            pages, vecs = [], []
            try:
                for page, img in iter_images(path):
                    pages.append(page)
                    vecs.append(embedder.embed(img))
            except Exception:
                pass  # unreadable file: stored as empty so it isn't retried on every search
            self.entries[key] = (np.array(pages, np.int32),
                                 np.array(vecs, np.float16).reshape(-1, SQUARES, DIM))
        return self.entries[key]

    def save(self, folder=None, complete=False):
        entries = self.entries
        if folder and complete:
            prefix = str(Path(folder).resolve()) + os.sep
            entries = {k: v for k, v in entries.items() if k in self.used or not k.startswith(prefix)}
        keys = list(entries)
        tmp = self.path.with_suffix(".tmp")
        with open(tmp, "wb") as f:
            np.savez(f,
                     keys=np.array(keys, dtype=str),
                     counts=np.array([len(entries[k][0]) for k in keys], np.int64),
                     pages=np.concatenate([entries[k][0] for k in keys] or [np.zeros(0, np.int32)]),
                     vecs=np.concatenate([entries[k][1] for k in keys] or [np.zeros((0, SQUARES, DIM), np.float16)]))
        os.replace(tmp, self.path)


def search(ref_img, folder, embedder, cache, stop=lambda: False):
    """Yield (files_done, files_total, scored) while scanning; scored holds (score, path, page)."""
    ref = embedder.embed(ref_img)
    files = list_files(folder)
    scored = []
    complete = False
    try:
        yield 0, len(files), scored
        for i, path in enumerate(files, 1):
            if stop():
                return
            try:
                pages, vecs = cache.get(path, embedder)
            except OSError:
                continue  # deleted or locked since the folder was listed
            if len(pages):
                sims = np.einsum("pkd,kd->p", vecs.astype(np.float32), ref) / SQUARES
                scored.extend((float(s), str(path), int(p)) for s, p in zip(sims, pages))
            yield i, len(files), scored
        complete = True
    finally:
        cache.save(folder, complete)
