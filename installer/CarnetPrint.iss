; Instalador de CarnetPrint (Inno Setup 6.1+). Lo compila el workflow de GitHub Actions:
;   ISCC.exe /DAppVersion=0.2.0 installer\CarnetPrint.iss
; Espera ..\dist\CarnetPrint.exe, ..\dist\bridge\ y deps\windowsdesktop-runtime-win-x64.exe.
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6F3A7C1E-5B2D-4E8A-9C41-2D7B8E0A5F13}
AppName=CarnetPrint
AppVersion={#AppVersion}
; Los datos (.env, printers.yaml, *.json, png\) viven junto al .exe: la carpeta debe ser escribible
DefaultDirName={sd}\CarnetPrint
DisableProgramGroupPage=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=CarnetPrint-Setup-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\CarnetPrint.exe

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "Crear un acceso directo en el escritorio"; GroupDescription: "Accesos directos:"
; Solo aparece si Windows no tiene la impresora «XPS Card Printer»
Name: "entrustdriver"; Description: "Descargar e instalar el driver XPS de Entrust 8.8 (no se encontró la impresora «XPS Card Printer»)"; GroupDescription: "Impresora:"; Check: PrinterMissing

[Dirs]
Name: "{app}"; Permissions: users-modify

[Files]
Source: "..\dist\CarnetPrint.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\bridge\*"; DestDir: "{app}\bridge"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "deps\windowsdesktop-runtime-win-x64.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall; Check: DotNetMissing

[Icons]
Name: "{autoprograms}\CarnetPrint"; Filename: "{app}\CarnetPrint.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\CarnetPrint"; Filename: "{app}\CarnetPrint.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{tmp}\windowsdesktop-runtime-win-x64.exe"; Parameters: "/install /quiet /norestart"; StatusMsg: "Instalando .NET 8 Desktop Runtime..."; Check: DotNetMissing; Flags: waituntilterminated
Filename: "{tmp}\XPSCardPrinter.exe"; StatusMsg: "Instalando el driver XPS de Entrust (sigue sus pasos)..."; Tasks: entrustdriver; Flags: waituntilterminated skipifsilent
Filename: "{app}\CarnetPrint.exe"; Description: "Abrir CarnetPrint"; WorkingDir: "{app}"; Flags: nowait postinstall skipifsilent

[Code]
const
  EntrustDriverUrl = 'https://downloads.entrust.com/drivers/XPSCardPrinter_8.8.048.0.exe';
  MinDotNetMajor = 8;

var
  DownloadPage: TDownloadWizardPage;
  DotNetChecked, DotNetIsMissing: Boolean;

// CardBridge.exe necesita Microsoft.WindowsDesktop.App 8 o superior (x64)
function DotNetMissing: Boolean;
var
  FindRec: TFindRec;
  Base, Name: String;
  Dot: Integer;
begin
  if not DotNetChecked then
  begin
    DotNetChecked := True;
    DotNetIsMissing := True;
    Base := ExpandConstant('{commonpf64}\dotnet\shared\Microsoft.WindowsDesktop.App\');
    if FindFirst(Base + '*', FindRec) then
    try
      repeat
        Name := FindRec.Name;
        Dot := Pos('.', Name);
        if ((FindRec.Attributes and FILE_ATTRIBUTE_DIRECTORY) <> 0) and (Dot > 1) then
          if StrToIntDef(Copy(Name, 1, Dot - 1), 0) >= MinDotNetMajor then
            DotNetIsMissing := False;
      until not FindNext(FindRec);
    finally
      FindClose(FindRec);
    end;
  end;
  Result := DotNetIsMissing;
end;

function PrinterMissing: Boolean;
var
  Code: Integer;
begin
  Result := not (Exec('powershell.exe',
    '-NoProfile -Command "Get-Printer -Name ''XPS Card Printer'' -ErrorAction Stop | Out-Null"',
    '', SW_HIDE, ewWaitUntilTerminated, Code) and (Code = 0));
end;

procedure InitializeWizard;
begin
  DownloadPage := CreateDownloadPage(SetupMessage(msgWizardPreparing), SetupMessage(msgPreparingDesc), nil);
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if (CurPageID = wpReady) and WizardIsTaskSelected('entrustdriver') then
  begin
    DownloadPage.Clear;
    DownloadPage.Add(EntrustDriverUrl, 'XPSCardPrinter.exe', '');
    DownloadPage.Show;
    try
      try
        DownloadPage.Download;
      except
        Result := False;
        MsgBox('No se pudo descargar el driver de Entrust: ' + GetExceptionMessage + #13#10 +
               'Descárgalo desde ' + EntrustDriverUrl + ' o desmarca esa opción.', mbError, MB_OK);
      end;
    finally
      DownloadPage.Hide;
    end;
  end;
end;

// Si CarnetPrint está abierto, se cierra para poder actualizarlo
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Code: Integer;
begin
  Exec('taskkill.exe', '/F /T /IM CarnetPrint.exe', '', SW_HIDE, ewWaitUntilTerminated, Code);
  Result := '';
end;
