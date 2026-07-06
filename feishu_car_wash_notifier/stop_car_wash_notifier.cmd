@echo off
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-CimInstance Win32_Process | Where-Object { ($_.CommandLine -like '*car_wash_notifier.py*') -or ($_.CommandLine -like '*lark-cli*event*+subscribe*') } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
echo Stopped car wash notifier if it was running.
endlocal
