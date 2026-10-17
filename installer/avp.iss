; AV Proposal Platform 服务器安装包（Inno Setup 6）。
; 由 .github/workflows/windows-installer.yml 先运行 installer\build.ps1 组装 build\，再用 ISCC 编译成 dist\*.exe。
; 静默安装（IT 用）：AVProposalPlatform-Setup-x.y.z.exe /VERYSILENT /DATADIR=D:\avp-data
; 更新：运行新版安装包即可，资料目录和 deploy.local.yaml 保留。

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#define AppName "AV Proposal Platform"
#define Port "8081"
#define FirewallRule "AV Proposal Platform 8081"

[Setup]
AppId={{D6FAEAC8-119D-42B1-80C4-06D46CF16EFD}
AppName={#AppName}
AppVersion={#AppVersion}
VersionInfoVersion={#AppVersion}
AppPublisher=Audax
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
MinVersion=10.0
CloseApplications=no
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
OutputDir=..\dist
OutputBaseFilename=AVProposalPlatform-Setup-{#AppVersion}
UninstallDisplayName={#AppName}

[Tasks]
Name: firewall; Description: "Allow other computers on the company network to connect (port {#Port}, Domain + Private only) 允许公司内网其他电脑访问"

[InstallDelete]
; 更新时先清掉旧的 Python 和界面，避免旧版依赖残留。资料目录不在程序目录里，不受影响。
Type: filesandordirs; Name: "{app}\python"
Type: filesandordirs; Name: "{app}\web"

[Files]
Source: "..\build\avp\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\build\vc_redist.x64.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall

[Dirs]
Name: "{app}\logs"
Name: "{group}"

[INI]
Filename: "{group}\Open AV Proposal Platform.url"; Section: "InternetShortcut"; Key: "URL"; String: "http://localhost:{#Port}"

[Run]
Filename: "{tmp}\vc_redist.x64.exe"; Parameters: "/install /quiet /norestart"; StatusMsg: "Installing Microsoft Visual C++ runtime..."; Flags: waituntilterminated
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""{#FirewallRule}"""; Flags: runhidden waituntilterminated; Tasks: firewall
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""{#FirewallRule}"" dir=in action=allow protocol=TCP localport={#Port} profile=domain,private"; StatusMsg: "Opening port {#Port}..."; Flags: runhidden waituntilterminated; Tasks: firewall
Filename: "{app}\avp-service.exe"; Parameters: "install"; StatusMsg: "Installing the service..."; Flags: runhidden waituntilterminated; Check: not ServiceInstalled
Filename: "{app}\avp-service.exe"; Parameters: "start"; StatusMsg: "Starting the service..."; Flags: runhidden waituntilterminated
Filename: "http://localhost:{#Port}"; Description: "Open AV Proposal Platform 打开平台"; Flags: shellexec postinstall nowait skipifsilent

[UninstallRun]
Filename: "{sys}\net.exe"; Parameters: "stop avp"; Flags: runhidden waituntilterminated; RunOnceId: "StopService"
Filename: "{app}\avp-service.exe"; Parameters: "uninstall"; Flags: runhidden waituntilterminated; RunOnceId: "RemoveService"
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""{#FirewallRule}"""; Flags: runhidden waituntilterminated; RunOnceId: "RemoveFirewallRule"

[UninstallDelete]
; 程序目录整个删掉（含日志和 deploy.local.yaml）；资料目录不在程序目录里，保留。
Type: filesandordirs; Name: "{app}"
Type: filesandordirs; Name: "{group}"

[Code]
var
  DataDirPage: TInputDirWizardPage;

function LocalConfig: String;
begin
  Result := ExpandConstant('{app}\app\config\deploy.local.yaml');
end;

function ServiceInstalled: Boolean;
begin
  Result := RegKeyExists(HKLM, 'SYSTEM\CurrentControlSet\Services\avp');
end;

procedure InitializeWizard;
var
  Dir: String;
begin
  DataDirPage := CreateInputDirPage(wpSelectDir, 'Data folder 资料目录',
    '数据库、客户原件和生成的文件都放在这里。',
    '请选本机容量大、有备份的磁盘（不要选网络盘）。更新或卸载时这个目录都不会被删除。', False, '');
  DataDirPage.Add('');
  Dir := ExpandConstant('{param:DATADIR}');
  if Dir = '' then
    if DirExists('D:\') then
      Dir := 'D:\avp-data'
    else
      Dir := ExpandConstant('{sd}\avp-data');
  DataDirPage.Values[0] := Dir;
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := False;
  if PageID = DataDirPage.ID then
    Result := FileExists(LocalConfig);  // 更新：沿用已有设置
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if CurPageID = DataDirPage.ID then
    if Pos(Uppercase(AddBackslash(WizardDirValue)), Uppercase(AddBackslash(DataDirPage.Values[0]))) = 1 then
    begin
      MsgBox('资料目录不能放在程序目录里（卸载时程序目录会被删掉）。', mbError, MB_OK);
      Result := False;
    end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Code: Integer;
begin
  // 更新：先停服务，旧文件才能替换
  if ServiceInstalled then
    Exec(ExpandConstant('{sys}\net.exe'), 'stop avp', '', SW_HIDE, ewWaitUntilTerminated, Code);
  Result := '';
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Dir: String;
  Lines: TArrayOfString;
begin
  // 首次安装：在复制文件之前写好服务器设置（服务启动时读取）。更新时已有，不动。
  if (CurStep = ssInstall) and not FileExists(LocalConfig) then
  begin
    Dir := DataDirPage.Values[0];
    StringChangeEx(Dir, '''', '''''', True);
    SetArrayLength(Lines, 2);
    Lines[0] := '# Written by the installer. To move the data folder: stop the service, copy the whole folder, then edit this line.';
    Lines[1] := 'data_dir: ''' + Dir + '''';
    ForceDirectories(ExtractFileDir(LocalConfig));
    if not SaveStringsToUTF8File(LocalConfig, Lines, False) then
      RaiseException('无法写入 ' + LocalConfig);
  end;
end;
