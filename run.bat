@echo off
echo ========================================
echo  OI Crypto Trader - Live Mode
echo ========================================
cd /d "C:\Users\DeAL\OneDrive\Desktop\OI_Crypto_Trader"

echo.
echo Symbol: BTCUSDT
echo Interval: 30 seconds
echo Signal file: signals\oi_signal.json
echo.
echo Ctrl+C se band karo
echo ========================================
echo.

python -m python.main --symbol BTCUSDT --interval 30 --log-level INFO --signal-path signals\oi_signal.json --db-path signals\oi_signals.db

pause
