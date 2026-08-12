; Inno Setup — AIQuick VPN. Signed single-file installer, compiled in CI.
#define AppName "AIQuick VPN"
#define AppVersion "1.0.0"

[Setup]
AppMutex=QuickOpen.AIQuickVPN
AppId={{97D3A1F5-6F13-41D9-84A9-B7EA519CF15A}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=QuickOpen (quickopen.ai)
AppPublisherURL=https://quickopen.ai/projects/aiquick-vpn
DefaultDirName={autopf}\AIQuickVPN
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\AIQuickVPN.exe
OutputDir=dist
OutputBaseFilename=AIQuickVPN-Setup
SetupIconFile=..\aiquick-vpn.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
WizardImageFile=branding\wizard-large.bmp
WizardSmallImageFile=branding\wizard-small.bmp
AppCopyright=Apache-2.0. 100%% AI-built, published on QuickOpen (quickopen.ai).
VersionInfoCompany=QuickOpen
VersionInfoProductName=AIQuick VPN
VersionInfoVersion=1.0.0.0
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Messages]
WelcomeLabel2=AIQuick VPN is a 100%% AI-built, open-source offline tool, published on QuickOpen (quickopen.ai).%n%nThis will install it on your computer.
BeveledLabel=QuickOpen · quickopen.ai

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"
Name: "trustca"; Description: "Trust the QuickOpen Root CA (lets Windows verify QuickOpen signatures)"; GroupDescription: "Security:"; Flags: unchecked

[Files]
Source: "staging\AIQuickVPN.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "staging\quickopen-root.crt"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
Source: "staging\README.md"; DestDir: "{app}"; Flags: ignoreversion isreadme skipifsourcedoesntexist
Source: "staging\LICENSE"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist

[Icons]
Name: "{group}\AIQuick VPN"; Filename: "{app}\AIQuickVPN.exe"; IconFilename: "{app}\AIQuickVPN.exe"
Name: "{group}\Uninstall AIQuick VPN"; Filename: "{uninstallexe}"
Name: "{autodesktop}\AIQuick VPN"; Filename: "{app}\AIQuickVPN.exe"; IconFilename: "{app}\AIQuickVPN.exe"; Tasks: desktopicon

[Run]
Filename: "certutil.exe"; Parameters: "-addstore -user Root ""{app}\quickopen-root.crt"""; Tasks: trustca; Flags: runhidden; StatusMsg: "Trusting the QuickOpen Root CA..."
Filename: "{app}\AIQuickVPN.exe"; Description: "Launch AIQuick VPN now"; Flags: nowait postinstall skipifsilent

; Full uninstall: remove every app-owned trace. The QuickOpen Root CA is
; intentionally NOT touched — it is shared by all QuickOpen apps.
[UninstallDelete]
Type: filesandordirs; Name: "{userappdata}\AIQuickVPN"
