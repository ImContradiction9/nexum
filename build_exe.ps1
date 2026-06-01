# Gera o Nexum.exe único (Windows). Rode na raiz do projeto:
#   powershell -ExecutionPolicy Bypass -File build_exe.ps1
#
# Requer as dependências instaladas (requirements.txt) + pyinstaller.
# Saída: dist\Nexum.exe

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

if (Test-Path dist\Nexum.exe) {
    $tam = [math]::Round((Get-Item dist\Nexum.exe).Length / 1MB, 1)
    Write-Host ""
    Write-Host "==> OK! Gerado dist\Nexum.exe ($tam MB)" -ForegroundColor Green
    Write-Host "    Copie esse unico arquivo para qualquer PC Windows e de duplo-clique."
    Write-Host "    Dados em %APPDATA%\Nexum (ou em data\ ao lado do exe se houver portable.txt)."
} else {
    Write-Host "==> FALHOU: dist\Nexum.exe nao foi gerado." -ForegroundColor Red
    exit 1
}
