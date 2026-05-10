@echo off
echo ========================================
echo  OI Crypto Trader - Setup
echo ========================================

cd /d "C:\Users\DeAL\OneDrive\Desktop\OI_Crypto_Trader"

echo.
echo [1/4] Folder structure bana raha hoon...
mkdir python\core 2>nul
mkdir python\tests 2>nul
mkdir mql5\Experts 2>nul
mkdir signals 2>nul

echo [2/4] __init__.py files bana raha hoon...
echo. > python\__init__.py
echo """OI Trading System.""" > python\core\__init__.py
echo from .oi_fetcher import OISnapshot, OIFetcher, BinanceOIProvider, BybitOIProvider, CoinGlassOIProvider >> python\core\__init__.py
echo from .oi_processor import OIMetrics, OIProcessor, OIValidator, TrendClassifier >> python\core\__init__.py
echo from .signal_publisher import SignalPublisher, JSONSignalPublisher, SQLiteSignalLogger >> python\core\__init__.py
echo. > python\tests\__init__.py

echo [3/4] Requirements install ho rahi hain...
pip install requests pandas numpy pytest --quiet

echo [4/4] Setup complete!
echo.
echo ========================================
echo  Ab yeh karo:
echo  1. Upar se sari .py files download karo
echo  2. Sahi folders mein rakho
echo  3. run.bat chalao
echo ========================================
pause
