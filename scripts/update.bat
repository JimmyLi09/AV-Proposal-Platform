@echo off
REM AV Proposal Platform — 一键更新 (Windows 服务器)
REM 用法: 双击此文件, 或在项目目录命令行执行 scripts\update.bat
REM 服务器自己的设置在 app\config\deploy.local.yaml, 资料目录在 deploy.local.yaml 指定的位置, 更新不会动它们。
cd /d "%~dp0.."

echo ==^> 拉取最新代码 Pulling latest code (branch: main)...
git fetch origin main || goto :err
git checkout main 2>nul || git checkout -b main origin/main
git reset --hard origin/main || goto :err

echo ==^> 安装 Python 依赖 Installing Python packages...
.venv\Scripts\python.exe -m pip install -r requirements.txt || goto :err

echo ==^> 构建界面 Building web UI...
cd web
call npm ci || goto :err
call npm run build || goto :err
cd ..

echo ==^> 重启服务 Restarting (数据库结构在启动时自动升级)...
call pm2 restart avp || goto :err
call pm2 save
echo √ 更新完成 Update done. 浏览器打开 http://localhost:8081 检查。
pause
exit /b 0

:err
echo × 更新失败, 请把上面的报错截图发给 Jimmy。
pause
exit /b 1
