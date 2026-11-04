; Inno Setup script. Build: ISCC /DAppVersion=... see tools/build.py.
#ifndef AppVersion
  #error Pass /DAppVersion, /DSourceDir, /DOutputDir, /DOutputName, /DIconFile
#endif

[Setup]
AppId={{6C1F3A52-8B47-4E0D-9D6A-2F7B5C9E41A8}
AppName=DiffAnyDoc
AppVersion={#AppVersion}
AppPublisher=DiffAnyDoc
DefaultDirName={autopf}\DiffAnyDoc
DefaultGroupName=DiffAnyDoc
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
SetupIconFile={#IconFile}
UninstallDisplayIcon={app}\DiffAnyDoc.exe
OutputDir={#OutputDir}
OutputBaseFilename={#OutputName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\DiffAnyDoc"; Filename: "{app}\DiffAnyDoc.exe"
Name: "{autodesktop}\DiffAnyDoc"; Filename: "{app}\DiffAnyDoc.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\DiffAnyDoc.exe"; Description: "{cm:LaunchProgram,DiffAnyDoc}"; Flags: nowait postinstall skipifsilent
