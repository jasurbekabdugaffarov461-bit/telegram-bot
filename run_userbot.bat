@echo off
chcp 65001 >nul
cd /d "%~dp0"
python -m pip install -q telethon google-genai
python userbot.py
pause
