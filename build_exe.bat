@echo off
rem Builds dist\DesignMatcher.exe: one file with Python, the model and the logo inside.
rem Needs: pip install pyinstaller -r requirements.txt
cd /d "%~dp0"
python -m PyInstaller --noconfirm --onefile --windowed --name DesignMatcher ^
  --icon assets\az.ico --add-data "models;models" --add-data "assets;assets" ^
  --exclude-module imagehash --exclude-module pygame --exclude-module matplotlib ^
  --exclude-module scipy --exclude-module torch --exclude-module cv2 --exclude-module pandas ^
  design_matcher_app.py
