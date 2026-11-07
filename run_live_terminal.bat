@echo off
title DELTA FUTURES STATISTICAL ARBITRAGE LIVE TRADER
echo ============================================================================
echo   STARTING DELTA FUTURES STATISTICAL ARBITRAGE LIVE TRADING ENGINE
echo ============================================================================
cd /d "%~dp0"
set "PYTHON_EXE=C:\Users\MSIGV\AppData\Local\Programs\Python\Python311\python.exe"
if exist "%PYTHON_EXE%" (
    "%PYTHON_EXE%" paper_trade.py --live --exchange delta --interval 3
) else (
    python paper_trade.py --live --exchange delta --interval 3
)
pause
