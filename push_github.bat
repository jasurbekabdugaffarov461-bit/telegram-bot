@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo   Kodni GitHub'ga yuklash
echo ============================================
where git >nul 2>&1
if errorlevel 1 (
  echo Git o'rnatilmagan! https://git-scm.com/download/win dan o'rnating va qayta ishga tushiring.
  pause
  goto :eof
)

if not exist .git git init
git branch -M main
git remote remove origin >nul 2>&1
git remote add origin https://github.com/jasurbekabdugaffarov461-bit/telegram-bot.git

git config user.name >nul 2>&1 || git config user.name "Muhammad Ali"
git config user.email >nul 2>&1 || git config user.email "bot@example.com"

git add .
echo.
echo --- GitHub'ga yuklanadigan fayllar (maxfiy fayllar YO'Q bo'lishi kerak) ---
git status --short
echo.
git commit -m "Yangilanish: AI zaxira xizmatlari, bitta javob, autostart"
echo.
echo GitHub login oynasi ochilishi mumkin - brauzerda tasdiqlang.
git push -u origin main
if errorlevel 1 (
  echo.
  echo XATO. Yuqoridagi matnni skrinshot qilib yuboring.
) else (
  echo.
  echo TAYYOR! https://github.com/jasurbekabdugaffarov461-bit/telegram-bot
)
pause
