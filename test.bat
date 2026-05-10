@echo off
echo ========================================
echo  OI Crypto Trader - Tests
echo ========================================
cd /d "C:\Users\DeAL\OneDrive\Desktop\OI_Crypto_Trader"

echo.
pytest python\tests\test_oi_system.py -v
echo.
pause
