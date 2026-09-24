' Userbotni oynasiz (fonda) ishga tushiradi
Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
sh.Run "pythonw userbot.py", 0, False
