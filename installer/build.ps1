# 组装安装包内容：build\avp\（Windows 版 Python + 依赖 + 程序 + 界面 + 服务程序）和 build\vc_redist.x64.exe。
# 由 .github/workflows/windows-installer.yml 在 Windows 机器上运行；运行前要先在 web\ 里 npm run build。
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"  # 进度条会让下载变得很慢

$Root = Split-Path -Parent $PSScriptRoot
$Build = Join-Path $Root "build"
$Out = Join-Path $Build "avp"
$PyVersion = "3.12.10"  # 3.12 最后一个有 Windows 官方包的版本
$WinSW = "https://github.com/winsw/winsw/releases/download/v2.12.0/WinSW.NET461.exe"
$WinSWSha256 = "b5066b7bbdfba1293e5d15cda3caaea88fbeab35bd5b38c41c913d492aadfc4f"

function Assert-Signed($Path, $Publisher) {
    $sig = Get-AuthenticodeSignature $Path
    if ($sig.Status -ne "Valid" -or $sig.SignerCertificate.Subject -notlike "*$Publisher*") {
        throw "$Path 的数字签名不对：$($sig.Status) $($sig.SignerCertificate.Subject)"
    }
}

if (-not (Test-Path (Join-Path $Root "web\dist\index.html"))) { throw "先在 web\ 里运行 npm run build" }
if (Test-Path $Build) { Remove-Item $Build -Recurse -Force }
New-Item -ItemType Directory $Out | Out-Null

# 1. Python 官方嵌入版（自带 sqlite3），只给本程序用，不影响服务器上别的 Python
$zip = Join-Path $Build "python.zip"
Invoke-WebRequest "https://www.python.org/ftp/python/$PyVersion/python-$PyVersion-embed-amd64.zip" -OutFile $zip
Expand-Archive $zip (Join-Path $Out "python")
Assert-Signed (Join-Path $Out "python\python.exe") "Python Software Foundation"
# ._pth 规定 Python 只在这几处找模块：标准库、依赖、程序（上一层目录）
Set-Content (Join-Path $Out "python\python312._pth") -Encoding ascii -Value @(
    "python312.zip", ".", "Lib\site-packages", "..", "import site")

# 2. 依赖：只用现成的 Windows 包，不在本机编译
python -m pip install --disable-pip-version-check --no-warn-script-location --only-binary=:all: `
    --target (Join-Path $Out "python\Lib\site-packages") -r (Join-Path $Root "requirements.txt")
if ($LASTEXITCODE) { throw "pip install 失败" }

# 2b. 打印 PDF 用的无头 Chromium（Playwright 的 chromium-headless-shell），放进程序目录的 browsers\，
#     服务启动时用 PLAYWRIGHT_BROWSERS_PATH 指过去（见 avp-service.xml）
$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $Out "browsers"
& (Join-Path $Out "python\python.exe") -m playwright install --only-shell chromium
if ($LASTEXITCODE) { throw "Chromium 下载失败" }
Remove-Item Env:PLAYWRIGHT_BROWSERS_PATH

# 3. 程序和界面（服务器自己的 deploy.local.yaml 由安装程序写，不打包）
Copy-Item (Join-Path $Root "app") $Out -Recurse
Get-ChildItem (Join-Path $Out "app") -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force
Remove-Item (Join-Path $Out "app\config\deploy.local.yaml") -ErrorAction SilentlyContinue
New-Item -ItemType Directory (Join-Path $Out "web") | Out-Null
Copy-Item (Join-Path $Root "web\dist") (Join-Path $Out "web") -Recurse

# 4. Windows 服务程序（WinSW，MIT 许可）
$svc = Join-Path $Out "avp-service.exe"
Invoke-WebRequest $WinSW -OutFile $svc
if ((Get-FileHash $svc -Algorithm SHA256).Hash -ne $WinSWSha256) { throw "WinSW 文件校验不对" }
Copy-Item (Join-Path $PSScriptRoot "avp-service.xml"), (Join-Path $PSScriptRoot "THIRD-PARTY.txt") $Out

# 5. Visual C++ 运行库（文字识别组件需要；微软允许随软件分发）
$vc = Join-Path $Build "vc_redist.x64.exe"
Invoke-WebRequest "https://aka.ms/vs/17/release/vc_redist.x64.exe" -OutFile $vc
Assert-Signed $vc "Microsoft Corporation"

$mb = (Get-ChildItem $Out -Recurse -File | Measure-Object Length -Sum).Sum / 1MB
"build\avp: {0:N0} MB" -f $mb
