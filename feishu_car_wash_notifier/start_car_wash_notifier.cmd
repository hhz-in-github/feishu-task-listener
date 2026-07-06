@echo off
setlocal
set "PROJECT=%~dp0"
call "%PROJECT%stop_car_wash_notifier.cmd" >nul 2>nul
powershell -NoProfile -ExecutionPolicy Bypass -Command "$script = Join-Path '%PROJECT%' 'car_wash_notifier.py'; $args = '-u \"' + $script + '\"'; Start-Process -FilePath 'python' -ArgumentList $args -WorkingDirectory '%PROJECT%' -RedirectStandardOutput (Join-Path '%PROJECT%' 'car_wash_notifier.out.log') -RedirectStandardError (Join-Path '%PROJECT%' 'car_wash_notifier.err.log') -WindowStyle Hidden"
echo Started car wash notifier. Check car_wash_notifier.err.log for connection status.
endlocal
