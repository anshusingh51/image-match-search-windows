"""
Find images/PDF pages in a folder that look like a reference photo.

Usage:
    python find_matching_design.py <reference_image> <search_folder> [--mode ai|hash] [--top 25]

Scans the folder and its subfolders and prints the closest images and PDF pages, best first.

- ai (default): compares what the designs look like, using a small local AI model.
  Works for a phone photo of a finished piece against catalogue images. The first
  search of a folder is slow; later ones only read new or changed files.
- hash: difference hash, for near-duplicate files (resized or re-saved copies).
  Hamming distance, lower = more similar; 0-5 is effectively the same image.
"""

import argparse
import sys
from pathlib import Path

import matcher


def main():
    ap = argparse.ArgumentParser(description="Find images and PDF pages that look like a reference photo.")
    ap.add_argument("reference", help="Path to the reference photo")
    ap.add_argument("folder", help="Folder to search, including subfolders")
    ap.add_argument("--mode", choices=["ai", "hash"], default="ai",
                    help="'ai' (default) for a photo of a real piece vs design images; "
                         "'hash' for near-duplicate files")
    ap.add_argument("--threshold", type=int, default=15,
                    help="hash mode only: max Hamming distance to count as a match (default 15)")
    ap.add_argument("--top", type=int, default=25, help="Show at most this many results (default: 25)")
    args = ap.parse_args()

    if not Path(args.reference).is_file():
        sys.exit(f"Reference image not found: {args.reference}")
    if not Path(args.folder).is_dir():
        sys.exit(f"Search folder not found: {args.folder}")
    ref = matcher.open_photo(args.reference)
    print(f"Reference: {args.reference}  (mode: {args.mode})")

    if args.mode == "hash":
        import imagehash

        ref_hash = imagehash.dhash(ref, hash_size=16)
        results = []
        for path in matcher.list_files(args.folder):
            try:
                for page, img in matcher.iter_images(path):
                    results.append((ref_hash - imagehash.dhash(img, hash_size=16), matcher.label(path, page)))
            except Exception as e:
                print(f"  [skip] {path}: {e}", file=sys.stderr)
        results.sort(key=lambda r: r[0])
        print(f"\nScanned {len(results)} images/pages.")
        matches = [r for r in results if r[0] <= args.threshold]
        if matches:
            print(f"Within distance {args.threshold} (lower = more similar):")
        else:
            print(f"Nothing within distance {args.threshold}. Closest anyway:")
            matches = results
        for dist, name in matches[:args.top]:
            print(f"  [{dist:3d}] {name}")
        return

    embedder, cache = matcher.Embedder(), matcher.Cache()
    done = total = 0
    scored = []
    for done, total, scored in matcher.search(ref, args.folder, embedder, cache):
        if done % 250 == 0:
            print(f"  ...{done}/{total} files", file=sys.stderr)
    scored.sort(reverse=True)
    print(f"\nScanned {total} files ({len(scored)} images/pages). Closest {min(args.top, len(scored))}, best first:")
    for rank, (score, path, page) in enumerate(scored[:args.top], 1):
        print(f"  #{rank:<3d} {score * 100:4.0f}%  {matcher.label(path, page)}")


if __name__ == "__main__":
    main()
