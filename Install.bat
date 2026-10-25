@echo off
rem PCDials installer: installs what's missing (Python, HWiNFO64, pywebview),
rem then opens PCDials Setup.  "Install.bat check" only reports, installs nothing.
setlocal
cd /d "%~dp0"
set CHECK=
if /i "%~1"=="check" set CHECK=1

echo.
echo  ===== PCDials installer =====
echo.

rem ---------------------------------------------------------------- Python
call :find_python
if defined PY (
    echo  [OK]  Python: %PY%
) else if defined CHECK (
    echo  [--]  Python: not installed
) else (
    echo  [..]  Python not found. Installing Python 3.14 ^(for your user only^)...
    winget install --id Python.Python.3.14 --exact --scope user --silent --accept-package-agreements --accept-source-agreements
    call :find_python
    if not defined PY (
        echo  [!!]  Python install didn't finish. Install it from https://www.python.org and run this again.
        goto :end
    )
    echo  [OK]  Python installed: %PY%
)

rem ---------------------------------------------------------------- HWiNFO64
set HWINFO=%ProgramFiles%\HWiNFO64\HWiNFO64.exe
if exist "%HWINFO%" (
    echo  [OK]  HWiNFO64: %HWINFO%
) else if defined CHECK (
    echo  [--]  HWiNFO64: not installed
) else (
    echo  [..]  HWiNFO64 not found. Installing ^(Windows may ask for permission^)...
    winget install --id REALiX.HWiNFO --exact --silent --accept-package-agreements --accept-source-agreements
    if exist "%HWINFO%" (echo  [OK]  HWiNFO64 installed) else (
        echo  [!!]  HWiNFO64 install didn't finish. Get it from https://www.hwinfo.com and run this again.
    )
)

rem ---------------------------------------------------------------- pywebview
if not defined PY goto :end
"%PY%" -c "import webview" 2>nul
if not errorlevel 1 (
    echo  [OK]  pywebview
) else if defined CHECK (
    echo  [--]  pywebview: not installed
) else (
    echo  [..]  Installing pywebview...
    "%PY%" -m pip install --quiet --disable-pip-version-check pywebview
    "%PY%" -c "import webview" 2>nul && (echo  [OK]  pywebview installed) || (echo  [!!]  pywebview install failed.)
)

if defined CHECK goto :end

rem ---------------------------------------------------------------- open Setup
echo.
echo  Opening PCDials Setup...
start "" "%PY:python.exe=pythonw.exe%" "%~dp0setup.py"
goto :end


:find_python
rem Look in the usual places directly (a fresh install isn't on PATH in this window yet),
rem then PATH. Skips Windows' fake "python" that only opens the Microsoft Store.
set PY=
for %%P in (
    "%LOCALAPPDATA%\Programs\Python\Python314\python.exe"
    "%ProgramFiles%\Python314\python.exe"
    "C:\Python314\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
    "%ProgramFiles%\Python313\python.exe"
    "C:\Python313\python.exe"
) do if not defined PY if exist %%P set "PY=%%~P"
if defined PY exit /b
for /f "delims=" %%E in ('python -c "import sys; print(sys.executable)" 2^>nul') do set "PY=%%E"
exit /b


:end
echo.
if not defined CHECK pause
endlocal
