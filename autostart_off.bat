@echo off
chcp 65001 >nul
del /q "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\telegram-bots.lnk" >nul 2>&1
taskkill /IM pythonw.exe /F >nul 2>&1
echo Avtomatik ishga tushirish O'CHIRILDI va botlar to'xtatildi.
pause
