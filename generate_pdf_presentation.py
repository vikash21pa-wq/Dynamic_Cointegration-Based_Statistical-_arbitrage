"""
Generates the complete 11-slide presentation as a high-resolution 16:9 PDF.
Event: TECHYUVA 11.0, Buddha Degree College, GIDA, Gorakhpur (Nov 3-5, 2026)
Topic: Dynamic Cointegration-Based Statistical Arbitrage in Cryptocurrency Markets
"""

import os
from pathlib import Path
from reportlab.lib import colors
from reportlab.pdfgen import canvas

PDF_OUTPUT = Path("presentation.pdf")

# Dimensions for 16:9 Widescreen (960 x 540 points)
WIDTH = 960
HEIGHT = 540

# Color Scheme
C_BG = colors.HexColor('#0B132B')        # Deep Navy
C_CARD = colors.HexColor('#1C2541')      # Card Surface
C_BORDER = colors.HexColor('#2E3D5C')    # Subtle Border
C_CYAN = colors.HexColor('#06B6D4')      # Accent Cyan
C_EMERALD = colors.HexColor('#10B981')   # Emerald Green
C_ROSE = colors.HexColor('#F43F5E')      # Coral Rose
C_AMBER = colors.HexColor('#F59E0B')     # Amber
C_WHITE = colors.HexColor('#F1F5F9')     # Bright White
C_MUTED = colors.HexColor('#94A3B8')     # Slate Muted Text
C_DARK = colors.HexColor('#070C1E')      # Deep Inset

def draw_background(c):
    """Draws slide background."""
    c.setFillColor(C_BG)
    c.rect(0, 0, WIDTH, HEIGHT, fill=True, stroke=False)

def draw_header(c, title, category="TECHYUVA 11.0 • BUDDHA DEGREE COLLEGE, GORAKHPUR"):
    """Draws slide banner header."""
    c.setFillColor(C_CYAN)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(50, HEIGHT - 40, category.upper())
    
    c.setFillColor(C_WHITE)
    c.setFont("Helvetica-Bold", 20)
    c.drawString(50, HEIGHT - 68, title)
    
    c.setStrokeColor(C_BORDER)
    c.setLineWidth(1)
    c.line(50, HEIGHT - 78, WIDTH - 50, HEIGHT - 78)

def draw_footer(c, slide_num):
    """Draws slide footer with event info and slide number."""
    c.setStrokeColor(C_BORDER)
    c.setLineWidth(0.8)
    c.line(50, 35, WIDTH - 50, 35)
    
    c.setFillColor(C_MUTED)
    c.setFont("Helvetica", 9)
    c.drawString(50, 20, "TECHYUVA 11.0  |  Buddha Degree College, GIDA, Gorakhpur (Nov 3-5, 2026)")
    
    c.drawRightString(WIDTH - 50, 20, f"Slide {slide_num} of 11")

def draw_card(c, x, y, w, h, title=None, border_color=C_BORDER, fill_color=C_CARD):
    """Draws an elevated card with optional title."""
    c.setFillColor(fill_color)
    c.setStrokeColor(border_color)
    c.setLineWidth(1.2)
    c.roundRect(x, y, w, h, radius=8, fill=True, stroke=True)
    
    if title:
        c.setFillColor(C_CYAN)
        c.setFont("Helvetica-Bold", 12)
        c.drawString(x + 16, y + h - 24, title)


def build_pdf():
    c = canvas.Canvas(str(PDF_OUTPUT), pagesize=(WIDTH, HEIGHT))
    
    # ==========================================
    # SLIDE 1: TITLE SLIDE
    # ==========================================
    draw_background(c)
    draw_card(c, 50, 45, WIDTH - 100, HEIGHT - 90, border_color=C_CYAN)
    
    # Event Tag
    c.setFillColor(C_CYAN)
    c.setFont("Helvetica-Bold", 12)
    c.drawString(80, HEIGHT - 95, "TECHYUVA 11.0  •  ANNUAL TECHNICAL SYMPOSIUM")
    
    # College
    c.setFillColor(C_MUTED)
    c.setFont("Helvetica-Bold", 14)
    c.drawString(80, HEIGHT - 118, "BUDDHA DEGREE COLLEGE, GIDA, GORAKHPUR")
    
    # Date
    c.setFillColor(C_AMBER)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(80, HEIGHT - 138, "Event Date: 3rd to 5th November, 2026")
    
    # Main Title
    c.setFillColor(C_WHITE)
    c.setFont("Helvetica-Bold", 24)
    c.drawString(80, HEIGHT - 200, "Dynamic Cointegration-Based Statistical Arbitrage")
    c.drawString(80, HEIGHT - 232, "in Cryptocurrency Markets")
    
    # Subtitle
    c.setFillColor(C_EMERALD)
    c.setFont("Helvetica", 13)
    c.drawString(80, HEIGHT - 265, "High-Frequency Algorithmic Pairs Trading with Zero-Lookahead Simulation & Live Paper OMS")
    
    # Author details box
    c.setStrokeColor(C_BORDER)
    c.setLineWidth(1)
    c.line(80, HEIGHT - 295, WIDTH - 80, HEIGHT - 295)
    
    c.setFillColor(C_WHITE)
    c.setFont("Helvetica-Bold", 13)
    c.drawString(80, HEIGHT - 335, "Presenter: Vikash & Research Team")
    
    c.setFillColor(C_MUTED)
    c.setFont("Helvetica", 11)
    c.drawString(80, HEIGHT - 358, "Course / Branch: B.Tech / B.Sc (Computer Science / Data Science)")
    c.drawString(80, HEIGHT - 378, "Semester: Final Year  |  Department of Computer Science & Applications")
    
    # Tag in right corner
    c.setFillColor(C_CYAN)
    c.setFont("Helvetica-Bold", 10)
    c.drawRightString(WIDTH - 80, HEIGHT - 335, "Algorithmic Trading & Quantitative Finance")
    
    c.showPage()
    
    # ==========================================
    # SLIDE 2: CONTENTS
    # ==========================================
    draw_background(c)
    draw_header(c, "Table of Contents")
    draw_footer(c, 2)
    
    contents = [
        ("01", "Introduction", "Core concepts of Statistical Arbitrage and market-neutral pairs trading in crypto"),
        ("02", "Case Situation", "24/7 continuous trading universe & 8,640 5-minute candles high-frequency dataset"),
        ("03", "Key Challenge", "Non-stationarity, spurious correlations, multiple testing bias, and transaction fees"),
        ("04", "Company / Quant Strategy", "Engle-Granger testing, FDR Benjamini-Hochberg correction, and Kalman filters"),
        ("05", "Results & Impact", "30-day performance benchmark: +2.90% Net Return, 20.62 Sharpe, 96.1% Win Rate"),
        ("06", "Analysis", "Why Static OLS outperformed Dynamic Kalman Filter under microstructure friction"),
        ("07", "Key Learnings", "Mathematical discipline, execution latency management, and full-stack deployment"),
        ("08", "Conclusion & Demo", "Production-grade React terminal, zero-secret paper OMS, and GitHub architecture")
    ]
    
    for idx, (num, title, desc) in enumerate(contents):
        col = idx % 2
        row = idx // 2
        x = 50 + col * 435
        y = HEIGHT - 150 - row * 82
        
        draw_card(c, x, y, 425, 72, border_color=C_BORDER)
        c.setFillColor(C_CYAN)
        c.setFont("Helvetica-Bold", 12)
        c.drawString(x + 14, y + 46, f"{num}. {title}")
        
        c.setFillColor(C_MUTED)
        c.setFont("Helvetica", 9)
        c.drawString(x + 14, y + 26, desc)
        
    c.showPage()
    
    # ==========================================
    # SLIDE 3: INTRODUCTION
    # ==========================================
    draw_background(c)
    draw_header(c, "Introduction: Algorithmic Statistical Arbitrage")
    draw_footer(c, 3)
    
    # Left Card
    draw_card(c, 50, 55, 420, 395, title="What is Statistical Arbitrage?", border_color=C_CYAN)
    
    text_3a = [
        ("Market-Neutral Pairs Trading", "Simultaneously buying an undervalued asset while shorting an overvalued asset to hedge out broader market risk."),
        ("Cointegration vs. Correlation", "Correlation measures co-movement in returns. Cointegration establishes a true stationary long-term equilibrium: S_t = ln(P_A) - α - β ln(P_B)."),
        ("Mean-Reversion Law", "When the spread diverges beyond ±2.0 standard deviations (Z-score), statistical forces pull it back, yielding predictable alpha."),
        ("Zero Directional Risk", "Profits are generated whether Bitcoin is rallying or crashing.")
    ]
    
    curr_y = HEIGHT - 130
    for title, desc in text_3a:
        c.setFillColor(C_WHITE)
        c.setFont("Helvetica-Bold", 11)
        c.drawString(68, curr_y, f"• {title}")
        c.setFillColor(C_MUTED)
        c.setFont("Helvetica", 9.5)
        # Wrap description
        words = desc.split()
        line = ""
        curr_y -= 16
        for w in words:
            if c.stringWidth(line + " " + w, "Helvetica", 9.5) < 370:
                line += " " + w
            else:
                c.drawString(80, curr_y, line.strip())
                curr_y -= 14
                line = w
        if line:
            c.drawString(80, curr_y, line.strip())
            curr_y -= 22

    # Right Card
    draw_card(c, 490, 55, 420, 395, title="System Scope & Deliverables", border_color=C_EMERALD)
    
    text_3b = [
        ("Automated Screening Engine", "Evaluates all 45 cross-pairs in Binance USDT-M Futures using Engle-Granger two-step tests."),
        ("Multiple Hypothesis Correction", "Applies Benjamini-Hochberg False Discovery Rate (FDR) control at q ≤ 0.05 to eliminate false discoveries."),
        ("Zero-Lookahead Backtester", "Simulates realistic order execution at bar t+1 Open with exchange taker fees (0.05%) and slippage (0.02%)."),
        ("Production Web Terminal", "React 18 frontend + FastAPI backend + local paper trading engine without needing private API secret keys.")
    ]
    
    curr_y = HEIGHT - 130
    for title, desc in text_3b:
        c.setFillColor(C_CYAN)
        c.setFont("Helvetica-Bold", 11)
        c.drawString(508, curr_y, f"• {title}")
        c.setFillColor(C_MUTED)
        c.setFont("Helvetica", 9.5)
        words = desc.split()
        line = ""
        curr_y -= 16
        for w in words:
            if c.stringWidth(line + " " + w, "Helvetica", 9.5) < 370:
                line += " " + w
            else:
                c.drawString(520, curr_y, line.strip())
                curr_y -= 14
                line = w
        if line:
            c.drawString(520, curr_y, line.strip())
            curr_y -= 22

    c.showPage()
    
    # ==========================================
    # SLIDE 4: CASE SITUATION
    # ==========================================
    draw_background(c)
    draw_header(c, "Case Situation: Market Environment & Dataset")
    draw_footer(c, 4)
    
    # 3 Cards Layout
    card_w = 275
    gap = 18
    
    # Card 1: Crypto Microstructure
    draw_card(c, 50, 55, card_w, 395, title="Crypto Microstructure", border_color=C_ROSE)
    bullets_4a = [
        "Continuous 24/7/365 trading with no opening/closing bell or market halts.",
        "Extreme volatility and frequent leverage liquidation cascades.",
        "Orderbook depth shifts rapidly during macro events.",
        "Traditional equity stat-arb assumptions fail in crypto due to fat-tailed returns."
    ]
    y_b = HEIGHT - 130
    for item in bullets_4a:
        c.setFillColor(C_WHITE)
        c.setFont("Helvetica", 10)
        words = item.split()
        line = "▶ "
        for w in words:
            if c.stringWidth(line + " " + w, "Helvetica", 10) < card_w - 30:
                line += " " + w
            else:
                c.drawString(66, y_b, line.strip())
                y_b -= 14
                line = "   " + w
        c.drawString(66, y_b, line.strip())
        y_b -= 20
        
    # Card 2: Experimental Dataset
    draw_card(c, 50 + card_w + gap, 55, card_w, 395, title="Empirical Dataset", border_color=C_CYAN)
    bullets_4b = [
        "Venue: Binance USDT-M Perpetual Futures (deepest global liquidity pool).",
        "Asset Universe (10): BTC, ETH, SOL, BNB, XRP, ADA, LINK, DOGE, AVAX, LTC.",
        "Frequency: 5-minute continuous OHLCV candles.",
        "Horizon: 8,640 consecutive synchronized bars (30 full trading days).",
        "Cross-Pairs: 45 unique combinations screened."
    ]
    y_b = HEIGHT - 130
    for item in bullets_4b:
        c.setFillColor(C_WHITE)
        c.setFont("Helvetica", 10)
        words = item.split()
        line = "▶ "
        for w in words:
            if c.stringWidth(line + " " + w, "Helvetica", 10) < card_w - 30:
                line += " " + w
            else:
                c.drawString(50 + card_w + gap + 16, y_b, line.strip())
                y_b -= 14
                line = "   " + w
        c.drawString(50 + card_w + gap + 16, y_b, line.strip())
        y_b -= 18

    # Card 3: Execution Constraints
    draw_card(c, 50 + 2 * (card_w + gap), 55, card_w, 395, title="Execution Realism", border_color=C_AMBER)
    bullets_4c = [
        "Initial Portfolio: $10,000 USDT capital base.",
        "Pair Sizing: 10% allocation ($1,000 target gross exposure per pair).",
        "Exchange Taker Fee: 0.05% per leg (0.10% round-trip friction).",
        "Execution Slippage: 0.02% modeled adverse fill on both entry and exit.",
        "Signal Integrity: Computed at Bar t Close, filled strictly at Bar t+1 Open."
    ]
    y_b = HEIGHT - 130
    for item in bullets_4c:
        c.setFillColor(C_WHITE)
        c.setFont("Helvetica", 10)
        words = item.split()
        line = "▶ "
        for w in words:
            if c.stringWidth(line + " " + w, "Helvetica", 10) < card_w - 30:
                line += " " + w
            else:
                c.drawString(50 + 2 * (card_w + gap) + 16, y_b, line.strip())
                y_b -= 14
                line = "   " + w
        c.drawString(50 + 2 * (card_w + gap) + 16, y_b, line.strip())
        y_b -= 18

    c.showPage()
    
    # ==========================================
    # SLIDE 5: KEY CHALLENGE
    # ==========================================
    draw_background(c)
    draw_header(c, "Key Challenge: Pitfalls in High-Frequency Stat-Arb")
    draw_footer(c, 5)
    
    challenges = [
        ("1. Spurious Correlation & Non-Stationarity",
         "Raw crypto prices are non-stationary I(1) random walks. High correlation does NOT imply mean-reversion. Trading non-cointegrated pairs leads to permanent capital divergence."),
        ("2. Data Snooping in Multi-Pair Screening",
         "Testing 45 candidate pairs at α = 0.05 yields an expected ~2.25 false discoveries purely by chance. Overfitting to past noise leads to catastrophic breakdown out-of-sample."),
        ("3. Microstructure Friction & Fee Drag",
         "In 5-minute high-frequency trading, small paper profits are easily eaten by 0.05% taker fees and 0.02% slippage unless trade frequency and profit targets are strictly calibrated."),
        ("4. Kalman Filter Over-Adaptation in Micro-Noise",
         "Adaptive state-space estimation can mistake random tick noise for structural shifts in hedge ratio β, triggering excessive turnover and severe whipsaw losses.")
    ]
    
    for idx, (title, desc) in enumerate(challenges):
        col = idx % 2
        row = idx // 2
        x = 50 + col * 435
        y = HEIGHT - 135 - row * 175
        
        draw_card(c, x, y, 425, 150, border_color=C_ROSE)
        c.setFillColor(C_ROSE)
        c.setFont("Helvetica-Bold", 12)
        c.drawString(x + 16, y + 124, title)
        
        c.setFillColor(C_WHITE)
        c.setFont("Helvetica", 9.5)
        words = desc.split()
        line = ""
        c_y = y + 102
        for w in words:
            if c.stringWidth(line + " " + w, "Helvetica", 9.5) < 390:
                line += " " + w
            else:
                c.drawString(x + 16, c_y, line.strip())
                c_y -= 16
                line = w
        if line:
            c.drawString(x + 16, c_y, line.strip())

    c.showPage()
    
    # ==========================================
    # SLIDE 6: COMPANY / QUANT STRATEGY
    # ==========================================
    draw_background(c)
    draw_header(c, "Company Strategy: End-to-End Quantitative Pipeline")
    draw_footer(c, 6)
    
    steps = [
        ("Step 1: Ingestion & Alignment", "Download continuous 5m OHLCV tick data from Binance, verify zero missing candles, and compute log prices X_t = ln(P_A), Y_t = ln(P_B)."),
        ("Step 2: Engle-Granger Cointegration", "Run OLS regression X_t = α + β Y_t + ε_t. Test residual stationarity via Augmented Dickey-Fuller (ADF) with constrained lag selection."),
        ("Step 3: Benjamini-Hochberg FDR Control", "Sort p-values across all 45 pairs: q_(k) = min (m/k * p_(k)) ≤ 0.05. Rejects 80%+ spurious pairs to ensure statistically proven cointegration."),
        ("Step 4: Half-Life Mean Reversion Filter", "Fit Ornstein-Uhlenbeck process ΔS_t = λ S_(t-1) + η_t. Keep only pairs with fast reversion: HL = -ln(2)/λ ≤ 24.0 hours."),
        ("Step 5: Dynamic State Machine & Sizing", "Compute rolling Z-score: Z_t = (S_t - μ) / σ. Enter Long Spread at Z ≤ -2.0, Short Spread at Z ≥ +2.0, exit at Z crossing 0.0. Fixed $1k sizing."),
        ("Step 6: Live Paper OMS & Web UI", "Real-time order fill simulation with taker fees & slippage. Stream live status to responsive React 18 & FastAPI terminal.")
    ]
    
    for idx, (title, desc) in enumerate(steps):
        col = idx % 2
        row = idx // 2
        x = 50 + col * 435
        y = HEIGHT - 130 - row * 115
        
        draw_card(c, x, y, 425, 100, border_color=C_CYAN)
        c.setFillColor(C_CYAN)
        c.setFont("Helvetica-Bold", 11)
        c.drawString(x + 16, y + 78, title)
        
        c.setFillColor(C_WHITE)
        c.setFont("Helvetica", 9)
        words = desc.split()
        line = ""
        c_y = y + 58
        for w in words:
            if c.stringWidth(line + " " + w, "Helvetica", 9) < 390:
                line += " " + w
            else:
                c.drawString(x + 16, c_y, line.strip())
                c_y -= 14
                line = w
        if line:
            c.drawString(x + 16, c_y, line.strip())

    c.showPage()
    
    # ==========================================
    # SLIDE 7: RESULTS / IMPACT
    # ==========================================
    draw_background(c)
    draw_header(c, "Results & Impact: Empirical Benchmark Performance")
    draw_footer(c, 7)
    
    # KPI Top Bar
    kpis = [
        ("Net Return (30d)", "+2.90%", "Annualized: +41.6%", C_EMERALD),
        ("Sharpe Ratio", "20.62", "Risk-Adjusted Alpha", C_CYAN),
        ("Max Drawdown", "-0.11%", "Near-Zero Downside", C_EMERALD),
        ("Win Rate", "96.05%", "73 Wins / 3 Losses", C_AMBER)
    ]
    for idx, (label, val, sub, col_c) in enumerate(kpis):
        x = 50 + idx * 218
        draw_card(c, x, HEIGHT - 170, 208, 75, border_color=col_c)
        c.setFillColor(C_MUTED)
        c.setFont("Helvetica-Bold", 8.5)
        c.drawString(x + 12, HEIGHT - 115, label.upper())
        
        c.setFillColor(col_c)
        c.setFont("Helvetica-Bold", 18)
        c.drawString(x + 12, HEIGHT - 140, val)
        
        c.setFillColor(C_MUTED)
        c.setFont("Helvetica", 8)
        c.drawString(x + 12, HEIGHT - 158, sub)

    # Benchmark Table Card
    draw_card(c, 50, 52, WIDTH - 100, HEIGHT - 240, title="Model Benchmark Comparison: Static OLS vs. Dynamic Kalman Filter")
    
    table_rows = [
        ("Performance Metric", "Model M1: Static OLS", "Model M3: Dynamic Kalman Filter", "Strategy Edge & Significance"),
        ("Total Net Return / Profit", "+$290.22 (+2.90%)", "-$389.38 (-3.89%)", "+6.79% alpha spread in favor of Static OLS"),
        ("Annualized Sharpe Ratio", "20.62", "-45.91", "Exceptional risk-adjusted return under static cointegration"),
        ("Maximum Drawdown", "-0.11%", "-3.89%", "Zero severe drawdown regimes observed in Model M1"),
        ("Win Rate (% Trades)", "96.05% (73 of 76)", "18.45% (62 of 336)", "M1 selectively trades only high-probability extremes"),
        ("Profit Factor", "30.66", "0.10", "Asymmetric profit distribution in favor of static model"),
        ("Average Holding Duration", "2.15 hours (25.8 bars)", "0.58 hours (7.0 bars)", "Static model aligns with true Ornstein-Uhlenbeck half-life"),
        ("Total Friction Paid", "$108.13", "$461.84", "Kalman over-traded 4.4x more, destroying equity via fee drag")
    ]
    
    y_row = HEIGHT - 215
    for r_idx, row in enumerate(table_rows):
        if r_idx == 0:
            c.setFillColor(C_CYAN)
            c.setFont("Helvetica-Bold", 9)
        else:
            c.setFillColor(C_WHITE if r_idx % 2 == 1 else C_MUTED)
            c.setFont("Helvetica", 8.5)
            
        c.drawString(68, y_row, row[0])
        c.drawString(275, y_row, row[1])
        c.drawString(455, y_row, row[2])
        c.drawString(670, y_row, row[3])
        
        c.setStrokeColor(C_BORDER)
        c.setLineWidth(0.5)
        c.line(68, y_row - 4, WIDTH - 68, y_row - 4)
        y_row -= 23

    c.showPage()
    
    # ==========================================
    # SLIDE 8: ANALYSIS
    # ==========================================
    draw_background(c)
    draw_header(c, "Quantitative Analysis: The Kalman Overfitting Paradox")
    draw_footer(c, 8)
    
    # Left Card: Why Static Succeeded
    draw_card(c, 50, 55, 420, 395, title="Why Static OLS Succeeded (M1)", border_color=C_EMERALD)
    points_8a = [
        ("Stable Mathematical Anchor", "Calibrated parameters (α = 1.4648, β = 1.1678) reflected the structural cointegrating relationship between BTC and ETH across the full 30 days."),
        ("Patience in Entry Execution", "Waited strictly for large ±2.0σ deviations, entering only 76 high-probability round-trips over 8,640 bars."),
        ("Natural Mean-Reversion", "Gave trades sufficient time to revert (average holding duration = 2.15 hours), matching the empirical half-life of 1.19 hours."),
        ("Minimal Fee Overhead", "Kept total transaction costs to just $108.13, preserving over 73% of gross trading profits.")
    ]
    c_y = HEIGHT - 130
    for title, desc in points_8a:
        c.setFillColor(C_EMERALD)
        c.setFont("Helvetica-Bold", 10.5)
        c.drawString(68, c_y, f"✔ {title}")
        c.setFillColor(C_WHITE)
        c.setFont("Helvetica", 9)
        c_y -= 14
        words = desc.split()
        line = ""
        for w in words:
            if c.stringWidth(line + " " + w, "Helvetica", 9) < 375:
                line += " " + w
            else:
                c.drawString(80, c_y, line.strip())
                c_y -= 13
                line = w
        if line:
            c.drawString(80, c_y, line.strip())
            c_y -= 18

    # Right Card: Why Kalman Failed
    draw_card(c, 490, 55, 420, 395, title="Why Dynamic Kalman Failed (M3)", border_color=C_ROSE)
    points_8b = [
        ("Over-Adapting to Micro-Noise", "At 5-minute frequency, the Kalman filter continuously shifted β in response to temporary orderbook imbalances rather than true economic regime shifts."),
        ("The Moving Goalpost Trap", "As the spread expanded, the Kalman filter adjusted β to absorb the divergence, prematurely moving the equilibrium and closing trades at false inflection points."),
        ("Severe Turnover Explosion", "Executed 336 round-trip trades (4.4x more than static), creating continuous churning and whipsaws."),
        ("Catastrophic Fee Drag", "Accumulated $461.84 in taker fees and slippage, wiping out capital and yielding a -45.91 Sharpe ratio.")
    ]
    c_y = HEIGHT - 130
    for title, desc in points_8b:
        c.setFillColor(C_ROSE)
        c.setFont("Helvetica-Bold", 10.5)
        c.drawString(508, c_y, f"✘ {title}")
        c.setFillColor(C_WHITE)
        c.setFont("Helvetica", 9)
        c_y -= 14
        words = desc.split()
        line = ""
        for w in words:
            if c.stringWidth(line + " " + w, "Helvetica", 9) < 375:
                line += " " + w
            else:
                c.drawString(520, c_y, line.strip())
                c_y -= 13
                line = w
        if line:
            c.drawString(520, c_y, line.strip())
            c_y -= 18

    c.showPage()
    
    # ==========================================
    # SLIDE 9: KEY LEARNINGS
    # ==========================================
    draw_background(c)
    draw_header(c, "Key Learnings & Quant Insights")
    draw_footer(c, 9)
    
    learnings = [
        ("1. Complexity Does Not Guarantee Alpha",
         "Sophisticated time-varying algorithms (like Kalman Filters) often underperform simpler static regressions in noisy high-frequency regimes due to parameter variance and fee multiplication."),
        ("2. Execution Friction Dominates Strategy PnL",
         "Theoretical paper returns without modeled taker fees (0.05%) and slippage (0.02%) are completely misleading. Real-world statistical arbitrage is an optimization against transaction costs."),
        ("3. Statistical Hygiene Prevents Overfitting",
         "Controlling the False Discovery Rate (FDR) via Benjamini-Hochberg is indispensable when mining hundreds of asset combinations to avoid trading random statistical artifacts."),
        ("4. Full-Stack Systems Engineering",
         "Building a real quant system requires uniting mathematical modeling (NumPy/Pandas/Statsmodels), backtesting integrity, async API backends (FastAPI), and responsive monitoring (React 18).")
    ]
    
    for idx, (title, desc) in enumerate(learnings):
        y = HEIGHT - 135 - idx * 78
        draw_card(c, 50, y, WIDTH - 100, 68, border_color=C_CYAN)
        
        c.setFillColor(C_CYAN)
        c.setFont("Helvetica-Bold", 11)
        c.drawString(68, y + 46, title)
        
        c.setFillColor(C_WHITE)
        c.setFont("Helvetica", 9.5)
        c.drawString(68, y + 24, desc)

    c.showPage()
    
    # ==========================================
    # SLIDE 10: CONCLUSION
    # ==========================================
    draw_background(c)
    draw_header(c, "Conclusion: Summary of Achievements")
    draw_footer(c, 10)
    
    draw_card(c, 50, 55, WIDTH - 100, 395, border_color=C_EMERALD)
    
    concl = [
        ("Research-Grade Quantitative Rigor", "Engineered a robust pairs trading framework grounded in Engle-Granger cointegration, Augmented Dickey-Fuller tests, and Benjamini-Hochberg FDR control."),
        ("Proven Empirical Edge", "Achieved +2.90% net 30-day return (41.6% annualized) with an exceptional 20.62 Sharpe ratio and 96.05% win rate on BTC/ETH futures, including realistic trading costs."),
        ("Solved Zero-Lookahead Bias", "All signals evaluated strictly at candle close and filled at next-bar open, preventing lookahead leakage present in naive backtesters."),
        ("Production-Ready Full-Stack Software", "Created a standalone simulated Order Management System (OMS) that paper-trades live public orderbooks with zero API secret keys required."),
        ("Open Source & Cloud Deployed", "Full code repository, test suites, React terminal, and documentation publicly accessible on GitHub and GitHub Pages.")
    ]
    
    c_y = HEIGHT - 130
    for title, desc in concl:
        c.setFillColor(C_EMERALD)
        c.setFont("Helvetica-Bold", 11.5)
        c.drawString(72, c_y, f"✔  {title}")
        c.setFillColor(C_WHITE)
        c.setFont("Helvetica", 10)
        c_y -= 16
        c.drawString(90, c_y, desc)
        c_y -= 26

    c.showPage()
    
    # ==========================================
    # SLIDE 11: THANK YOU / Q&A
    # ==========================================
    draw_background(c)
    draw_card(c, 100, 70, WIDTH - 200, HEIGHT - 140, border_color=C_CYAN)
    
    c.setFillColor(C_CYAN)
    c.setFont("Helvetica-Bold", 36)
    c.drawCentredString(WIDTH / 2, HEIGHT - 150, "THANK YOU!")
    
    c.setFillColor(C_WHITE)
    c.setFont("Helvetica-Bold", 18)
    c.drawCentredString(WIDTH / 2, HEIGHT - 190, "Questions & Answers (Q/A)")
    
    c.setFillColor(C_AMBER)
    c.setFont("Helvetica-Bold", 12)
    c.drawCentredString(WIDTH / 2, HEIGHT - 230, "TECHYUVA 11.0  |  BUDDHA DEGREE COLLEGE, GIDA, GORAKHPUR")
    
    c.setStrokeColor(C_BORDER)
    c.setLineWidth(1)
    c.line(180, HEIGHT - 255, WIDTH - 180, HEIGHT - 255)
    
    c.setFillColor(C_MUTED)
    c.setFont("Helvetica", 11)
    c.drawCentredString(WIDTH / 2, HEIGHT - 290, "GitHub: https://github.com/vikash21pa-wq/Dynamic_Cointegration-Based_Statistical-_arbitrage")
    
    c.setFillColor(C_EMERALD)
    c.setFont("Helvetica-Bold", 11)
    c.drawCentredString(WIDTH / 2, HEIGHT - 315, "Live Web Terminal: https://vikash21pa-wq.github.io/Dynamic_Cointegration-Based_Statistical-_arbitrage/")
    
    c.setFillColor(C_WHITE)
    c.setFont("Helvetica", 11)
    c.drawCentredString(WIDTH / 2, HEIGHT - 355, "Presented by: Vikash & Research Team (Final Year CS/DS)")
    
    c.showPage()
    
    c.save()
    print(f"Successfully generated {PDF_OUTPUT} ({os.path.getsize(PDF_OUTPUT)} bytes, 11 slides)")

if __name__ == "__main__":
    build_pdf()
