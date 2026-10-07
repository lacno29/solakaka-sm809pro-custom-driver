# PyInstaller spec for the SM809 Pro app.
#   build:  pyinstaller SM809Pro.spec      (or run build_exe.bat)
#   output: dist/SM809Pro.exe  (single file, no console window)
#
# Portable: config (macros.json / profiles.json) is written next to the .exe at
# runtime (see app/paths.py app_dir()), so the single exe + its config/ folder
# can be copied between machines.

from PyInstaller.utils.hooks import collect_dynamic_libs

# bundle the hidapi DLL the `hid` module loads at runtime
binaries = collect_dynamic_libs("hid") + collect_dynamic_libs("hidapi")

# bundle read-only resources (the numbered mouse reference image)
datas = [("images", "images")]

block_cipher = None

a = Analysis(
    ["run_app.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=["hid"],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "PySide6.QtWebEngineCore", "PySide6.Qt3DCore"],
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="SM809Pro",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    runtime_tmpdir=None,
    console=False,            # no terminal window
    disable_windowed_traceback=False,
    icon="images/icon.ico",   # the .exe file icon
)
