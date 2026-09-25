' Guruh boti (bot.py) va userbot (userbot.py) ni oynasiz, fonda ishga tushiradi
Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
WScript.Sleep 15000   ' kompyuter yoqilganda internet ulanishini kutish
sh.Run "taskkill /IM pythonw.exe /F", 0, True
sh.Run "pythonw bot.py", 0, False
sh.Run "pythonw userbot.py", 0, False
