@echo off
title DELTA FUTURES STATISTICAL ARBITRAGE LIVE TRADER
echo ============================================================================
echo   DELTA FUTURES STATISTICAL ARBITRAGE LIVE TRADING ENGINE (MULTI-PAIR)
echo ============================================================================
echo   Strict Quantitative Policy: Maximum 2 Active Pairs
echo.
echo   [1] BTCUSD / ETHUSD       (Primary Major-Cap Anchor)
echo   [2] SOLUSD / AVAXUSD      (Layer-1 High-Beta Cluster)
echo   [3] Run BOTH Pairs        (Launches 2 concurrent live trading windows)
echo.
set /p choice="Select trading pair [1, 2, or 3] (default: 1): "
if "%choice%"=="" set choice=1

cd /d "%~dp0"
set "PYTHON_EXE=C:\Users\MSIGV\AppData\Local\Programs\Python\Python311\python.exe"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=python"

if "%choice%"=="1" (
    echo Starting Pair 1: BTCUSD/ETHUSD...
    "%PYTHON_EXE%" paper_trade.py --live --exchange delta --pair BTCUSD/ETHUSD --interval 3
) else if "%choice%"=="2" (
    echo Starting Pair 2: SOLUSD/AVAXUSD...
    "%PYTHON_EXE%" paper_trade.py --live --exchange delta --pair SOLUSD/AVAXUSD --interval 3
) else if "%choice%"=="3" (
    echo Launching Pair 1: BTCUSD/ETHUSD in window 1...
    start "DELTA STAT-ARB - BTCUSD/ETHUSD" "%PYTHON_EXE%" paper_trade.py --live --exchange delta --pair BTCUSD/ETHUSD --interval 3
    timeout /t 2 >nul
    echo Launching Pair 2: SOLUSD/AVAXUSD in window 2...
    start "DELTA STAT-ARB - SOLUSD/AVAXUSD" "%PYTHON_EXE%" paper_trade.py --live --exchange delta --pair SOLUSD/AVAXUSD --interval 3
    echo Both live trading engines launched successfully.
) else (
    echo Invalid selection. Defaulting to BTCUSD/ETHUSD...
    "%PYTHON_EXE%" paper_trade.py --live --exchange delta --pair BTCUSD/ETHUSD --interval 3
)
pause
