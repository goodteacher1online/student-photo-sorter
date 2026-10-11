$WshShell = New-Object -ComObject WScript.Shell
$Desktop = [System.Environment]::GetFolderPath('Desktop')
$Shortcut = $WshShell.CreateShortcut("$Desktop\학생 사진 자동 분류기.lnk")

# 초고속 0초 기동 배포판 직접 연결
$TargetExe = "C:\Users\goodt\student-photo-sorter\dist\학생사진자동분류기_초고속\학생사진자동분류기.exe"
if (-not (Test-Path $TargetExe)) {
    $TargetExe = "C:\Users\goodt\student-photo-sorter\학생사진자동분류기.exe"
}

$Shortcut.TargetPath = $TargetExe
$Shortcut.WorkingDirectory = [System.IO.Path]::GetDirectoryName($TargetExe)
$Shortcut.Description = "학생 사진 자동 분류기 (초고속 0초 기동 모드)"
$Shortcut.Save()
Write-Host "바탕화면에 바로가기가 성공적으로 생성되었습니다: $Desktop\학생 사진 자동 분류기.lnk -> $TargetExe"
