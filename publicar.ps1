# Publica uma release do Nexum no GitHub a partir da sua máquina.
#
# Builda o exe + instalador localmente e publica via GitHub CLI (gh).
#
# Uso:
#   .\publicar.ps1            -> usa a versão atual de app/__init__.py
#   .\publicar.ps1 1.0.3      -> atualiza a versão para 1.0.3 e publica
#
# Pré-requisitos (uma vez só):
#   winget install GitHub.cli      (instala o gh)
#   gh auth login                  (autentica na sua conta)
#   git remote add origin https://github.com/SEU_USUARIO/nexum.git
#
# Obs: alternativa a este script é o GitHub Actions (.github/workflows/release.yml),
# que builda na nuvem só com "git tag vX.Y.Z + git push --tags". Use UM dos dois
# por release — o workflow detecta se a release já foi publicada e não duplica.

param([string]$Versao)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

# 0. Checagens de ambiente -------------------------------------------------
if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    throw "gh CLI nao instalado. Rode: winget install GitHub.cli  (e depois: gh auth login)"
}
gh auth status *> $null
if ($LASTEXITCODE -ne 0) { throw "gh nao autenticado. Rode: gh auth login" }

git rev-parse --is-inside-work-tree *> $null
if ($LASTEXITCODE -ne 0) { throw "Esta pasta nao e um repositorio git." }

git remote get-url origin *> $null
if ($LASTEXITCODE -ne 0) { throw "Remote 'origin' nao configurado. Rode: git remote add origin <url>" }

# 1. Atualiza a versao se foi passada (preserva acentos: UTF-8 sem BOM) -----
$initPath = Join-Path $PSScriptRoot "app\__init__.py"
if ($Versao) {
    if ($Versao -notmatch '^\d+\.\d+\.\d+$') { throw "Versao invalida: '$Versao' (use X.Y.Z, ex: 1.0.3)" }
    $txt = [System.IO.File]::ReadAllText($initPath)
    $txt = [regex]::Replace($txt, '__version__\s*=\s*"[^"]+"', "__version__ = `"$Versao`"")
    [System.IO.File]::WriteAllText($initPath, $txt, (New-Object System.Text.UTF8Encoding($false)))
    Write-Host "==> Versao atualizada para $Versao" -ForegroundColor Cyan
}

# 2. Le a versao atual -----------------------------------------------------
$ver = "0.0.0"
if ((Get-Content $initPath -Raw) -match '__version__\s*=\s*"([0-9][^"]*)"') { $ver = $Matches[1] }
$tag = "v$ver"
Write-Host "==> Publicando $tag" -ForegroundColor Cyan

# 3. Ja existe essa release? ----------------------------------------------
gh release view $tag *> $null
if ($LASTEXITCODE -eq 0) {
    throw "Release $tag ja existe no GitHub. Suba a versao (ex: .\publicar.ps1 1.0.3)."
}

# 4. Builda exe + instalador ----------------------------------------------
& "$PSScriptRoot\build_installer.ps1"
if (-not (Test-Path "$PSScriptRoot\dist\NexumSetup.exe")) {
    throw "Build falhou: dist\NexumSetup.exe nao foi gerado."
}

# 5. Commita o bump (se houve mudanca) e empurra a branch ------------------
git add "app/__init__.py"
git diff --cached --quiet
if ($LASTEXITCODE -ne 0) {
    git commit -m "Release $tag"
    Write-Host "==> Commit do bump criado." -ForegroundColor Cyan
}
git push

# 6. Cria a release (gh cria a tag remota e sobe o instalador) -------------
Write-Host "==> Criando a release e enviando o NexumSetup.exe..." -ForegroundColor Cyan
gh release create $tag "dist\NexumSetup.exe" --title "Nexum $ver" --generate-notes
if ($LASTEXITCODE -ne 0) { throw "Falha ao criar a release via gh." }

Write-Host ""
Write-Host "==> OK! Release $tag publicada com o NexumSetup.exe." -ForegroundColor Green
Write-Host "    As instalacoes do Nexum vao detectar a nova versao no proximo 'verificar'."
