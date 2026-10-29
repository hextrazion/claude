; Inno Setup script for the Windows installer (per-user, no admin rights needed).
; Built by .github/workflows/ai-video-studio.yml:  iscc /DAppVersion=x.y.z packaging\installer.iss

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{CC61F7B3-7295-4F73-9717-23C2C1B671F8}
AppName=AI Video Studio
AppVersion={#AppVersion}
AppPublisher=AI Video Studio
DefaultDirName={localappdata}\Programs\AI Video Studio
DefaultGroupName=AI Video Studio
DisableProgramGroupPage=yes
DisableDirPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist-installer
OutputBaseFilename=AI-Video-Studio-Setup
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\AI Video Studio.exe
UninstallDisplayName=AI Video Studio
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Tasks]
Name: "desktopicon"; Description: "Put an AI Video Studio icon on my desktop"

[Files]
Source: "..\dist\AI Video Studio\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{userprograms}\AI Video Studio"; Filename: "{app}\AI Video Studio.exe"
Name: "{userdesktop}\AI Video Studio"; Filename: "{app}\AI Video Studio.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\AI Video Studio.exe"; Description: "Open AI Video Studio now"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; Ask a running copy to close before files are removed.
Filename: "{sys}\taskkill.exe"; Parameters: "/IM ""AI Video Studio.exe"" /F"; Flags: runhidden; RunOnceId: "StopStudio"

[Messages]
FinishedLabel=AI Video Studio is installed.%n%nIt opens in its own window and keeps a small icon in the system tray (bottom-right, near the clock) so videos can keep rendering when the window is closed. Right-click that icon and choose Quit to stop it.%n%nYour projects are kept in %LOCALAPPDATA%\AI Video Studio, even if you uninstall.
