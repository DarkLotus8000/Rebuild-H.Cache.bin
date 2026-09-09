@echo off
setlocal
if "%~1"=="" (
    echo Drag the B.Cache.*.bin!E_hash files onto this BAT file.
    echo.
    pause
    exit /b 1
)
py -3 "%~dp0rebuild_hcache.py" %*
set "code=%errorlevel%"
echo.
pause
exit /b %code%
