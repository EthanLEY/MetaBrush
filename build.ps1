# MetaBrush 打包脚本：PyInstaller 单 EXE + 桌面快捷方式
# 用法： 双击 build.bat，或执行  powershell -ExecutionPolicy Bypass -File build.ps1
# 要求： 本机已安装 Python 3.10+（推荐 3.10/3.11/3.12）

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

Write-Host "==============================================" -ForegroundColor Cyan
Write-Host " MetaBrush 打包开始" -ForegroundColor Cyan
Write-Host "==============================================" -ForegroundColor Cyan

# 1. 创建虚拟环境并安装依赖
if (-not (Test-Path ".venv")) {
    Write-Host "[1/4] 创建虚拟环境 .venv ..." -ForegroundColor Yellow
    python -m venv .venv
}
$py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { throw "未找到虚拟环境 Python：$py" }

Write-Host "[2/4] 安装依赖（customtkinter / pillow / piexif / pyinstaller）..." -ForegroundColor Yellow
& $py -m pip install --disable-pip-version-check -q --upgrade pip
& $py -m pip install --disable-pip-version-check -q -r requirements.txt
& $py -m pip install --disable-pip-version-check -q pyinstaller
if ($LASTEXITCODE -ne 0) { throw "依赖安装失败" }

# 2. 运行核心逻辑测试
Write-Host "[3/4] 运行核心逻辑测试 ..." -ForegroundColor Yellow
& $py -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) {
    Write-Host "测试未通过，已中止打包。请先修复后重试。" -ForegroundColor Red
    exit 1
}

# 3. PyInstaller 打包为单 EXE（-F 单文件，-w 无控制台窗口）
Write-Host "[4/4] PyInstaller 打包（--onefile --windowed）..." -ForegroundColor Yellow
& $py -m PyInstaller --noconfirm --clean --onefile --windowed `
    --name MetaBrush `
    --collect-all customtkinter `
    --paths "$Root" `
    "$Root\main.py"
if ($LASTEXITCODE -ne 0) { throw "PyInstaller 构建失败" }

$exe = Join-Path $Root "dist\MetaBrush.exe"
if (-not (Test-Path $exe)) { throw "未找到构建产物：$exe" }

# 4. 创建桌面快捷方式「MetaBrush」（已存在则覆盖）
Write-Host "创建桌面快捷方式「MetaBrush」..." -ForegroundColor Yellow
$desktop = [Environment]::GetFolderPath("Desktop")
$lnk = Join-Path $desktop "MetaBrush.lnk"
$ws = New-Object -ComObject WScript.Shell
$sc = $ws.CreateShortcut($lnk)          # 已存在同名快捷方式时自动覆盖
$sc.TargetPath = $exe
$sc.WorkingDirectory = Split-Path -Parent $exe
$sc.Description = "MetaBrush - EXIF 元数据批量处理工具"
$sc.IconLocation = "$exe,0"
$sc.Save()

Write-Host ""
Write-Host "==============================================" -ForegroundColor Green
Write-Host " 打包完成！" -ForegroundColor Green
Write-Host "  EXE      : $exe" -ForegroundColor Green
Write-Host "  快捷方式 : $lnk" -ForegroundColor Green
Write-Host "==============================================" -ForegroundColor Green
