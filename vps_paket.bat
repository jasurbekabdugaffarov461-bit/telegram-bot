@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo VPS uchun kerakli fayllar vps_paket papkasiga va vps_paket.zip ga yig'ilmoqda...
if not exist .env python make_env.py
if exist vps_paket rmdir /s /q vps_paket
mkdir vps_paket
for %%F in (bot.py userbot.py bad_words.py requirements.txt setup_vps.sh .env bot_config.json userbot_config.json my_account.session) do if exist "%%F" copy /y "%%F" vps_paket\ >nul
if exist vps_paket.zip del /q vps_paket.zip
powershell -NoProfile -Command "Compress-Archive -Path 'vps_paket\*' -DestinationPath 'vps_paket.zip' -Force"
echo.
echo TAYYOR! Papkadagi fayllar:
dir /b /a vps_paket
echo.
echo vps_paket.zip - ichida MAXFIY kalitlar bor, hech kimga bermang!
pause
