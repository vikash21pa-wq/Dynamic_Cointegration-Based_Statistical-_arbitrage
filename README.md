# Dynamic Cointegration-Based Statistical Arbitrage in Cryptocurrency Markets

[![GitHub Pages Frontend](https://img.shields.io/badge/Live%20Frontend-GitHub%20Pages-06b6d4?style=for-the-badge&logo=react&logoColor=white)](https://vikash21pa-wq.github.io/Dynamic_Cointegration-Based_Statistical-_arbitrage/)
[![FastAPI Backend](https://img.shields.io/badge/FastAPI-Backend%20API-10b981?style=for-the-badge&logo=fastapi&logoColor=white)](http://localhost:8000)
[![Swagger API Docs](https://img.shields.io/badge/API%20Docs-Swagger%20UI-8b5cf6?style=for-the-badge&logo=swagger&logoColor=white)](http://localhost:8000/docs)
[![Deploy to Render](https://img.shields.io/badge/Deploy%20Backend-Render%20Cloud-black?style=for-the-badge&logo=render)](https://render.com/deploy?repo=https://github.com/vikash21pa-wq/Dynamic_Cointegration-Based_Statistical-_arbitrage)

> **Live Links to Open Dashboard & Backend:**
> - 🌐 **[Click to Open Live Frontend Dashboard](https://vikash21pa-wq.github.io/Dynamic_Cointegration-Based_Statistical-_arbitrage/)** (Hosted on GitHub Pages)
> - ⚡ **[Click to Open Local FastAPI Server](http://localhost:8000)** (When running `app.py` or `run_dashboard.bat`)
> - 📖 **[Click to Open Interactive Swagger API Docs](http://localhost:8000/docs)** (Full interactive REST API playground)

Research-grade quantitative trading framework for high-frequency cryptocurrency pairs trading and dynamic statistical arbitrage.

## System Architecture

```
dynamic_crypto_pairs/
├── config.py             # System hyperparameters, universe, fee & risk specifications
├── main.py               # End-to-end execution pipeline (Data -> Audit -> Screening -> Simulation)
├── requirements.txt      # Production package dependencies
├── README.md             # Research documentation & execution guide
├── src/
│   ├── data_loader.py    # Binance USDT-M Futures historical data downloader & synthetic generator
│   ├── preprocessing.py  # Timestamp synchronization, missing candle audit, log transformations
│   ├── pair_selection.py # Engle-Granger 2-step, ADF tests, Benjamini-Hochberg FDR correction, Half-life
│   ├── kalman_filter.py  # Online dynamic state-space estimation with Joseph-form covariance updates
│   ├── signals.py        # Crossing-based state machine, rolling Z-score, emergency stops
│   ├── execution.py      # Gross notional sizing, next-bar open execution, turnover, fee & funding deduction
│   ├── risk_management.py# Relationship breakdown detection & portfolio drawdown circuit breakers
│   ├── backtester.py     # Bar-by-bar walk-forward simulation engine with zero lookahead bias
│   └── performance.py    # Annualized Sharpe, Sortino, Calmar, drawdown, and trade distribution metrics
├── tests/                # Comprehensive unit test battery (Pytest)
├── notebooks/            # Exploratory research notebooks
└── data/
    ├── raw/              # Cached 5m OHLCV CSVs
    └── processed/        # Aligned price matrices, screening results, quality reports, experiment summaries
```

## Mathematical Foundations

### 1. Log Price Transformation
$$X_t = \ln(P_{A,t}), \quad Y_t = \ln(P_{B,t})$$

### 2. Log Return Correlation Screening
$$\rho_{AB} = \frac{\text{Cov}(\Delta X, \Delta Y)}{\sigma_{\Delta X} \sigma_{\Delta Y}}, \quad |\rho_{AB}| \ge 0.70$$

### 3. Engle-Granger Cointegration & Multiple Testing Correction
Cointegrating regression via OLS:
$$X_t = \alpha + \beta Y_t + \epsilon_t$$
Residual stationarity tested via Augmented Dickey-Fuller (ADF) with AIC lag selection.
To prevent false discoveries across all $\frac{N(N-1)}{2}$ candidate pairs, the **Benjamini-Hochberg False Discovery Rate (FDR)** procedure is applied:
$$q_{(k)} = \min_{j \ge k} \left( \min\left(1.0, \frac{m}{j} p_{(j)}\right) \right) \le \alpha_{FDR}$$

### 4. Mean-Reversion Half-Life
$$\Delta S_t = \lambda S_{t-1} + \eta_t, \quad HL = \frac{-\ln(2)}{\lambda}$$

### 5. Dynamic Kalman Filter State Space
$$\theta_t = \begin{bmatrix} \alpha_t \\ \beta_t \end{bmatrix}, \quad X_t = \begin{bmatrix} 1 & Y_t \end{bmatrix} \theta_t + v_t, \quad v_t \sim \mathcal{N}(0, R)$$
$$\theta_t = \theta_{t-1} + w_t, \quad w_t \sim \mathcal{N}(0, Q), \quad Q = \frac{\delta}{1-\delta} I_2$$
Covariance update implemented using the **Joseph form** to guarantee positive semi-definiteness:
$$P_t = (I - K_t H_t) P_{t|t-1} (I - K_t H_t)^T + K_t R K_t^T$$

### 6. Constrained Gross Exposure Sizing & Execution
To fix total pair gross notional exposure to target budget $G$:
$$N_A = \frac{G}{1 + |\beta|}, \quad N_B = \frac{|\beta| G}{1 + |\beta|}, \quad N_A + N_B = G$$
Signal calculated at bar $t$ close is strictly executed at bar $t+1$ open.

---

## Quickstart & Terminal Command Reference

### 1. Environment Setup
```bash
pip install -r requirements.txt
```

### 2. Run Comprehensive Unit Tests
```bash
python -m pytest -q
```

### 3. Terminal CLI Commands

| Command | Description |
| :--- | :--- |
| `python main.py -r` | **Instant Results**: Displays the formatted performance benchmark & screening rankings in < 0.1s |
| `python main.py` | Runs standard 30-day pipeline (audits, screens 45 pairs, backtests top cointegrated pair) |
| `python main.py --screen-only` | Screens all 45 pairs for cointegration & FDR correction without running backtests |
| `python main.py --synthetic` | Runs entire pipeline on calibrated synthetic market data (offline mode) |
| `python main.py --pair BTCUSDT/ETHUSDT` | Runs backtest on a specific pair of your choice |
| `python main.py --method ols` | Simulates only Model M1 (Static OLS) |
| `python main.py --method kalman` | Simulates only Model M3 (Dynamic Kalman Filter) |
| `python main.py --capital 25000 --allocation 0.20` | Customizes portfolio capital ($25k) and per-pair allocation (20%) |
| `python main.py --quiet` | Suppresses debug logs, showing only clean data and performance tables |

### 4. Real-Time Paper Trading Dashboard

A real-time paper trading system is built in to monitor live price feeds, calculate rolling Z-scores, and simulate virtual order execution with realistic exchange fees and slippage:

```bash
# 1. Interactive demo replay (fast bar-by-bar simulation in the terminal)
python paper_trade.py --replay --bars 100 --speed 0.05

# 2. Live continuous monitoring (polls Binance Futures)
python paper_trade.py --live

# 3. Check current paper trading portfolio status and PnL
python paper_trade.py --status
```

Credentials are saved in `.env` (gitignored):
```env
BINANCE_API_KEY=qfx89x...7Wq1
BINANCE_API_SECRET=your_secret_key_here
BINANCE_TESTNET=True
```

### 5. Generated Artifacts
Saved in `results/` and `data/processed/`:
- `experiment_001_summary.json`: Detailed JSON summary comparing M1 and M3
- `experiment_001_comparison.csv`: Side-by-side performance metrics table
- `pair_screening_results.csv`: Complete Engle-Granger, ADF, and FDR screening statistics for all 45 pairs
- `data_quality_report.csv`: Gap detection, outlier audits, and candle counts
- `m1_trades.csv` / `m3_trades.csv`: Detailed trade-by-trade execution logs
