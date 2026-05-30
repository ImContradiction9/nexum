@echo off
title Nexum DIAGNOSTICO

echo.
echo ============================================
echo   DIAGNOSTICO DE INICIALIZACAO DO NEXUM
echo ============================================
echo.

echo [1] Pasta atual: %~dp0
echo.

echo [2] Verificando Python...
where python
if errorlevel 1 (
    echo    ERRO: Python nao encontrado.
    pause
    exit /b 1
)
echo    OK
echo.

echo [3] Versao do Python:
python --version
echo.

echo [4] Verificando se fastapi esta instalado...
python -c "import fastapi; print('   FastAPI versao', fastapi.__version__)"
if errorlevel 1 (
    echo    FastAPI nao instalado, tentando instalar...
    pip install -r "%~dp0requirements.txt"
    if errorlevel 1 (
        echo    ERRO: pip install falhou
        pause
        exit /b 1
    )
)
echo.

echo [5] Verificando pytesseract...
python -c "import pytesseract; print('   pytesseract OK')"
if errorlevel 1 (
    echo    pytesseract nao instalado, instalando...
    pip install pytesseract Pillow pypdfium2
)
echo.

echo [6] Verificando pdftotext...
where pdftotext
if errorlevel 1 (
    echo    AVISO: pdftotext nao esta instalado.
)
echo.

echo [7] Verificando estrutura de pastas...
if exist "%~dp0app\main.py" (
    echo    app/main.py: OK
) else (
    echo    ERRO: app/main.py nao encontrado em %~dp0app\
)
echo.

echo [8] Tentando subir servidor (pressione Ctrl+C pra cancelar)...
echo.
cd /d "%~dp0"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8765

echo.
echo Servidor encerrado.
pause
