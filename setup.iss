; visher MODs 安装脚本
; ??Inno Setup 编译生成安装??
[Setup]
AppName=visher MODs
AppVersion=2.0
AppPublisher=visher
DefaultDirName={autopf}\visherMODs
DefaultGroupName=visher MODs
UninstallDisplayIcon={app}\visher MODs.exe
UninstallFilesDir={app}\data\uninstall
OutputDir=.
OutputBaseFilename=visher_MODs_安装包
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupIconFile=app.ico
DirExistsWarning=no
DisableWelcomePage=no
DisableDirPage=no
DisableReadyPage=no
DisableFinishedPage=no

[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加图标:"; Flags: checkedonce

[Files]
Source: "visher MODs.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\visher MODs"; Filename: "{app}\visher MODs.exe"
Name: "{group}\卸载visher MODs"; Filename: "{app}\data\uninstall\unins000.exe"
Name: "{commondesktop}\visher MODs"; Filename: "{app}\visher MODs.exe"; Tasks: desktopicon

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Run]
; Filename: "{app}\visher MODs.exe"; Description: "立即运行 visher MODs"; Flags: nowait postinstall skipifsilent

[Code]
const
  HWND_TOPMOST = -1;
  SWP_NOMOVE = $0002;
  SWP_NOSIZE = $0001;

procedure SetWindowPos(hWnd: HWND; hWndInsertAfter: HWND; X, Y, cx, cy: Integer; uFlags: UINT);
  external 'SetWindowPos@user32.dll stdcall';

procedure InitializeWizard();
begin
  // 安装窗口强制置顶
  SetWindowPos(WizardForm.Handle, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE or SWP_NOSIZE);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Cmd: String;
  ResultCode: Integer;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    // 卸载完成后，用临时批处理删除剩余文件和文件夹
    Cmd := '/C ping 127.0.0.1 -n 3 >nul & rmdir /s /q "' + ExpandConstant('{app}') + '"';
    Exec('cmd.exe', Cmd, '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  end;
end;
