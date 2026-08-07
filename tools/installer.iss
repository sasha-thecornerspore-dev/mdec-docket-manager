; Inno Setup script for MDEC Docket Manager.
;
;   ISCC.exe /DAppVersion=1.2.0 tools\installer.iss
;
; Built by tools/build_installer.py, which runs PyInstaller first and passes the
; version in. Installs per-user under Local AppData so no administrator prompt
; appears — this is a personal tool, and requiring elevation to read your own
; court docket would be silly.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

#define AppName "MDEC Docket Manager"
#define AppExe "MDECDocketManager.exe"
#define AppPublisher "MDEC Docket Manager contributors"
#define AppUrl "https://github.com/sasha-thecornerspore-dev/mdec-docket-manager"

[Setup]
AppId={{7B3F2A64-5C21-4E8D-9A17-2D6E4F8B1C93}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppUrl}
AppSupportURL={#AppUrl}/issues
AppUpdatesURL={#AppUrl}/releases
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
DisableDirPage=no
LicenseFile=..\LICENSE
InfoAfterFile=..\assets\installer_after.txt
OutputDir=..\dist
OutputBaseFilename=MDEC-Docket-Manager-{#AppVersion}-Setup
SetupIconFile=..\assets\mdec.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &Desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
; The whole PyInstaller onedir tree — Python runtime included, so the user does
; not need Python installed.
Source: "..\build_dist\MDECDocketManager\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"; IconFilename: "{app}\assets\mdec.ico"
Name: "{group}\{#AppName} — Documentation"; Filename: "{app}\docs\WALKTHROUGH.md"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"; IconFilename: "{app}\assets\mdec.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Open {#AppName} now"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; PyInstaller writes nothing here, but leftover caches would block a clean removal.
Type: filesandordirs; Name: "{app}\__pycache__"

[Messages]
; The default "Setup will install..." wording implies a system install; this is per-user.
WelcomeLabel2=This will install [name/ver] for your user account only.%n%nNo administrator rights are needed and nothing is changed system-wide. Your case documents, notes, and settings are stored separately and are never touched by installing or uninstalling.

[Code]
// Warn if the app is running: PyInstaller cannot overwrite a loaded exe, and the
// service keeps running after its window closes, so this is easy to hit.
function InitializeSetup(): Boolean;
begin
  Result := True;
end;
