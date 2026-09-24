@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Kutubxonalar o'rnatilmoqda...
python -m pip install -r requirements.txt
echo.
python bot.py
pause
