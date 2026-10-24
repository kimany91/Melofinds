; Installateur Windows de Melofinds PC (Inno Setup 6).
; Construit par .github/workflows/pc-build.yml :
;   iscc /DAppVersion=3.1.0 pc\installer.iss
; Il demande où installer le programme et où arrivent les prods, copie le programme
; et ses outils (inclus : rien n'est téléchargé après coup), crée les raccourcis,
; propose le lancement avec Windows, et s'inscrit dans « Applications installées »
; avec un désinstalleur standard. Installation pour l'utilisateur seulement (pas besoin
; d'être administrateur).

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{9C1E7F3A-5B2D-4E8A-9F61-3D7C2B8A4E10}
AppName=Melofinds PC
AppVersion={#AppVersion}
AppVerName=Melofinds PC {#AppVersion}
AppPublisher=Melofinds
AppPublisherURL=https://kimany91.github.io/Melofinds/
AppSupportURL=https://github.com/kimany91/Melofinds
AppUpdatesURL=https://github.com/kimany91/Melofinds/releases
DefaultDirName={localappdata}\Programs\Melofinds
DisableDirPage=no
DisableProgramGroupPage=yes
DisableWelcomePage=no
UsePreviousAppDir=yes
UsePreviousTasks=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=MelofindsSetup
SetupIconFile=assets\melofinds.ico
UninstallDisplayIcon={app}\MelofindsPC.exe
UninstallDisplayName=Melofinds PC
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
VersionInfoVersion={#AppVersion}
VersionInfoCompany=Melofinds
VersionInfoProductName=Melofinds PC
VersionInfoDescription=Installateur de Melofinds PC
VersionInfoCopyright=Melofinds

[Languages]
Name: "fr"; MessagesFile: "compiler:Languages\French.isl"

[Tasks]
Name: "desktopicon"; Description: "Créer un raccourci « Melofinds PC » sur le bureau"; GroupDescription: "Raccourcis :"
Name: "autostart"; Description: "Se mettre en ligne tout seul au démarrage de l'ordinateur"; GroupDescription: "Démarrage :"

[Files]
Source: "..\dist\MelofindsPC\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\build\tools\*"; DestDir: "{app}\tools"; Flags: ignoreversion

[Icons]
Name: "{userprograms}\Melofinds PC"; Filename: "{app}\MelofindsPC.exe"; Comment: "Gérer Melofinds PC : en ligne, appareils, dossier des prods"
Name: "{userdesktop}\Melofinds PC"; Filename: "{app}\MelofindsPC.exe"; Comment: "Gérer Melofinds PC : en ligne, appareils, dossier des prods"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "MelofindsPC"; ValueData: """{app}\MelofindsPC.exe"" --background"; Tasks: autostart; Flags: uninsdeletevalue

[Run]
; Réglages choisis dans l'installateur (dossier des prods, code du téléphone) : pas en mise à jour silencieuse.
Filename: "{app}\MelofindsPC.exe"; Parameters: "--configure --dossier ""{code:BeatsDir}"" {code:PairArg}"; Flags: runhidden waituntilterminated; StatusMsg: "Réglages…"; Check: not WizardSilent
; Remise en ligne (installation et mise à jour).
Filename: "{app}\MelofindsPC.exe"; Parameters: "--start-if-configured"; Flags: runhidden nowait
Filename: "{app}\MelofindsPC.exe"; Description: "Ouvrir Melofinds PC"; Flags: postinstall nowait skipifsilent

[UninstallRun]
Filename: "{app}\MelofindsPC.exe"; Parameters: "--stop"; Flags: runhidden waituntilterminated; RunOnceId: "StopMelofinds"

[UninstallDelete]
; Fichiers créés par le programme lui-même (jamais les prods : elles sont dans leur propre dossier).
Type: files; Name: "{app}\config.json"
Type: files; Name: "{app}\config.tmp"
Type: files; Name: "{app}\state.json"
Type: files; Name: "{app}\state.tmp"
Type: files; Name: "{app}\melofinds.log"
Type: files; Name: "{app}\melofinds.old.log"
Type: files; Name: "{app}\heartbeat"
Type: files; Name: "{app}\worker.lock"
Type: files; Name: "{app}\worker.pid"
Type: files; Name: "{app}\stop"
Type: filesandordirs; Name: "{app}\tools"
Type: filesandordirs; Name: "{app}\updates"
Type: filesandordirs; Name: "{app}\flmake"
; Script FL de FLmake (clé de Graillon), installé depuis le panneau
Type: filesandordirs; Name: "{userdocs}\Image-Line\FL Studio\Settings\Hardware\Melofinds FLmake"
Type: dirifempty; Name: "{app}"

[Code]
var
  BeatsPage: TInputDirWizardPage;
  PairPage: TInputQueryWizardPage;

procedure InitializeWizard;
begin
  BeatsPage := CreateInputDirPage(wpSelectDir,
    'Dossier des prods', 'Où arrivent les prods reçues ?',
    'Les prods envoyées depuis ton téléphone arriveront dans ce dossier, en .wav (rien d''autre n''y est écrit). Tu pourras le changer plus tard dans Melofinds PC.',
    False, '');
  BeatsPage.Add('');
  BeatsPage.Values[0] := GetPreviousData('BeatsDir', ExpandConstant('{%USERPROFILE}') + '\Music\Melofinds');

  PairPage := CreateInputQueryPage(BeatsPage.ID,
    'Ton téléphone', 'Code d''appairage (facultatif)',
    'Sur ton téléphone : Melofinds Web → Mon PC → Copier, puis colle le code ici. Tu peux aussi laisser vide et l''ajouter plus tard dans Melofinds PC → Appareils.');
  PairPage.Add('Code :', False);
end;

procedure RegisterPreviousData(PreviousDataKey: Integer);
begin
  SetPreviousData(PreviousDataKey, 'BeatsDir', BeatsPage.Values[0]);
end;

function ValidPairing(Code: String): Boolean;
var
  I: Integer;
begin
  { melofinds-<32 hex>.<64 hex> : uniquement des lettres a-f, des chiffres, « - » et « . » }
  Result := (Pos('melofinds-', Code) = 1) and (Length(Code) = 107);
  if Result then
    for I := 11 to Length(Code) do
      if Pos(Code[I], '0123456789abcdef.') = 0 then
        Result := False;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  Code: String;
begin
  Result := True;
  if CurPageID = PairPage.ID then
  begin
    Code := Lowercase(Trim(PairPage.Values[0]));
    if (Code <> '') and not ValidPairing(Code) then
    begin
      MsgBox('Ce code n''est pas valide. Dans Melofinds Web → Mon PC, touche « Copier » et colle-le ici (ou laisse vide).', mbError, MB_OK);
      Result := False;
    end;
  end;
end;

function BeatsDir(Param: String): String;
begin
  { Pas de « \ » final juste avant le guillemet (ex. « D:\ ») : il casserait la ligne de commande. }
  Result := RemoveBackslash(BeatsPage.Values[0]);
  if Length(Result) = 2 then
    Result := Result + '\.';
end;

function PairArg(Param: String): String;
var
  Code: String;
begin
  Code := Lowercase(Trim(PairPage.Values[0]));
  if ValidPairing(Code) then
    Result := '--pair ' + Code
  else
    Result := '';
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
begin
  { Mise à jour : on met d'abord le programme hors ligne proprement. }
  if FileExists(ExpandConstant('{app}\MelofindsPC.exe')) then
    Exec(ExpandConstant('{app}\MelofindsPC.exe'), '--stop', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Result := '';
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  { Le démarrage automatique peut aussi avoir été activé depuis le panneau. }
  if CurUninstallStep = usUninstall then
    RegDeleteValue(HKEY_CURRENT_USER, 'Software\Microsoft\Windows\CurrentVersion\Run', 'MelofindsPC');
end;
