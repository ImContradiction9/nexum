' ============================================================
' Nexum - Launcher Silencioso (zero janelas)
'
' Faz TUDO sem mostrar nenhuma janela:
'   1. Verifica Python (instalado e libs presentes)
'   2. Se libs faltam, mostra MsgBox pedindo pra rodar instalar_deps.bat
'   3. Sobe servidor uvicorn em background com pythonw
'   4. Aguarda servidor responder
'   5. Abre Chrome em modo app
'   6. Monitora - quando Chrome fechar, mata servidor
' ============================================================

Option Explicit

Const PORTA = 8765
Const URL_HEALTH = "http://127.0.0.1:8765/api/health"

Dim objShell, objFSO, scriptDir
Set objShell = CreateObject("WScript.Shell")
Set objFSO = CreateObject("Scripting.FileSystemObject")
scriptDir = objFSO.GetParentFolderName(WScript.ScriptFullName)
objShell.CurrentDirectory = scriptDir

' ============================================================
' [0a] Localizar Poppler (pdftotext) e injetar no PATH da sessao
' ============================================================
' O INSTALAR.bat coloca o Poppler em Documents\Nexum\poppler, mas o setx
' so afeta sessoes futuras. Aqui procuramos o pdftotext.exe e adicionamos
' ao PATH desta sessao do VBS - assim funciona mesmo sem reiniciar o PC.
Dim popplerBin, pastasPoppler, pp

popplerBin = ""

' Lista de pastas onde o Poppler pode estar
pastasPoppler = Array( _
    objShell.ExpandEnvironmentStrings("%USERPROFILE%\Documents\Nexum\poppler"), _
    scriptDir & "\poppler", _
    objFSO.GetParentFolderName(scriptDir) & "\poppler", _
    "C:\poppler", _
    "C:\Program Files\poppler" _
)

For Each pp In pastasPoppler
    If objFSO.FolderExists(pp) Then
        ' Procura pdftotext.exe recursivamente
        popplerBin = AcharPdftotext(pp)
        If popplerBin <> "" Then Exit For
    End If
Next

' Se achou, injeta no PATH da sessao
If popplerBin <> "" Then
    Dim pathAtual
    pathAtual = objShell.Environment("PROCESS")("PATH")
    If InStr(1, pathAtual, popplerBin, vbTextCompare) = 0 Then
        objShell.Environment("PROCESS")("PATH") = popplerBin & ";" & pathAtual
    End If
End If

' Funcao auxiliar: busca pdftotext.exe dentro de uma pasta (recursivo)
Function AcharPdftotext(pasta)
    AcharPdftotext = ""
    Dim fso2, arq, subPasta, resultadoRec
    Set fso2 = CreateObject("Scripting.FileSystemObject")
    If Not fso2.FolderExists(pasta) Then Exit Function
    On Error Resume Next
    ' Checa arquivos desta pasta
    For Each arq In fso2.GetFolder(pasta).Files
        If LCase(arq.Name) = "pdftotext.exe" Then
            AcharPdftotext = pasta
            Exit Function
        End If
    Next
    ' Recursao nas subpastas
    For Each subPasta In fso2.GetFolder(pasta).SubFolders
        resultadoRec = AcharPdftotext(subPasta.Path)
        If resultadoRec <> "" Then
            AcharPdftotext = resultadoRec
            Exit Function
        End If
    Next
    On Error Goto 0
End Function

' ============================================================
' [0] Verificar Python e dependencias (silencioso)
' ============================================================
Dim exitCode

' Testa se Python existe
' Testa se o Python REALMENTE funciona (nao o alias da Microsoft Store).
' O alias finge ser python mas so abre a loja. Testamos executando codigo real.
exitCode = objShell.Run("cmd /c python -c ""import sys; sys.exit(0)"" 2>nul", 0, True)
If exitCode <> 0 Then
    MsgBox "Python nao encontrado (ou e apenas o atalho da Microsoft Store)." & vbCrLf & vbCrLf & _
           "Instale o Python real em:" & vbCrLf & _
           "https://www.python.org/downloads/" & vbCrLf & vbCrLf & _
           "Marque 'Add Python to PATH' durante a instalacao." & vbCrLf & vbCrLf & _
           "Dica: desative o alias falso em Configuracoes > Aplicativos >" & vbCrLf & _
           "Configuracoes avancadas > Aliases de execucao de aplicativo.", _
           vbCritical, "Nexum"
    WScript.Quit 1
End If

' Testa se fastapi esta instalado
exitCode = objShell.Run("cmd /c python -c ""import fastapi"" 2>nul", 0, True)
If exitCode <> 0 Then
    ' Pede pra rodar instalador de deps
    Dim resp
    resp = MsgBox("As dependencias do Nexum ainda nao estao instaladas." & vbCrLf & vbCrLf & _
                  "Vou abrir uma janela pra instalar (leva 1-2 minutos)." & vbCrLf & _
                  "Depois pode rodar o Nexum normalmente." & vbCrLf & vbCrLf & _
                  "Continuar?", vbYesNo + vbQuestion, "Nexum - Primeira execucao")
    If resp = vbNo Then WScript.Quit 0

    ' Roda pip install com janela visivel (1x so)
    exitCode = objShell.Run("cmd /c python -m pip install -r """ & scriptDir & "\requirements.txt"" && pause", 1, True)
    If exitCode <> 0 Then
        MsgBox "Falha ao instalar dependencias.", vbCritical, "Nexum"
        WScript.Quit 1
    End If
End If

' Testa libs OCR (instalacao opcional)
exitCode = objShell.Run("cmd /c python -c ""import pytesseract, pypdfium2"" 2>nul", 0, True)
If exitCode <> 0 Then
    ' Instala silenciosamente em background - nao bloqueia
    objShell.Run "cmd /c python -m pip install pytesseract Pillow pypdfium2", 0, True
End If

' Garante pasta data/
If Not objFSO.FolderExists(scriptDir & "\data") Then
    objFSO.CreateFolder(scriptDir & "\data")
End If

' ============================================================
' [1] Sobe servidor com python redirecionando log
' ============================================================
' IMPORTANTE: usamos cmd /c python (nao pythonw) porque pythonw nao
' tem stdout/stderr - qualquer erro de importacao morre silencioso.
' Com python normal redirecionando pra arquivo, conseguimos diagnosticar.
' WindowStyle = 0 esconde o cmd completamente.

Dim logServidor
logServidor = scriptDir & "\data\server.log"

' Apaga log anterior pra captura limpa
On Error Resume Next
If objFSO.FileExists(logServidor) Then objFSO.DeleteFile(logServidor)
On Error Goto 0

Dim cmdServidor
' Garante que cd entra na pasta do script ANTES de chamar python
' Aspas duplas escapadas pra suportar paths com espaco (ex: "Vibe Coding")
cmdServidor = "cmd /c cd /d """ & scriptDir & """ && python.exe -m uvicorn app.main:app --host 127.0.0.1 --port " & PORTA & " > """ & logServidor & """ 2>&1"
objShell.Run cmdServidor, 0, False

' ============================================================
' [2] Aguarda servidor responder
' ============================================================
Dim http, tentativas, servidorOK
servidorOK = False
For tentativas = 1 To 45
    WScript.Sleep 1000
    On Error Resume Next
    Set http = CreateObject("MSXML2.ServerXMLHTTP.6.0")
    http.SetTimeouts 1000, 1000, 1000, 1000
    http.Open "GET", URL_HEALTH, False
    http.Send
    If Err.Number = 0 And http.Status = 200 Then
        servidorOK = True
        On Error Goto 0
        Exit For
    End If
    On Error Goto 0
Next

If Not servidorOK Then
    ' Le o log pra mostrar o erro real
    Dim msgErro, fileLog, contentLog
    msgErro = "O servidor do Nexum nao iniciou em 45 segundos." & vbCrLf & vbCrLf

    On Error Resume Next
    Set fileLog = objFSO.OpenTextFile(logServidor, 1)
    If Err.Number = 0 Then
        contentLog = fileLog.ReadAll
        fileLog.Close
        If Len(contentLog) > 0 Then
            ' Limita a 2000 chars pra nao virar uma MsgBox gigante
            If Len(contentLog) > 2000 Then
                contentLog = "..." & Right(contentLog, 2000)
            End If
            msgErro = msgErro & "Erro detectado:" & vbCrLf & vbCrLf & contentLog
        Else
            msgErro = msgErro & "Log vazio. Possivel causa:" & vbCrLf & _
                      "- python.exe nao esta no PATH" & vbCrLf & _
                      "- pasta 'app' nao esta junto do Nexum.vbs"
        End If
    Else
        msgErro = msgErro & "Nao foi possivel ler o log em:" & vbCrLf & logServidor
    End If
    On Error Goto 0

    MsgBox msgErro, vbCritical, "Nexum - Erro"
    WScript.Quit 1
End If

' ============================================================
' [3] Encontra Chrome ou Edge
' ============================================================
Dim browserPath, candidatos, p
browserPath = ""
candidatos = Array( _
    objShell.ExpandEnvironmentStrings("%ProgramFiles%\Google\Chrome\Application\chrome.exe"), _
    objShell.ExpandEnvironmentStrings("%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"), _
    objShell.ExpandEnvironmentStrings("%LocalAppData%\Google\Chrome\Application\chrome.exe"), _
    objShell.ExpandEnvironmentStrings("%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"), _
    objShell.ExpandEnvironmentStrings("%ProgramFiles%\Microsoft\Edge\Application\msedge.exe") _
)

For Each p In candidatos
    If objFSO.FileExists(p) Then
        browserPath = p
        Exit For
    End If
Next

' ============================================================
' [4] Abre o navegador em modo app + monitora
' ============================================================
Dim userData
userData = scriptDir & "\data\chrome-profile"
If Not objFSO.FolderExists(userData) Then objFSO.CreateFolder(userData)

Dim url, cmdBrowser
url = "http://localhost:" & PORTA

If browserPath = "" Then
    ' Fallback: navegador padrao
    objShell.Run url, 1, False
    ' Sem como monitorar fim - deixa servidor rodando
    WScript.Quit 0
End If

cmdBrowser = """" & browserPath & """ --app=" & url & _
             " --window-size=1400,900 --user-data-dir=""" & userData & """"
objShell.Run cmdBrowser, 1, False

' Captura PIDs do nosso browser
WScript.Sleep 2000
Dim browserExe
browserExe = objFSO.GetFileName(browserPath)

Dim wmi, processos, proc, pidsNossos
Set wmi = GetObject("winmgmts:\\.\root\cimv2")
Set pidsNossos = CreateObject("Scripting.Dictionary")

Set processos = wmi.ExecQuery( _
    "SELECT ProcessId, CommandLine FROM Win32_Process WHERE Name = '" & browserExe & "'")
For Each proc In processos
    If Not IsNull(proc.CommandLine) Then
        If InStr(proc.CommandLine, userData) > 0 Then
            pidsNossos.Add proc.ProcessId, True
        End If
    End If
Next

If pidsNossos.Count = 0 Then WScript.Quit 0

' ============================================================
' [5] Loop: espera o Chrome fechar
' ============================================================
Dim aindaTem, pid, q

Do
    WScript.Sleep 3000
    aindaTem = False
    For Each pid In pidsNossos.Keys
        Set q = wmi.ExecQuery("SELECT ProcessId FROM Win32_Process WHERE ProcessId = " & pid)
        If q.Count > 0 Then
            aindaTem = True
            Exit For
        End If
    Next
Loop While aindaTem

' ============================================================
' [6] Chrome fechado - mata servidor uvicorn
' ============================================================
' Mata python.exe (que esta rodando uvicorn) e o cmd.exe pai
' (que foi criado pelo objShell.Run cmd /c ...)
Dim qServ, procServ
Set qServ = wmi.ExecQuery( _
    "SELECT ProcessId, CommandLine FROM Win32_Process " & _
    "WHERE Name = 'pythonw.exe' OR Name = 'python.exe' OR Name = 'cmd.exe'")

For Each procServ In qServ
    If Not IsNull(procServ.CommandLine) Then
        If InStr(procServ.CommandLine, "uvicorn") > 0 And _
           InStr(procServ.CommandLine, CStr(PORTA)) > 0 Then
            On Error Resume Next
            procServ.Terminate
            On Error Goto 0
        End If
    End If
Next

WScript.Quit 0
