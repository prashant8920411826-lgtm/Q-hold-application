@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Creating the Q-Hold Python environment...
    py -3 -m venv .venv
    if errorlevel 1 goto :error
)

echo Checking Q-Hold dependencies...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :error

echo.
echo Starting Q-Hold at http://127.0.0.1:5000
echo Keep this window open while using the application.
echo Stop the server with Ctrl+C.
".venv\Scripts\python.exe" app.py --no-browser
if errorlevel 1 goto :error
goto :eof

:error
echo.
echo Q-Hold could not start. Check the error above and confirm Python 3 is installed.
pause
exit /b 1
