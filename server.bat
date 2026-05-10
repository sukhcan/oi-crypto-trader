@echo off
echo ========================================
echo  OI Dashboard Server
echo ========================================
cd /d "C:\Users\DeAL\OneDrive\Desktop\OI_Crypto_Trader"

echo.
echo  Dashboard: http://localhost:8765/dashboard
echo  Ctrl+C se band karo
echo.

"C:\Program Files\PyManager\python.exe" server.py
pause
