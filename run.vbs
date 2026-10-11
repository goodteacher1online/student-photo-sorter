Set WshShell = CreateObject("WScript.Shell")
Set FSO = CreateObject("Scripting.FileSystemObject")
currentDir = FSO.GetParentFolderName(WScript.ScriptFullName)
WshShell.CurrentDirectory = currentDir

targetExe = currentDir & "\dist\학생사진자동분류기_초고속\학생사진자동분류기.exe"
If FSO.FileExists(targetExe) Then
    WshShell.Run """" & targetExe & """", 1, False
ElseIf FSO.FileExists(currentDir & "\학생사진자동분류기.exe") Then
    WshShell.Run """" & currentDir & "\학생사진자동분류기.exe""", 1, False
Else
    WshShell.Run "pythonw.exe app.py", 0, False
End If
