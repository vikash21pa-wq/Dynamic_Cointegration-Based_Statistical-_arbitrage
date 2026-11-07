@echo off
title DELTA FUTURES STATISTICAL ARBITRAGE LIVE TRADER - DUAL-PAIR CONCURRENT
echo ============================================================================
echo   DELTA FUTURES STATISTICAL ARBITRAGE LIVE TRADING ENGINE
echo ============================================================================
echo   Active Portfolio Pairs (Strict Maximum 2 Pairs):
echo     - Pair 1: BTCUSD / ETHUSD  (Major Anchor, 10%% Allocation)
echo     - Pair 2: SOLUSD / AVAXUSD (Layer-1 Beta, 10%% Allocation)
echo ============================================================================
echo.
echo   [1] Run BOTH Pairs Simultaneously (Unified Dual-Pair Terminal Dashboard)
echo   [2] Run BTCUSD / ETHUSD only
echo   [3] Run SOLUSD / AVAXUSD only
echo   [4] Launch Both Pairs in 2 Separate Windows
echo.
set /p choice="Select option [1, 2, 3, or 4] (default: 1 - BOTH PAIRS): "
if "%choice%"=="" set choice=1

cd /d "%~dp0"
set "PYTHON_EXE=C:\Users\MSIGV\AppData\Local\Programs\Python\Python311\python.exe"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=python"

if "%choice%"=="1" (
    echo Starting Both Pairs Simultaneously (Unified Dashboard)...
    "%PYTHON_EXE%" paper_trade.py --live --exchange delta --interval 3
) else if "%choice%"=="2" (
    echo Starting Pair 1: BTCUSD/ETHUSD...
    "%PYTHON_EXE%" paper_trade.py --live --exchange delta --pair BTCUSD/ETHUSD --interval 3
) else if "%choice%"=="3" (
    echo Starting Pair 2: SOLUSD/AVAXUSD...
    "%PYTHON_EXE%" paper_trade.py --live --exchange delta --pair SOLUSD/AVAXUSD --interval 3
) else if "%choice%"=="4" (
    echo Launching Pair 1: BTCUSD/ETHUSD in window 1...
    start "DELTA STAT-ARB - BTCUSD/ETHUSD" "%PYTHON_EXE%" paper_trade.py --live --exchange delta --pair BTCUSD/ETHUSD --interval 3
    timeout /t 2 >nul
    echo Launching Pair 2: SOLUSD/AVAXUSD in window 2...
    start "DELTA STAT-ARB - SOLUSD/AVAXUSD" "%PYTHON_EXE%" paper_trade.py --live --exchange delta --pair SOLUSD/AVAXUSD --interval 3
    echo Both live trading engines launched in separate windows.
) else (
    echo Defaulting to Both Pairs Simultaneously...
    "%PYTHON_EXE%" paper_trade.py --live --exchange delta --interval 3
)
pause
