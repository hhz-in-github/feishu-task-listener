@echo off
setlocal
set "PROJECT=%~dp0"
cd /d "%PROJECT%"
python car_wash_notifier.py --status
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object { $_.CommandLine -like '*car_wash_notifier.py*' } | Select-Object ProcessId,Name,CommandLine | ConvertTo-Json -Compress } catch { Write-Output ('Process query unavailable: ' + $_.Exception.Message) }"
endlocal
