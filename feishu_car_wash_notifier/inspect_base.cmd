@echo off
setlocal
set "PROJECT=%~dp0"
cd /d "%PROJECT%"
python car_wash_notifier.py --inspect-base
endlocal
