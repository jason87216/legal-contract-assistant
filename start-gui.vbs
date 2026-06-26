Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
command = "powershell.exe -ExecutionPolicy Bypass -NoProfile -File """ & scriptDir & "\start-gui.ps1"""
shell.Run command, 0, False
