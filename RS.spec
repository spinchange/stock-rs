# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = []
binaries = []
hiddenimports = ['peewee']
tmp_ret = collect_all('plotly')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('curl_cffi')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('yfinance')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


excludes = [
    # Heavy packages pulled in via pandas' optional deps but unused by this app.
    'scipy', 'pyarrow', 'duckdb', 'psycopg2', 'psycopg2cffi',
    'matplotlib', 'IPython', 'PIL', 'sqlalchemy', 'numba',
    'openpyxl', 'xlrd', 'xlsxwriter', 'tables', 'xarray', 'tkinter',
    # Qt modules a WebEngine-widgets app never touches.
    'PySide6.Qt3DAnimation', 'PySide6.Qt3DCore', 'PySide6.Qt3DExtras',
    'PySide6.Qt3DInput', 'PySide6.Qt3DLogic', 'PySide6.Qt3DRender',
    'PySide6.QtCharts', 'PySide6.QtDataVisualization',
    'PySide6.QtGraphs', 'PySide6.QtGraphsWidgets',
    'PySide6.QtMultimedia', 'PySide6.QtMultimediaWidgets', 'PySide6.QtSpatialAudio',
    'PySide6.QtBluetooth', 'PySide6.QtNfc', 'PySide6.QtSensors',
    'PySide6.QtSerialBus', 'PySide6.QtSerialPort',
    'PySide6.QtDesigner', 'PySide6.QtUiTools', 'PySide6.QtHelp',
    'PySide6.QtSql', 'PySide6.QtTest',
    'PySide6.QtScxml', 'PySide6.QtStateMachine', 'PySide6.QtRemoteObjects',
    'PySide6.QtTextToSpeech', 'PySide6.QtQuick3D',
    'PySide6.QtLocation', 'PySide6.QtPositioning',
    'PySide6.QtPdf', 'PySide6.QtPdfWidgets',
    'PySide6.QtNetworkAuth', 'PySide6.QtWebView', 'PySide6.QtWebSockets',
]

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='RS',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='RS',
)
