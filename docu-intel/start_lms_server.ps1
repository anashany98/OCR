param(
    [switch]$Foreground = $false
)
$ErrorActionPreference = "Stop"
Set-Location "C:\Users\Usuario\Desktop\DocuIntel\OCR\docu-intel"

# Kill any existing lms_server
Get-Process -Name "python" -ErrorAction SilentlyContinue | Where-Object {
    try { $_.MainWindowTitle -like "*lms_server*" -or ($_.CommandLine -like "*lms_server*") } catch { $false }
} | ForEach-Object {
    Write-Host "Killing existing lms_server PID $($_.Id)"
    Stop-Process -Id $_.Id -Force
}

if ($Foreground) {
    & python lms_server.py
} else {
    $logFile = "C:\Users\Usuario\Desktop\DocuIntel\OCR\docu-intel\lms_server.log"
    Write-Host "Starting lms_server.py in background. Log: $logFile"
    Start-Process -FilePath "python" -ArgumentList "lms_server.py" -RedirectStandardOutput $logFile -RedirectStandardError "$logFile.err" -WorkingDirectory "C:\Users\Usuario\Desktop\DocuIntel\OCR\docu-intel" -WindowStyle Hidden
    Start-Sleep -Seconds 2
    Write-Host "lms_server started"
}
