@echo off
chcp 65001 >nul
cd /d "%~dp0"
taskkill /IM pythonw.exe /F >/dev/null 2>&1
python qr_login.py
