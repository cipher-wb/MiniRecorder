; Inno Setup script — bundles dist\MiniRecorder.exe into 轻录_Setup.exe
; Build:  & "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe" installer.iss
; Output: installer_dist\轻录_Setup_x.y.z.exe

#define AppName "轻录"
#define AppNameEn "MiniRecorder"
#define AppVersion "1.0.0"
#define AppPublisher "cipher-wb"
#define AppURL "https://github.com/cipher-wb/MiniRecorder"
#define AppExeName "MiniRecorder.exe"

[Setup]
AppId={{C2A9F4E6-B017-4E5D-9B3E-8A9C2B1D7E60}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
AppUpdatesURL={#AppURL}
DefaultDirName={autopf}\{#AppNameEn}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\{#AppExeName}
UninstallDisplayName={#AppName}
OutputDir=installer_dist
OutputBaseFilename=轻录_Setup_{#AppVersion}
SetupIconFile=src\assets\icons\app.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "chinese"; MessagesFile: "ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; onedir layout — recursively bundle all PyInstaller output
Source: "dist\MiniRecorder\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "README.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
