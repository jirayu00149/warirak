@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Building and deploying Warirak website to Cloudflare...
call npm run deploy
echo.
echo Exit code: %errorlevel%
pause
