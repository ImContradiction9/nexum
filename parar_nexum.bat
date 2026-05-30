@echo off
REM Encerra o servidor do Nexum (caso ele tenha ficado rodando em background)
echo Encerrando processos do Nexum...

REM Mata python.exe rodando uvicorn na porta 8765
for /f "tokens=2" %%p in ('wmic process where "name='python.exe' and CommandLine like '%%uvicorn%%8765%%'" get ProcessId /format:value 2^>nul ^| find "="') do (
    echo Matando python PID %%p
    taskkill /F /PID %%p >nul 2>&1
)

REM Mata pythonw.exe rodando uvicorn na porta 8765
for /f "tokens=2" %%p in ('wmic process where "name='pythonw.exe' and CommandLine like '%%uvicorn%%8765%%'" get ProcessId /format:value 2^>nul ^| find "="') do (
    echo Matando pythonw PID %%p
    taskkill /F /PID %%p >nul 2>&1
)

REM Mata cmd.exe que esta segurando o python
for /f "tokens=2" %%p in ('wmic process where "name='cmd.exe' and CommandLine like '%%uvicorn%%8765%%'" get ProcessId /format:value 2^>nul ^| find "="') do (
    echo Matando cmd PID %%p
    taskkill /F /PID %%p >nul 2>&1
)

echo Pronto.
timeout /t 2 >nul
exit /b 0
