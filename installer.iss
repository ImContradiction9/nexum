; Instalador do Nexum (Inno Setup 6)
; Gera dist\NexumSetup.exe a partir da pasta dist\Nexum\ (PyInstaller ONEDIR:
; Nexum.exe + _internal\). Onedir evita o erro de "Failed to load Python DLL"
; que o onefile causava na 1ª abertura pós-update (corrida com o Defender).
;
; Instalação POR USUÁRIO (sem admin/UAC): vai para %LocalAppData%\Programs\Nexum.
; Os DADOS do usuário ficam em %APPDATA%\Nexum (o exe decide isso em run_nexum.py)
; e por isso NÃO são tocados na desinstalação.
;
; Compilar:  build_installer.ps1   (ou: ISCC.exe installer.iss)

#define MyAppName "Nexum"
; A versão pode vir do build_installer.ps1 via /DMyAppVersion=x.y.z (lê app/__init__.py).
#ifndef MyAppVersion
  #define MyAppVersion "1.0.0"
#endif
#define MyAppPublisher "Nexum"
#define MyAppExeName "Nexum.exe"

[Setup]
; AppId identifica o app para upgrades/desinstalação — NÃO mudar entre versões.
AppId={{B0D9F3A1-7C42-4E58-9A1D-6F2E0C3B5A77}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DisableProgramGroupPage=yes
; Sem admin: instala no perfil do usuário, sem prompt de UAC.
PrivilegesRequired=lowest
OutputDir=dist
OutputBaseFilename=NexumSetup
SetupIconFile=app\static\icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Auto-update: o app se fecha antes de rodar o setup (updater .bat) e reabre
; sozinho. CloseApplications=yes é uma rede de segurança caso ainda esteja vivo;
; RestartApplications=no porque o updater já reabre o Nexum.
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
; Ambos marcados por padrão. O do Menu Iniciar fica visível como opção (antes
; era criado sempre, sem checkbox). Default checked = o usuário só desmarca se
; não quiser.
Name: "startmenuicon"; Description: "Criar atalho no Menu Iniciar (facilita a busca)"; GroupDescription: "{cm:AdditionalIcons}"
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
; ONEDIR: copia Nexum.exe + a pasta _internal\ inteira.
Source: "dist\Nexum\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; Menu Iniciar + Área de Trabalho, ambos opcionais via task (default checked).
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: startmenuicon
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
