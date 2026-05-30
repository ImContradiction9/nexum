# Gera o instalador dist\NexumSetup.exe (Windows). Rode na raiz do projeto:
#   powershell -ExecutionPolicy Bypass -File build_installer.ps1
#
# Passos: (1) rebuilda o dist\Nexum.exe via build_exe.ps1; (2) compila o
# installer.iss com o Inno Setup (ISCC). Requer o Inno Setup 6 instalado
# (winget install JRSoftware.InnoSetup).

$ErrorActionPreference = "Stop"

# 1. Gera o exe único
Write-Host "==> Gerando o executavel..." -ForegroundColor Cyan
& "$PSScriptRoot\build_exe.ps1"
if (-not (Test-Path "$PSScriptRoot\dist\Nexum.exe")) {
    Write-Host "==> FALHOU: dist\Nexum.exe nao existe." -ForegroundColor Red
    exit 1
}

# 2. Localiza o ISCC (compilador do Inno Setup)
$candidatos = @(
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
    "$env:LocalAppData\Programs\Inno Setup 6\ISCC.exe"
)
$iscc = $candidatos | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) {
    Write-Host "==> Inno Setup nao encontrado. Instale com:" -ForegroundColor Red
    Write-Host "    winget install JRSoftware.InnoSetup" -ForegroundColor Yellow
    exit 1
}
Write-Host "==> Usando ISCC: $iscc" -ForegroundColor Cyan

# 3. Lê a versão de app/__init__.py (fonte única de verdade)
$ver = "1.0.0"
$initPy = Get-Content "$PSScriptRoot\app\__init__.py" -Raw
if ($initPy -match '__version__\s*=\s*["'']([0-9][^"'']*)["'']') { $ver = $Matches[1] }
Write-Host "==> Versao: $ver" -ForegroundColor Cyan

# 4. Compila o instalador
& $iscc "/DMyAppVersion=$ver" "$PSScriptRoot\installer.iss"
if ($LASTEXITCODE -ne 0) {
    Write-Host "==> FALHOU: ISCC retornou $LASTEXITCODE." -ForegroundColor Red
    exit 1
}

if (Test-Path "$PSScriptRoot\dist\NexumSetup.exe") {
    $tam = [math]::Round((Get-Item "$PSScriptRoot\dist\NexumSetup.exe").Length / 1MB, 1)
    Write-Host ""
    Write-Host "==> OK! Gerado dist\NexumSetup.exe ($tam MB)" -ForegroundColor Green
    Write-Host "    Entregue esse instalador. Ele cria atalhos (Area de Trabalho + Menu"
    Write-Host "    Iniciar) e guarda os dados em %APPDATA%\Nexum. Nao exige admin."
} else {
    Write-Host "==> FALHOU: dist\NexumSetup.exe nao foi gerado." -ForegroundColor Red
    exit 1
}
