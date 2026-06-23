# PyInstaller spec for the N-SIM Lab Controller GUI.
#
# Build with:
#     .venv\Scripts\pyinstaller LabController.spec
#
# Produces a single windowed executable at dist\LabController.exe. The build
# script (build.bat) also copies config.json next to the .exe so device COM
# ports can be edited without rebuilding.

block_cipher = None


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    # Bundle a default config.json inside the exe as a fallback. An editable
    # copy next to the .exe takes precedence (see MainWindow._config_search_paths).
    datas=[('src/configs/config.json', 'src/configs')],
    hiddenimports=[
        'pyqtgraph',
        'minimalmodbus',
        'serial',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Trim large, unused parts of the scientific stack to keep the exe smaller.
    excludes=[
        'tkinter',
        'PyQt5',
        'PySide6',
        'pytest',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
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
    name='LabController',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # GUI app: no console window
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
