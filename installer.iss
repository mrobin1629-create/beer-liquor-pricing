; Inno Setup script for Beer and Liquor Pricing
; IMPORTANT: never change AppId. Keeping it the same is what makes a new
; setup file upgrade the existing install instead of installing twice.
#define MyAppName "Beer and Liquor Pricing"
; keep MyAppVersion in sync with APP_VERSION in app\config.py
#define MyAppVersion "1.5.3"
#define MyAppExe "BevMargin.exe"

[Setup]
AppId={{6F2C4B1E-8A37-4D5C-9E21-B3A07C5D4F18}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher=Robin Mishra
AppCopyright=Copyright (C) 2026 Robin Mishra
VersionInfoCompany=Robin Mishra
VersionInfoCopyright=Copyright (C) 2026 Robin Mishra
DefaultDirName={autopf}\BevMargin
DefaultGroupName={#MyAppName}
UninstallDisplayIcon={app}\{#MyAppExe}
OutputDir=Output
OutputBaseFilename=BevMargin-Setup-{#MyAppVersion}
SetupIconFile=assets\app.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequiredOverridesAllowed=dialog
CloseApplications=yes
UsePreviousAppDir=yes
ArchitecturesInstallIn64BitMode=x64compatible

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
; Program files only. Your data is in %APPDATA%\BevMargin and is never included,
; replaced or deleted by this installer or by uninstall.
Source: "dist\BevMargin\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; clear old program files from a previous version (not data)
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExe}"; Description: "Start {#MyAppName}"; Flags: nowait postinstall skipifsilent
