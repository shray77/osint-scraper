; ============================================================
;  Inno Setup — альтернативный установщик для OSINT Scraper
;
;  Inno Setup генерирует .exe установщик (не MSI), но он проще
;  в настройке и часто более гибкий, чем WiX.
;
;  Требования:
;    - Inno Setup 6+: https://jrsoftware.org/isdl.php
;    - PyInstaller: pip install pyinstaller
;
;  Сборка:
;    1. Сначала: pyinstaller packaging\osint_scraper.spec --noconfirm
;    2. Запустить Inno Setup Compiler:
;       iscc packaging\installer.iss
;    3. Результат: packaging\OSINTScraper-Setup-1.1.0.exe
; ============================================================

#define MyAppName "OSINT Scraper"
#define MyAppVersion "1.1.0"
#define MyAppPublisher "OSINT Tools"
#define MyAppURL "https://github.com/yourname/osint-scraper"
#define MyAppExeName "OSINTScraper.exe"

[Setup]
AppId={{7B5E3F2A-1234-5678-9ABC-DEF012345678}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
LicenseFile=packaging\license.rtf
OutputDir=packaging
OutputBaseFilename=OSINTScraper-Setup-{#MyAppVersion}
SetupIconFile=gui\resources\icon.ico
Compression=lzma2/ultra
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64
ArchitecturesAllowed=x64
PrivilegesRequired=admin
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "quicklaunchicon"; Description: "{cm:CreateQuickLaunchIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked; OnlyBelowVersion: 0,6.1

[Files]
; Все файлы из PyInstaller dist/OSINTScraper/
Source: "dist\OSINTScraper\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\gui\resources\icon.ico"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon; IconFilename: "{app}\gui\resources\icon.ico"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Code]
function InitializeSetup(): Boolean;
begin
  Result := True;
end;
