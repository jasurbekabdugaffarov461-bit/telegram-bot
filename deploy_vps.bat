@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo   Botlarni VPS serverga joylash
echo ============================================
echo.
set /p SERVER=VPS manzili (masalan root@123.45.67.89):
if "%SERVER%"=="" goto :eof

echo.
echo [1/4] Kompyuterdagi bot va userbot to'xtatilmoqda...
taskkill /IM pythonw.exe /F >nul 2>&1
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'bot\.py' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" >nul 2>&1
del /q "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\start_userbot_hidden*.lnk" >nul 2>&1
del /q "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\telegram-bots.lnk" >nul 2>&1

echo [2/4] Serverda papka yaratilmoqda (parol so'ralsa - kiriting)...
ssh %SERVER% "mkdir -p ~/telegram-bot"
if errorlevel 1 goto :err

set EXTRA=
if exist .env set EXTRA=.env
if exist biznes.txt set EXTRA=%EXTRA% biznes.txt
echo [3/4] Fayllar yuklanmoqda (parol so'ralsa - kiriting)...
scp %EXTRA% bot.py ai_core.py bad_words.py userbot.py bot_config.json userbot_config.json my_account.session requirements.txt setup_vps.sh %SERVER%:telegram-bot/
if errorlevel 1 goto :err

echo [4/4] Serverda o'rnatilmoqda (parol so'ralsa - kiriting)...
ssh -t %SERVER% "bash ~/telegram-bot/setup_vps.sh"
if errorlevel 1 goto :err

echo.
echo TAYYOR! Botlar endi serverda 24/7 ishlaydi.
echo Kompyuterda bot.py va userbotni ISHGA TUSHIRMANG (ikki nusxa xato beradi).
pause
goto :eof

:err
echo.
echo XATO yuz berdi. Yuqoridagi matnni skrinshot qilib yuboring.
pause
