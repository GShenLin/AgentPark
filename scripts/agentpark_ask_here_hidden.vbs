Option Explicit

Dim shell
Dim fso
Dim scriptDir
Dim batchPath
Dim folderPath
Dim command

Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
batchPath = fso.BuildPath(scriptDir, "agentpark_ask_here.bat")

If WScript.Arguments.Count < 1 Then
    WScript.Quit 1
End If

folderPath = WScript.Arguments.Item(0)
command = """" & batchPath & """ """ & folderPath & """"

shell.Run command, 0, False
