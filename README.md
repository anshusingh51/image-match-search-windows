# Design Matcher

Find the design in your catalog that matches a customer's photo. Pick a photo, pick a folder, and the app searches every image and PDF page in it (including subfolders), then shows the closest candidates as ranked thumbnails.

Built for CNC/woodcarving shops: a customer sends an angled phone photo of a carved door, and you need to find the matching design file among thousands.

## Install

Requires Python 3.9+ (Tkinter is included with the standard Windows Python installer).

```
pip install -r requirements.txt
```

## Use

Desktop app:

```
python design_matcher_app.py
```

Command line:

```
python find_matching_design.py customer_photo.jpg "C:\path\to\designs" --top 30
```

## How it works

ORB keypoint matching (OpenCV) compares the shapes and edges of the photo against each candidate, so it tolerates camera angle, crop and lighting differences. PDFs are rendered page by page with PyMuPDF.

The score is a shortlisting tool, not a verdict. A correct match can score low when wood grain and lighting differ a lot, so look at the top 10-15 results yourself.

`--mode hash` in the command-line script is a faster perceptual-hash mode for finding near-duplicate files (resized or re-saved copies).

## License

MIT
