@echo off
REM ============================================================
REM  Builds BevMargin.exe, the Windows setup file and a portable zip.
REM  Needs: Python 3.10+ (python.org, tick "Add python.exe to PATH")
REM         Inno Setup 6 (jrsoftware.org/isdl.php) for the setup file
REM ============================================================
cd /d "%~dp0"
if not exist Output mkdir Output

echo [1/4] Installing build tools...
python -m pip install --upgrade pip >nul
python -m pip install -r requirements.txt || goto :err

echo [2/4] Running tests...
python tests\test_core.py || goto :err

echo [3/4] Building program folder with PyInstaller...
rmdir /s /q build dist 2>nul
python -m PyInstaller --noconfirm --windowed --name BevMargin --icon assets\app.ico ^
  --add-data "assets;assets" --collect-submodules reportlab.graphics.barcode --hidden-import cryptography main.py || goto :err

echo [4/4] Building setup file with Inno Setup...
set ISCC=
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set ISCC="%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set ISCC="%ProgramFiles%\Inno Setup 6\ISCC.exe"
if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set ISCC="%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not defined ISCC for /f "delims=" %%I in ('where ISCC.exe 2^>nul') do set ISCC="%%I"
if not defined ISCC (
  echo.
  echo Inno Setup 6 was not found. The app itself IS built: dist\BevMargin\BevMargin.exe
  echo To get the setup file: install Inno Setup 6 from https://jrsoftware.org/isdl.php
  echo and run build.bat again, OR double-click installer.iss and press Ctrl+F9.
  echo.
  goto :portable
)
echo Using %ISCC%
%ISCC% installer.iss || goto :err
echo.
echo Setup file created in the Output folder.

:portable
echo Creating portable version (data stays next to the exe, for USB use)...
xcopy /e /i /y dist\BevMargin dist\BevMargin-Portable >nul
type nul > dist\BevMargin-Portable\portable.flag
powershell -NoProfile -Command "Compress-Archive -Force -Path dist\BevMargin-Portable\* -DestinationPath Output\BevMargin-Portable.zip" 2>nul
echo Done.
pause
exit /b 0

:err
echo.
echo BUILD FAILED - see the messages above.
pause
exit /b 1
