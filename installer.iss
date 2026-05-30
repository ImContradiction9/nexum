; Instalador do Nexum (Inno Setup 6)
; Gera dist\NexumSetup.exe a partir de dist\Nexum.exe (PyInstaller onefile).
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
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "dist\Nexum.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
; Menu Iniciar (lista de aplicativos) + Área de Trabalho (opcional via task).
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
