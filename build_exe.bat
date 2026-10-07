@echo off
REM Build the SM809 Pro app into a single portable .exe (no console window).
REM Output: dist\SM809Pro.exe
REM Requires: pip install pyinstaller  (plus PySide6 + hidapi, already used by the app)
echo Building SM809Pro.exe ...
python -m PyInstaller --noconfirm SM809Pro.spec
echo.
echo Done. See dist\SM809Pro.exe
pause
