"""
Find images/PDFs in a folder that visually match a reference photo.

Usage:
    python find_matching_design.py <reference_image> <search_folder> [--threshold 10] [--top 20]

How it works:
- Computes a perceptual hash (pHash) of the reference photo. Perceptual hashing
  encodes the visual "shape" of an image into a fingerprint that stays similar
  even if the file is resized, re-compressed, cropped slightly, or re-saved as
  a different format. This makes it robust to the kind of variation you get
  when the same design has been exported/scanned multiple times.
- Recursively scans the search folder for .jpg/.jpeg/.png/.bmp/.webp/.pdf files.
- For PDFs, renders every page to an image (via PyMuPDF) and hashes each page
  separately, since a PDF may contain the design on any page.
- Compares every candidate hash to the reference hash using Hamming distance
  (number of differing bits). Lower distance = more similar.
    0        = identical / near-identical
    1-10     = very likely the same design
    11-20    = possibly related / similar design
    20+      = probably unrelated
- Prints a ranked list of matches (best first), and optionally copies the best
  matches to a "matches" subfolder for quick review.
"""

import argparse
import sys
from pathlib import Path

import numpy as np
from PIL import Image
import imagehash
import cv2

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tiff", ".gif"}
PDF_EXTS = {".pdf"}

# ORB feature matcher: shared across calls for speed
_ORB = cv2.ORB_create(nfeatures=1000)
_BF = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)


def hash_image(img: Image.Image):
    # dhash (difference hash): pure numpy, no scipy/pywt dependency needed
    # (this machine's Smart App Control policy blocks scipy's compiled DLLs)
    return imagehash.dhash(img, hash_size=16)


def hash_reference(path: Path):
    img = Image.open(path).convert("RGB")
    return hash_image(img)


def pil_to_gray_cv(img: Image.Image, max_dim=800):
    """Convert PIL image to a size-capped grayscale OpenCV array (for speed)."""
    w, h = img.size
    scale = min(1.0, max_dim / max(w, h))
    if scale < 1.0:
        img = img.resize((int(w * scale), int(h * scale)))
    arr = np.array(img.convert("L"))
    return arr


def orb_descriptors(img: Image.Image):
    gray = pil_to_gray_cv(img)
    kp, des = _ORB.detectAndCompute(gray, None)
    return des


def orb_similarity(des_ref, des_cand, ratio=0.75):
    """Return count of good keypoint matches (higher = more similar shape/pattern)."""
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
            except Exception as e:
                print(f"  [skip] {path}: {e}", file=sys.stderr)
        elif ext in PDF_EXTS:
            try:
                import fitz  # PyMuPDF
                doc = fitz.open(path)
                for page_num in range(len(doc)):
                    page = doc[page_num]
                    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))  # 2x zoom for quality
                    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                    label = f"{path} [page {page_num + 1}]"
                    yield label, img
                doc.close()
            except Exception as e:
                print(f"  [skip] {path}: {e}", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser(description="Find images/PDFs matching a reference photo.")
    ap.add_argument("reference", help="Path to the reference photo")
    ap.add_argument("folder", help="Folder to search recursively")
    ap.add_argument("--mode", choices=["hash", "features"], default="features",
                     help="'hash' = fast, for near-duplicate files (resized/recompressed). "
                          "'features' = ORB keypoint matching, robust to angle/perspective/lighting "
                          "-- use this for a customer's phone photo of a physical door vs your catalog "
                          "design images. Default: features")
    ap.add_argument("--threshold", type=int, default=None,
                     help="hash mode: max Hamming distance to count as a match (default 15). "
                          "features mode: min good keypoint matches to count as a match (default 15).")
    ap.add_argument("--top", type=int, default=25,
                     help="Show at most this many results (default: 25)")
    args = ap.parse_args()

    ref_path = Path(args.reference)
    folder = Path(args.folder)

    if not ref_path.is_file():
        print(f"Reference image not found: {ref_path}")
        sys.exit(1)
    if not folder.is_dir():
        print(f"Search folder not found: {folder}")
        sys.exit(1)

    print(f"Reference: {ref_path}  (mode: {args.mode})")
    ref_img = Image.open(ref_path).convert("RGB")

    if args.mode == "hash":
        threshold = args.threshold if args.threshold is not None else 15
        ref_hash = hash_image(ref_img)
    else:
        threshold = args.threshold if args.threshold is not None else 15
        ref_des = orb_descriptors(ref_img)
        if ref_des is None or len(ref_des) < 2:
            print("Could not find enough distinctive features in the reference image.")
            sys.exit(1)

    results = []
    count = 0
    for label, img in iter_candidates(folder):
        count += 1
        try:
            if args.mode == "hash":
                h = hash_image(img)
                score = ref_hash - h  # Hamming distance, lower = more similar
            else:
                des = orb_descriptors(img)
                score = orb_similarity(ref_des, des)  # good matches, higher = more similar
        except Exception as e:
            print(f"  [skip] {label}: {e}", file=sys.stderr)
            continue
        results.append((score, label))
        if count % 25 == 0:
            print(f"  ...scanned {count} images so far")

    print(f"\nScanned {count} images/pages under {folder}\n")

    if args.mode == "hash":
        results.sort(key=lambda x: x[0])
        matches = [r for r in results if r[0] <= threshold]
        if not matches:
            print(f"No matches found within threshold {threshold}. Closest results anyway:")
            matches = results[:args.top]
        else:
            print(f"Matches within threshold {threshold} (lower distance = more similar):")
        for score, label in matches[:args.top]:
            tag = "IDENTICAL/NEAR-IDENTICAL" if score <= 5 else ("LIKELY MATCH" if score <= 10 else "POSSIBLE MATCH")
            print(f"  [{score:4d}] {tag:25s} {label}")
    else:
        results.sort(key=lambda x: -x[0])
        matches = [r for r in results if r[0] >= threshold]
        if not matches:
            print(f"No matches found with at least {threshold} good keypoint matches. Closest results anyway:")
            matches = results[:args.top]
        else:
            print(f"Matches with at least {threshold} good keypoint matches (higher = more similar):")
        for score, label in matches[:args.top]:
            tag = "STRONG MATCH" if score >= 40 else ("LIKELY MATCH" if score >= 20 else "POSSIBLE MATCH")
            print(f"  [{score:4d}] {tag:15s} {label}")


if __name__ == "__main__":
    main()
