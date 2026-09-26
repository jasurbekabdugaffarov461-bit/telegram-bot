' Guruh boti (bot.py) va userbot (userbot.py) ni oynasiz, fonda ishga tushiradi
Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)

' Internet paydo bo'lguncha kutish (ko'pi bilan ~3 daqiqa)
For i = 1 To 36
    If sh.Run("ping -n 1 -w 2000 api.telegram.org", 0, True) = 0 Then Exit For
    WScript.Sleep 5000
Next

sh.Run "taskkill /IM pythonw.exe /F", 0, True
sh.Run "pythonw bot.py", 0, False
sh.Run "pythonw userbot.py", 0, False
