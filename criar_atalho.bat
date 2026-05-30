@echo off
setlocal EnableDelayedExpansion
title Criar atalho do Nexum
REM chcp removido - causa problemas em alguns Windows

echo.
echo  ============================================
echo   CRIAR ATALHO DO NEXUM
echo  ============================================
echo.

REM === Caminhos absolutos com aspas ===
set "PASTA_APP=%~dp0"
if "%PASTA_APP:~-1%"=="\" set "PASTA_APP=%PASTA_APP:~0,-1%"

set "BAT_APP=%PASTA_APP%\Nexum.vbs"
set "ICON_APP=%PASTA_APP%\app\static\icon.ico"

echo Pasta do app:  %PASTA_APP%
echo Script:        %BAT_APP%
echo Icone:         %ICON_APP%
echo.

REM === Verifica que arquivos existem ===
if not exist "%BAT_APP%" (
    echo [ERRO] Nexum.vbs nao encontrado em: %BAT_APP%
    echo.
    echo Voce extraiu o ZIP nessa pasta? Confira se o Nexum.vbs esta junto deste arquivo.
    echo.
    pause
    exit /b 1
)

if not exist "%ICON_APP%" (
    echo [AVISO] icon.ico nao encontrado em: %ICON_APP%
    echo O atalho sera criado, mas com icone padrao do Windows.
    set "ICON_APP="
    echo.
)

REM === Caminho da Desktop ===
REM Pega via PowerShell pra suportar OneDrive Desktop e idiomas diferentes
for /f "delims=" %%i in ('powershell -NoProfile -Command "[Environment]::GetFolderPath('Desktop')"') do set "DESKTOP=%%i"

if "%DESKTOP%"=="" (
    set "DESKTOP=%USERPROFILE%\Desktop"
)

set "ATALHO=%DESKTOP%\Nexum.lnk"
echo Desktop:       %DESKTOP%
echo Atalho final:  %ATALHO%
echo.

REM === Cria o atalho usando PowerShell ===
echo Criando atalho...

set "PS_CMD=$ws = New-Object -ComObject WScript.Shell;"
set "PS_CMD=%PS_CMD% $s = $ws.CreateShortcut('%ATALHO%');"
set "PS_CMD=%PS_CMD% $s.TargetPath = '%BAT_APP%';"
set "PS_CMD=%PS_CMD% $s.WorkingDirectory = '%PASTA_APP%';"
if defined ICON_APP set "PS_CMD=%PS_CMD% $s.IconLocation = '%ICON_APP%';"
set "PS_CMD=%PS_CMD% $s.WindowStyle = 1;"
set "PS_CMD=%PS_CMD% $s.Description = 'Nexum - Control. Grow. Prosper.';"
set "PS_CMD=%PS_CMD% $s.Save();"
set "PS_CMD=%PS_CMD% Write-Host 'OK' -ForegroundColor Green"

powershell -NoProfile -ExecutionPolicy Bypass -Command "%PS_CMD%"

if errorlevel 1 (
    echo.
    echo [ERRO] PowerShell falhou ao criar atalho.
    echo.
    echo Possiveis causas:
    echo  - Politica de seguranca do PowerShell bloqueando
    echo  - Nome de arquivo com caracteres especiais no caminho
    echo  - Permissoes da Desktop bloqueadas
    echo.
    echo Tente executar este script como Administrador
    echo (clique direito no .bat e escolha "Executar como administrador").
    echo.
    pause
    exit /b 1
)

REM === Verifica se realmente criou ===
if not exist "%ATALHO%" (
    echo.
    echo [ERRO] Atalho nao foi criado, mesmo sem erro do PowerShell.
    echo Verifique permissao da pasta Desktop.
    pause
    exit /b 1
)

echo.
echo  ============================================
echo   [OK] Atalho criado com sucesso!
echo  ============================================
echo.
echo Local: %ATALHO%
echo.
echo Use o atalho "Nexum" na sua Desktop pra abrir o aplicativo.
echo Voce tambem pode arrastar pra barra de tarefas pra fixar.
echo.
echo Se o icone aparecer borrado/errado, reinicie o Windows Explorer:
echo  1. Ctrl+Shift+Esc
echo  2. Encontre "Windows Explorer" na lista
echo  3. Clique com botao direito - "Reiniciar"
echo.
pause
