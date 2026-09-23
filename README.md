# Design Matcher

**Forgot where you saved that design? Search your folders by picture instead of by file name.**

Give the app a photo and a folder. It looks through every image **and every page of every PDF** in that folder and all its subfolders, then shows the closest matches as ranked thumbnails. Double-click a result to open the file.

Useful for designers and workshops with thousands of designs, catalogues and images scattered across folders and PDFs, where file names like `IMG_0042.jpg` don't tell you anything.

![Design Matcher screenshot](docs/screenshot.png)

*Example: a rotated, darker, blurred photo finds the original design (score 346), and also lists a matching page inside a PDF catalogue.*

### What it can do

- Match a photo against images: JPG, PNG, WEBP, BMP, TIFF, GIF
- Match against PDFs, page by page, and show which page matched
- Search a whole folder tree, including subfolders
- Cope with a different camera angle, crop, lighting or wood colour than the stored design
- Run fully offline on a normal PC: no AI model, no GPU, no account, nothing uploaded

Built for CNC and woodcarving shops: a customer sends an angled phone photo of a carved door, and you need to find the matching design file among thousands.

## Download (Windows, no Python needed)

1. Go to the [latest release](https://github.com/anshusingh51/image-match-search-windows/releases/latest)
2. Download **DesignMatcher.exe**
3. Double-click it

The file is about 90 MB because it carries its own copy of Python and OpenCV. Nothing is installed and nothing leaves your PC.

Windows may show a blue "Windows protected your PC" screen the first time, because the exe is not code-signed (that costs money each year). Click **More info**, then **Run anyway**. Some antivirus programs also flag any unsigned single-file exe made this way. If you prefer not to trust a downloaded exe, run it from source instead (below) and read the code, it is two short files.

## Run from source (Python)

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
