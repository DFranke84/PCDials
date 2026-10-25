@echo off
rem Start the PCDials dials (does nothing if they're already running).
setlocal
set PYW=
for %%P in (
    "%LOCALAPPDATA%\Programs\Python\Python314\pythonw.exe"
    "%ProgramFiles%\Python314\pythonw.exe"
    "C:\Python314\pythonw.exe"
    "%LOCALAPPDATA%\Programs\Python\Python313\pythonw.exe"
    "%ProgramFiles%\Python313\pythonw.exe"
    "C:\Python313\pythonw.exe"
) do if not defined PYW if exist %%P set "PYW=%%~P"
if not defined PYW for /f "delims=" %%E in ('where pythonw 2^>nul') do if not defined PYW set "PYW=%%E"
if not defined PYW (
    echo Python isn't installed. Run Install.bat first.
    pause
    exit /b 1
)
start "" "%PYW%" "%~dp0helper.py"
