# -*- mode: python ; coding: utf-8 -*-
"""
Spec do PyInstaller para gerar o Nexum.exe único (Windows).

Empacota tudo (Python + libs + templates + static + pypdfium2) num só .exe.
O usuário final NÃO precisa instalar Python nem Poppler.

Build:  pyinstaller Nexum.spec   (ou use build_exe.ps1)
Saída:  dist/Nexum.exe
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

a = Analysis(
    ["run_nexum.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["matplotlib", "numpy", "pandas", "PyInstaller", "pytest"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Nexum",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,            # app de janela (sem console preto)
    disable_windowed_traceback=False,
    icon="app/static/icon.ico",
)
