# -*- mode: python ; coding: utf-8 -*-
#
# Regenerate with: pyi-makespec --onefile --console --name asgi-webdav standalone.py
# Keep these manual fixes after regenerating:
# - upx=False (avoids broken code signature on macOS and antivirus false
#   positives on Windows)
# - datas bundles asgi_webdav/static, served via Path(__file__).parent/static
#   in asgi_webdav/server.py


a = Analysis(
    ['standalone.py'],
    pathex=[],
    binaries=[],
    datas=[('asgi_webdav/static', 'asgi_webdav/static')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='asgi-webdav',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
