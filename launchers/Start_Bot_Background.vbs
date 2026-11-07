Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName))
Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = root & "\bot"
sh.Run "cmd /c node whatsapp_bot.js >> ""..\data\bot.log"" 2>&1", 0, False
