@echo off
chcp 65001 >nul
cd /d "%~dp0"
powershell -NoProfile -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Startup')+'\telegram-bots.lnk'); $s.TargetPath='wscript.exe'; $s.Arguments='\"%~dp0start_all_hidden.vbs\"'; $s.WorkingDirectory='%~dp0'; $s.Save()"
del /q "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\start_userbot_hidden*.lnk" >nul 2>&1
echo.
echo Avtomatik ishga tushirish YOQILDI.
echo Kompyuter yoqilganda bot va userbot o'zi ishga tushadi.
echo Hozir ham ishga tushirilmoqda...
wscript.exe "%~dp0start_all_hidden.vbs"
pause
