# -*- mode: python ; coding: utf-8 -*-
"""
Spec do PyInstaller para gerar o Nexum-Dev.exe (Windows) — versão de TESTES.

Idêntico ao Nexum.spec, com duas diferenças:
  - embute o marcador `DEV_BUILD` no bundle → o app sobe em modo DEV
    (banco em %APPDATA%\\Nexum-Dev, porta 8766, badge "DEV"), totalmente
    isolado do Nexum "de verdade";
  - o exe se chama `Nexum-Dev`.

ONEDIR (igual ao Nexum.spec): saída é a pasta dist/Nexum-Dev/.

Build:  pyinstaller Nexum-Dev.spec   (ou use build_exe.ps1 -Dev)
Saída:  dist/Nexum-Dev/Nexum-Dev.exe
"""
from PyInstaller.utils.hooks import collect_all, collect_submodules

datas = [
    ("app/templates", "app/templates"),
    ("app/static", "app/static"),
    ("DEV_BUILD", "."),   # marcador → run_nexum._modo_dev() detecta no bundle
]
binaries = []
hiddenimports = []

# pypdfium2 traz um binário nativo embutido — precisa ir junto.
for pkg in ("pypdfium2", "pypdfium2_raw"):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:
        pass

# uvicorn faz imports dinâmicos (loops/protocolos) — colhe todos os submódulos.
hiddenimports += collect_submodules("uvicorn")
hiddenimports += [
    "anyio",
    "h11",
    "click",
]

# Janela nativa: pywebview (backend Edge WebView2) + pythonnet (.NET).
for pkg in ("webview", "pythonnet", "clr_loader"):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:
        pass
hiddenimports += [
    "webview.platforms.edgechromium",
    "webview.platforms.winforms",
    "clr",
]

# Exportação .xlsx (openpyxl + et_xmlfile, puro Python).
for pkg in ("openpyxl", "et_xmlfile"):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:
        pass

a = Analysis(
    ["run_nexum.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["matplotlib", "numpy", "pandas", "PyInstaller", "pytest",
              "PIL", "Pillow", "pytesseract"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],                       # ONEDIR
    exclude_binaries=True,    # ONEDIR
    name="Nexum-Dev",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon="app/static/icon.ico",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Nexum-Dev",         # gera dist/Nexum-Dev/
)
