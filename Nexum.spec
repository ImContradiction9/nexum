# -*- mode: python ; coding: utf-8 -*-
"""
Spec do PyInstaller para gerar o Nexum (Windows) em modo ONEDIR (pasta).

Empacota tudo (Python + libs + templates + static + pypdfium2) numa PASTA
`dist/Nexum/` com `Nexum.exe` + `_internal/`. O usuário final NÃO precisa
instalar Python nem Poppler.

POR QUE ONEDIR (e não onefile): o onefile extrai tudo pro %TEMP%\\_MEIxxxx a
CADA execução; na 1ª abertura após um auto-update o Windows Defender varre o
exe novo e a corrida com a extração quebra o carregamento do python314.dll
("Failed to load Python DLL ... módulo não encontrado"). Onedir não extrai
nada em runtime → o erro some.

Build:  pyinstaller Nexum.spec   (ou use build_exe.ps1)
Saída:  dist/Nexum/Nexum.exe (+ dist/Nexum/_internal/)
"""
from PyInstaller.utils.hooks import collect_all, collect_submodules

datas = [
    ("app/templates", "app/templates"),
    ("app/static", "app/static"),
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
    # OCR é opcional; se a lib não estiver no ambiente de build, PyInstaller ignora.
]

# Janela nativa: pywebview (backend Edge WebView2) + pythonnet (.NET). Traz as
# DLLs Microsoft.Web.WebView2.* e o runtime do pythonnet (Python.Runtime.dll).
# Se faltar no ambiente de build, o app cai pro navegador em runtime.
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
              "PIL", "Pillow", "pytesseract"],   # OCR removido (~16 MB)
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],                       # ONEDIR: binários/datas vão no COLLECT, não no exe
    exclude_binaries=True,    # ONEDIR
    name="Nexum",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,            # app de janela (sem console preto)
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
    name="Nexum",             # gera dist/Nexum/ (Nexum.exe + _internal/)
)
