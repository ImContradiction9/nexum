# Gera o Nexum em modo ONEDIR (pasta dist\Nexum\ com Nexum.exe + _internal\).
# Rode na raiz do projeto:
#   powershell -ExecutionPolicy Bypass -File build_exe.ps1
#
# Requer as dependências instaladas (requirements.txt) + pyinstaller.
# Saída: dist\Nexum\Nexum.exe

$ErrorActionPreference = "Stop"

# Python a usar. No CI definimos NEXUM_PYTHON com o caminho do python.org 3.14
# (o exe gerado por OUTROS builds de Python não carrega em algumas máquinas).
# Localmente, cai no 'python' do PATH.
$py = if ($env:NEXUM_PYTHON) { $env:NEXUM_PYTHON } else { "python" }
Write-Host "==> Python do build: $py" -ForegroundColor Cyan
& $py --version

Write-Host "==> Instalando dependencias de runtime + build..." -ForegroundColor Cyan
& $py -m pip install -r requirements.txt
& $py -m pip install pyinstaller

Write-Host "==> Limpando builds anteriores..." -ForegroundColor Cyan
if (Test-Path build) { Remove-Item -Recurse -Force build }
if (Test-Path dist)  { Remove-Item -Recurse -Force dist }

Write-Host "==> Empacotando com PyInstaller (pode levar alguns minutos)..." -ForegroundColor Cyan
& $py -m PyInstaller --clean --noconfirm Nexum.spec

if (Test-Path dist\Nexum\Nexum.exe) {
    $tam = [math]::Round(((Get-ChildItem dist\Nexum -Recurse | Measure-Object Length -Sum).Sum) / 1MB, 1)
    Write-Host ""
    Write-Host "==> OK! Gerada a pasta dist\Nexum\ ($tam MB) com Nexum.exe + _internal\" -ForegroundColor Green
    Write-Host "    Distribua via instalador (build_installer.ps1). Onedir = sem extracao _MEI em runtime."
    Write-Host "    Dados em %APPDATA%\Nexum (ou em data\ ao lado do exe se houver portable.txt)."
} else {
    Write-Host "==> FALHOU: dist\Nexum\Nexum.exe nao foi gerado." -ForegroundColor Red
    exit 1
}
