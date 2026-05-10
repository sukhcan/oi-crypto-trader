@echo off
echo ============================================
echo  Crypto OI Fetcher Pro - Setup & Run
echo ============================================
echo.

:: ── Python dhundho ───────────────────────────────────────────
set PYTHON=
for %%P in (
    "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python39\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python38\python.exe"
    "C:\Python313\python.exe"
    "C:\Python312\python.exe"
    "C:\Python311\python.exe"
    "C:\Python310\python.exe"
    "C:\Python39\python.exe"
    "C:\Program Files\Python313\python.exe"
    "C:\Program Files\Python312\python.exe"
    "C:\Program Files\Python311\python.exe"
    "C:\Program Files\Python310\python.exe"
) do (
    if exist %%P (
        set PYTHON=%%P
        goto :found
    )
)

where python >nul 2>&1
if not errorlevel 1 ( set PYTHON=python && goto :found )

echo ============================================
echo  ERROR: Python nahi mila!
echo ============================================
echo.
echo  Abhi yeh karo:
echo  1. https://www.python.org/downloads/
echo  2. Download karo aur install karo
echo  3. Install karte waqt:
echo     [x] Add Python to PATH  -- YEH ZAROOR TICK KARO!
echo  4. PC restart karo
echo  5. Phir yeh file dobara chalao
echo.
pause
exit /b 1

:found
echo  Python mila: %PYTHON%
echo.

:: ── Dependencies ─────────────────────────────────────────────
echo [1/2] Dependencies install kar raha hoon...
echo       (pehli baar thoda waqt lagega)
echo.
%PYTHON% -m pip install --upgrade pip --quiet
%PYTHON% -m pip install requests pandas MetaTrader5 --quiet
if errorlevel 1 (
    echo ERROR: Install fail hua!
    pause
    exit /b 1
)
echo  Dependencies OK
echo.

:: ── Run ──────────────────────────────────────────────────────
echo [2/2] Crypto OI Fetcher Pro chal raha hai...
echo.
%PYTHON% crypto_oi_fetcher_pro.py

if errorlevel 1 (
    echo.
    echo ============================================
    echo  Software band ho gaya — error aaya
    echo ============================================
    pause
)
