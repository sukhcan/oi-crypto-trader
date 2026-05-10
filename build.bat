@echo off
title OI Fetcher Pro — Build
color 0A
cls

echo.
echo  ================================================
echo   OI Fetcher Pro v2.0 - Build Tool
echo  ================================================
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found!
    pause & exit /b 1
)

:: Activate venv
if not exist "oi_env\Scripts\activate.bat" (
    echo [INFO] Creating virtual environment...
    python -m venv oi_env
)
call oi_env\Scripts\activate.bat

:: Install packages
echo [1/3] Installing packages...
pip install pyinstaller requests pandas openpyxl --quiet
echo [OK] Done.

:: Create LICENSE.txt (required by NSIS)
echo OI Fetcher Pro v2.0 > LICENSE.txt
echo Copyright 2026 OI Trader Systems >> LICENSE.txt
echo All rights reserved. >> LICENSE.txt
echo. >> LICENSE.txt
echo This software is licensed for personal use only. >> LICENSE.txt

:: Build EXE
echo.
echo [2/3] Building EXE... (2-3 minutes)
pyinstaller --onefile --windowed --name "OI_Fetcher_Pro" --distpath "dist" --workpath "build_tmp" --specpath "build_tmp" oi_fetcher_pro.py

if errorlevel 1 (
    echo [ERROR] EXE build failed!
    pause & exit /b 1
)
echo [OK] EXE ready: dist\OI_Fetcher_Pro.exe

:: Create dist\data folder
if not exist "dist\data" mkdir dist\data

:: Build NSIS Installer
echo.
echo [3/3] Building Installer (NSIS)...

:: Find NSIS makensis.exe
set MAKENSIS=
if exist "C:\Program Files (x86)\NSIS\makensis.exe" set MAKENSIS=C:\Program Files (x86)\NSIS\makensis.exe
if exist "C:\Program Files\NSIS\makensis.exe"       set MAKENSIS=C:\Program Files\NSIS\makensis.exe

if "%MAKENSIS%"=="" (
    where makensis >nul 2>&1
    if not errorlevel 1 set MAKENSIS=makensis
)

if "%MAKENSIS%"=="" (
    echo [ERROR] NSIS not found!
    echo         Install from: https://nsis.sourceforge.io/Download
    pause & exit /b 1
)

"%MAKENSIS%" /V3 installer.nsi
if errorlevel 1 (
    echo [ERROR] NSIS installer build failed!
    echo.
    echo Possible fixes:
    echo  1. Run build.bat as Administrator (Right-click ^> Run as admin)
    echo  2. Make sure NSIS 3.x is installed
    pause & exit /b 1
)

echo.
echo  ================================================
echo   BUILD SUCCESSFUL!
echo  ================================================
echo.
echo   Setup File: OI_Fetcher_Pro_Setup.exe
echo.
echo   HOW TO INSTALL:
echo   1. Double-click OI_Fetcher_Pro_Setup.exe
echo   2. Click Next, Next, Install, Finish
echo.
echo   DEFAULT LOGIN:
echo     Username: admin
echo     Password: admin123
echo.
echo   IMPORTANT: Change password after first login!
echo  ================================================
echo.

:: Open current folder
explorer .
pause
