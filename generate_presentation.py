"""
Generates the complete 11-slide PowerPoint presentation (.pptx)
for TECHYUVA 11.0 at Buddha Degree College, GIDA, Gorakhpur.
Topic: Dynamic Cointegration-Based Statistical Arbitrage in Cryptocurrency Markets
"""

import sys
from pathlib import Path
import pptx
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE

OUTPUT_FILE = Path("presentation.pptx")

# Color Palette (Dark Theme / Professional Quant Aesthetic)
BG_COLOR = RGBColor(11, 19, 43)        # Deep Navy (#0B132B)
CARD_BG = RGBColor(28, 37, 65)         # Slate Navy (#1C2541)
ACCENT_CYAN = RGBColor(6, 182, 212)    # Neon Cyan (#06B6D4)
ACCENT_EMERALD = RGBColor(16, 185, 129)# Green (#10B981)
ACCENT_ROSE = RGBColor(244, 63, 94)    # Coral Red (#F43F5E)
ACCENT_AMBER = RGBColor(245, 158, 11)  # Amber (#F59E0B)
TEXT_WHITE = RGBColor(241, 245, 249)   # Crisp White (#F1F5F9)
TEXT_MUTED = RGBColor(148, 163, 184)   # Slate Grey (#94A3B8)
BORDER_COLOR = RGBColor(51, 65, 85)    # Border Slate (#334155)

prs = pptx.Presentation()
prs.slide_width = Inches(13.333)
prs.slide_height = Inches(7.5)
blank_layout = prs.slide_layouts[6]

def apply_background(slide):
    """Fills slide with dark navy background."""
    bg_shape = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE, 0, 0, prs.slide_width, prs.slide_height
    )
    bg_shape.fill.solid()
    bg_shape.fill.fore_color.rgb = BG_COLOR
    bg_shape.line.fill.background()
    return bg_shape

def add_header(slide, title_text, category_text="TECHYUVA 11.0 • BUDDHA DEGREE COLLEGE"):
    """Adds standard banner header to slide."""
    header_box = slide.shapes.add_textbox(Inches(0.8), Inches(0.4), Inches(11.7), Inches(1.0))
    tf = header_box.text_frame
    tf.word_wrap = True
    tf.margin_top = tf.margin_bottom = tf.margin_left = tf.margin_right = 0
    
    # Category tag
    p_cat = tf.paragraphs[0]
    p_cat.text = category_text.upper()
    p_cat.font.size = Pt(10)
    p_cat.font.bold = True
    p_cat.font.color.rgb = ACCENT_CYAN
    
    # Title
    p_title = tf.add_paragraph()
    p_title.text = title_text
    p_title.font.size = Pt(24)
    p_title.font.bold = True
    p_title.font.color.rgb = TEXT_WHITE
    p_title.space_before = Pt(3)

def add_footer(slide, slide_num):
    """Adds consistent footer across slides."""
    footer_box = slide.shapes.add_textbox(Inches(0.8), Inches(7.0), Inches(11.7), Inches(0.4))
    tf = footer_box.text_frame
    tf.margin_top = tf.margin_bottom = tf.margin_left = tf.margin_right = 0
    p = tf.paragraphs[0]
    p.text = f"TECHYUVA 11.0  |  Buddha Degree College, GIDA, Gorakhpur  |  Slide {slide_num}"
    p.font.size = Pt(9)
    p.font.color.rgb = TEXT_MUTED

def add_card(slide, left, top, width, height, title=None, border_color=BORDER_COLOR):
    """Draws an elevated card container."""
    shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, left, top, width, height)
    shape.fill.solid()
    shape.fill.fore_color.rgb = CARD_BG
    shape.line.color.rgb = border_color
    shape.line.width = Pt(1.2)
    
    if title:
        tx_box = slide.shapes.add_textbox(left + Inches(0.25), top + Inches(0.2), width - Inches(0.5), Inches(0.4))
        tf = tx_box.text_frame
        tf.word_wrap = True
        tf.margin_top = tf.margin_bottom = tf.margin_left = tf.margin_right = 0
        p = tf.paragraphs[0]
        p.text = title
        p.font.size = Pt(14)
        p.font.bold = True
        p.font.color.rgb = ACCENT_CYAN
    return shape


# ==========================================
# SLIDE 1: TITLE SLIDE
# ==========================================
s1 = prs.slides.add_slide(blank_layout)
apply_background(s1)

# Main Title Card
add_card(s1, Inches(1.0), Inches(1.0), Inches(11.333), Inches(5.5), border_color=ACCENT_CYAN)

tb1 = s1.shapes.add_textbox(Inches(1.5), Inches(1.4), Inches(10.333), Inches(4.7))
tf1 = tb1.text_frame
tf1.word_wrap = True

p_event = tf1.paragraphs[0]
p_event.text = "TECHYUVA 11.0  •  ANNUAL TECH FEST"
p_event.font.size = Pt(13)
p_event.font.bold = True
p_event.font.color.rgb = ACCENT_CYAN

p_inst = tf1.add_paragraph()
p_inst.text = "BUDDHA DEGREE COLLEGE, GIDA, GORAKHPUR"
p_inst.font.size = Pt(14)
p_inst.font.bold = True
p_inst.font.color.rgb = TEXT_MUTED
p_inst.space_before = Pt(4)

p_date = tf1.add_paragraph()
p_date.text = "Date: 3rd to 5th November, 2026"
p_date.font.size = Pt(11)
p_date.font.color.rgb = ACCENT_AMBER
p_date.space_before = Pt(2)

p_main = tf1.add_paragraph()
p_main.text = "Dynamic Cointegration-Based Statistical Arbitrage in Cryptocurrency Markets"
p_main.font.size = Pt(28)
p_main.font.bold = True
p_main.font.color.rgb = TEXT_WHITE
p_main.space_before = Pt(20)

p_sub = tf1.add_paragraph()
p_sub.text = "High-Frequency Algorithmic Pairs Trading with Zero-Lookahead Simulation & Live Paper OMS"
p_sub.font.size = Pt(14)
p_sub.font.color.rgb = ACCENT_EMERALD
p_sub.space_before = Pt(8)

p_author = tf1.add_paragraph()
p_author.text = "Author Name: Vikash & Research Team"
p_author.font.size = Pt(13)
p_author.font.bold = True
p_author.font.color.rgb = TEXT_WHITE
p_author.space_before = Pt(28)

p_branch = tf1.add_paragraph()
p_branch.text = "Course: B.Tech / B.Sc (Computer Science / Data Science)  |  Semester: Final Year"
p_branch.font.size = Pt(12)
p_branch.font.color.rgb = TEXT_MUTED
p_branch.space_before = Pt(4)


# ==========================================
# SLIDE 2: CONTENTS
# ==========================================
s2 = prs.slides.add_slide(blank_layout)
apply_background(s2)
add_header(s2, "Table of Contents")
add_footer(s2, 2)

contents = [
    ("01", "Introduction", "Core concepts of Statistical Arbitrage and pairs trading in crypto markets"),
    ("02", "Case Situation", "24/7 continuous trading universe & 8,640 5-minute candles high-frequency dataset"),
    ("03", "Key Challenge", "Non-stationarity, spurious correlations, multiple testing bias, and transaction fees"),
    ("04", "Company / Quant Strategy", "Engle-Granger testing, FDR Benjamini-Hochberg correction, and Kalman filters"),
    ("05", "Results & Impact", "30-day performance benchmark: +2.90% Net Return, 20.62 Sharpe, 96.1% Win Rate"),
    ("06", "Analysis", "Why Static OLS outperformed Dynamic Kalman Filter under microstructure friction"),
    ("07", "Key Learnings", "Mathematical discipline, execution latency management, and full-stack deployment"),
    ("08", "Conclusion & Live Demo", "Production-grade React terminal, zero-secret paper OMS, and GitHub architecture")
]

for idx, (num, title, desc) in enumerate(contents):
    col = idx % 2
    row = idx // 2
    x = Inches(0.8 + col * 5.9)
    y = Inches(1.6 + row * 1.25)
    
    add_card(s2, x, y, Inches(5.6), Inches(1.1), border_color=BORDER_COLOR)
    tb = s2.shapes.add_textbox(x + Inches(0.2), y + Inches(0.12), Inches(5.2), Inches(0.85))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_top = tf.margin_bottom = tf.margin_left = tf.margin_right = 0
    
    p = tf.paragraphs[0]
    p.text = f"{num}. {title}"
    p.font.size = Pt(13)
    p.font.bold = True
    p.font.color.rgb = ACCENT_CYAN
    
    p2 = tf.add_paragraph()
    p2.text = desc
    p2.font.size = Pt(10)
    p2.font.color.rgb = TEXT_MUTED
    p2.space_before = Pt(3)


# ==========================================
# SLIDE 3: INTRODUCTION
# ==========================================
s3 = prs.slides.add_slide(blank_layout)
apply_background(s3)
add_header(s3, "Introduction: Algorithmic Statistical Arbitrage")
add_footer(s3, 3)

add_card(s3, Inches(0.8), Inches(1.6), Inches(5.6), Inches(5.0), title="What is Statistical Arbitrage?", border_color=ACCENT_CYAN)
tb3a = s3.shapes.add_textbox(Inches(1.05), Inches(2.2), Inches(5.1), Inches(4.2))
tf3a = tb3a.text_frame
tf3a.word_wrap = True
tf3a.margin_top = tf3a.margin_bottom = tf3a.margin_left = tf3a.margin_right = 0

bullets3a = [
    ("Market-Neutral pairs trading", "Simultaneously buying an undervalued asset while shorting an overvalued asset to hedge market beta."),
    ("Cointegration vs. Correlation", "Correlation measures co-movement in returns. Cointegration establishes a true stationary long-term equilibrium: S_t = ln(P_A) - α - β ln(P_B)."),
    ("Mean-Reversion Law", "When the spread diverges beyond ±2.0 standard deviations (Z-score), statistical forces pull it back to equilibrium, generating alpha."),
    ("Zero Directional Risk", "Profits are generated regardless of whether Bitcoin surges or crashes.")
]

for title, text in bullets3a:
    p = tf3a.add_paragraph() if tf3a.paragraphs[0].text else tf3a.paragraphs[0]
    p.text = f"• {title}: "
    p.font.size = Pt(12)
    p.font.bold = True
    p.font.color.rgb = TEXT_WHITE
    p.space_before = Pt(8)
    
    run = p.add_run()
    run.text = text
    run.font.bold = False
    run.font.color.rgb = TEXT_MUTED

add_card(s3, Inches(6.8), Inches(1.6), Inches(5.7), Inches(5.0), title="Project Core Deliverables", border_color=ACCENT_EMERALD)
tb3b = s3.shapes.add_textbox(Inches(7.05), Inches(2.2), Inches(5.2), Inches(4.2))
tf3b = tb3b.text_frame
tf3b.word_wrap = True
tf3b.margin_top = tf3b.margin_bottom = tf3b.margin_left = tf3b.margin_right = 0

bullets3b = [
    ("Automated Screening Engine", "Evaluates all 45 cross-pairs in Binance USDT-M Futures using Engle-Granger two-step tests."),
    ("Multiple Hypothesis Correction", "Applies Benjamini-Hochberg False Discovery Rate (FDR) control at q ≤ 0.05 to eliminate false discoveries."),
    ("Zero-Lookahead Backtester", "Simulates realistic order execution at bar t+1 Open with exchange taker fees (0.05%) and slippage (0.02%)."),
    ("Production Web Terminal", "React 18 frontend + FastAPI backend + local paper trading engine without needing private API secret keys.")
]

for title, text in bullets3b:
    p = tf3b.add_paragraph() if tf3b.paragraphs[0].text else tf3b.paragraphs[0]
    p.text = f"• {title}: "
    p.font.size = Pt(12)
    p.font.bold = True
    p.font.color.rgb = ACCENT_CYAN
    p.space_before = Pt(8)
    
    run = p.add_run()
    run.text = text
    run.font.bold = False
    run.font.color.rgb = TEXT_MUTED


# ==========================================
# SLIDE 4: CASE SITUATION
# ==========================================
s4 = prs.slides.add_slide(blank_layout)
apply_background(s4)
add_header(s4, "Case Situation: Market Environment & Dataset")
add_footer(s4, 4)

# 3 Horizontal Cards
c_width = Inches(3.7)
c_gap = Inches(0.3)

# Card 1: Crypto Market Realities
add_card(s4, Inches(0.8), Inches(1.6), c_width, Inches(5.0), title="Market Microstructure", border_color=ACCENT_ROSE)
tb4a = s4.shapes.add_textbox(Inches(1.0), Inches(2.2), c_width - Inches(0.4), Inches(4.2))
tf4a = tb4a.text_frame
tf4a.word_wrap = True
tf4a.margin_top = tf4a.margin_bottom = tf4a.margin_left = tf4a.margin_right = 0

items4a = [
    "24/7/365 Non-stop trading with no market open/close auctions.",
    "High volatility regimes with leverage liquidation cascades.",
    "Orderbook depth shifts rapidly during high-impact macro news.",
    "Traditional equity statistical arbitrage assumptions fail in crypto due to heavy tails."
]
for item in items4a:
    p = tf4a.add_paragraph() if tf4a.paragraphs[0].text else tf4a.paragraphs[0]
    p.text = f"▶  {item}"
    p.font.size = Pt(11)
    p.font.color.rgb = TEXT_WHITE
    p.space_before = Pt(12)

# Card 2: Experimental Universe
add_card(s4, Inches(0.8 + 1 * (3.7 + 0.3)), Inches(1.6), c_width, Inches(5.0), title="Empirical Universe", border_color=ACCENT_CYAN)
tb4b = s4.shapes.add_textbox(Inches(1.0 + 1 * (3.7 + 0.3)), Inches(2.2), c_width - Inches(0.4), Inches(4.2))
tf4b = tb4b.text_frame
tf4b.word_wrap = True
tf4b.margin_top = tf4b.margin_bottom = tf4b.margin_left = tf4b.margin_right = 0

items4b = [
    "Venue: Binance USDT-M Perpetual Futures (largest global liquidity pool).",
    "Assets (10): BTC, ETH, SOL, BNB, XRP, ADA, LINK, DOGE, AVAX, LTC.",
    "Candle Frequency: 5-minute OHLCV intervals.",
    "Period: 8,640 consecutive synchronized bars (30 full trading days).",
    "Pair Combinations: 10 * 9 / 2 = 45 unique cross-currency pairs."
]
for item in items4b:
    p = tf4b.add_paragraph() if tf4b.paragraphs[0].text else tf4b.paragraphs[0]
    p.text = f"▶  {item}"
    p.font.size = Pt(11)
    p.font.color.rgb = TEXT_WHITE
    p.space_before = Pt(10)

# Card 3: Execution Realism
add_card(s4, Inches(0.8 + 2 * (3.7 + 0.3)), Inches(1.6), c_width, Inches(5.0), title="Execution Constraints", border_color=ACCENT_AMBER)
tb4c = s4.shapes.add_textbox(Inches(1.0 + 2 * (3.7 + 0.3)), Inches(2.2), c_width - Inches(0.4), Inches(4.2))
tf4c = tb4c.text_frame
tf4c.word_wrap = True
tf4c.margin_top = tf4c.margin_bottom = tf4c.margin_left = tf4c.margin_right = 0

items4c = [
    "Portfolio Starting Capital: $10,000 USDT.",
    "Capital Allocation: 10% per pair ($1,000 target gross exposure).",
    "Exchange Taker Fee: 0.05% per leg (0.10% round-trip).",
    "Simulated Execution Slippage: 0.02% adverse fill on entry & exit.",
    "Signal Rule: Calculated at Bar t Close, filled strictly at Bar t+1 Open."
]
for item in items4c:
    p = tf4c.add_paragraph() if tf4c.paragraphs[0].text else tf4c.paragraphs[0]
    p.text = f"▶  {item}"
    p.font.size = Pt(11)
    p.font.color.rgb = TEXT_WHITE
    p.space_before = Pt(10)


# ==========================================
# SLIDE 5: KEY CHALLENGE
# ==========================================
s5 = prs.slides.add_slide(blank_layout)
apply_background(s5)
add_header(s5, "Key Challenge: Pitfalls in High-Frequency Stat-Arb")
add_footer(s5, 5)

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
    x = Inches(0.8 + col * 5.9)
    y = Inches(1.6 + row * 2.5)
    
    add_card(s5, x, y, Inches(5.6), Inches(2.2), border_color=ACCENT_ROSE)
    tb = s5.shapes.add_textbox(x + Inches(0.25), y + Inches(0.18), Inches(5.1), Inches(1.8))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_top = tf.margin_bottom = tf.margin_left = tf.margin_right = 0
    
    p = tf.paragraphs[0]
    p.text = title
    p.font.size = Pt(13)
    p.font.bold = True
    p.font.color.rgb = ACCENT_ROSE
    
    p2 = tf.add_paragraph()
    p2.text = desc
    p2.font.size = Pt(11)
    p2.font.color.rgb = TEXT_WHITE
    p2.space_before = Pt(6)


# ==========================================
# SLIDE 6: COMPANY / QUANT STRATEGY
# ==========================================
s6 = prs.slides.add_slide(blank_layout)
apply_background(s6)
add_header(s6, "Company Strategy: End-to-End Quantitative Pipeline")
add_footer(s6, 6)

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
    x = Inches(0.8 + col * 5.9)
    y = Inches(1.6 + row * 1.65)
    
    add_card(s6, x, y, Inches(5.6), Inches(1.45), border_color=ACCENT_CYAN)
    tb = s6.shapes.add_textbox(x + Inches(0.2), y + Inches(0.12), Inches(5.2), Inches(1.2))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_top = tf.margin_bottom = tf.margin_left = tf.margin_right = 0
    
    p = tf.paragraphs[0]
    p.text = title
    p.font.size = Pt(12)
    p.font.bold = True
    p.font.color.rgb = ACCENT_CYAN
    
    p2 = tf.add_paragraph()
    p2.text = desc
    p2.font.size = Pt(10)
    p2.font.color.rgb = TEXT_WHITE
    p2.space_before = Pt(3)


# ==========================================
# SLIDE 7: RESULTS / IMPACT
# ==========================================
s7 = prs.slides.add_slide(blank_layout)
apply_background(s7)
add_header(s7, "Results & Impact: Empirical Benchmark Performance")
add_footer(s7, 7)

# KPI Highlights Row
kpis = [
    ("Net Return (30d)", "+2.90%", "Annualized: +41.6%", ACCENT_EMERALD),
    ("Sharpe Ratio", "20.62", "Risk-adjusted return", ACCENT_CYAN),
    ("Max Drawdown", "-0.11%", "Ultra-low downside", ACCENT_EMERALD),
    ("Win Rate", "96.05%", "73 Wins / 3 Losses", ACCENT_AMBER)
]

for idx, (label, val, sub, color) in enumerate(kpis):
    x = Inches(0.8 + idx * 2.95)
    add_card(s7, x, Inches(1.5), Inches(2.8), Inches(1.3), border_color=color)
    tb = s7.shapes.add_textbox(x + Inches(0.15), Inches(1.6), Inches(2.5), Inches(1.1))
    tf = tb.text_frame
    tf.margin_top = tf.margin_bottom = tf.margin_left = tf.margin_right = 0
    
    p = tf.paragraphs[0]
    p.text = label.upper()
    p.font.size = Pt(9)
    p.font.bold = True
    p.font.color.rgb = TEXT_MUTED
    
    p2 = tf.add_paragraph()
    p2.text = val
    p2.font.size = Pt(20)
    p2.font.bold = True
    p2.font.color.rgb = color
    
    p3 = tf.add_paragraph()
    p3.text = sub
    p3.font.size = Pt(9)
    p3.font.color.rgb = TEXT_MUTED

# Detailed Benchmark Table
add_card(s7, Inches(0.8), Inches(3.0), Inches(11.733), Inches(3.8), title="Model Benchmark: Static OLS (M1) vs. Dynamic Kalman Filter (M3)")

rows_data = [
    ("Performance Metric", "Model M1: Static OLS", "Model M3: Dynamic Kalman Filter", "Strategy Edge / Significance"),
    ("Total Net Profit / Return", "+$290.22 (+2.90%)", "-$389.38 (-3.89%)", "M1 delivers consistent positive alpha (+6.79% spread)"),
    ("Annualized Sharpe Ratio", "20.62", "-45.91", "Exceptional risk-adjusted return under static cointegration"),
    ("Maximum Peak-to-Trough Drawdown", "-0.11%", "-3.89%", "Zero severe drawdown regimes for Model M1"),
    ("Win Rate (% Profitable Trades)", "96.05% (73 of 76)", "18.45% (62 of 336)", "M1 avoids whipsaw losses by waiting for full ±2.0σ signals"),
    ("Profit Factor (Gross Win / Gross Loss)", "30.66", "0.10", "Asymmetric payoff distribution in favor of static model"),
    ("Average Trade Holding Time", "2.15 hours (25.8 bars)", "0.58 hours (7.0 bars)", "Static model aligns with true Ornstein-Uhlenbeck half-life"),
    ("Total Fees & Slippage Paid", "$108.13", "$461.84", "Kalman over-traded 4.4x more, destroying equity via fee drag")
]

tb_tbl = s7.shapes.add_textbox(Inches(1.0), Inches(3.6), Inches(11.3), Inches(3.0))
tf_tbl = tb_tbl.text_frame
tf_tbl.word_wrap = True
tf_tbl.margin_top = tf_tbl.margin_bottom = tf_tbl.margin_left = tf_tbl.margin_right = 0

for r_idx, row in enumerate(rows_data):
    p = tf_tbl.add_paragraph() if tf_tbl.paragraphs[0].text else tf_tbl.paragraphs[0]
    p.space_before = Pt(4)
    if r_idx == 0:
        p.text = f"{row[0]:<34} | {row[1]:<24} | {row[2]:<30} | {row[3]}"
        p.font.size = Pt(10)
        p.font.bold = True
        p.font.color.rgb = ACCENT_CYAN
    else:
        p.text = f"{row[0]:<34} | {row[1]:<24} | {row[2]:<30} | {row[3]}"
        p.font.size = Pt(9.5)
        p.font.color.rgb = TEXT_WHITE if r_idx % 2 == 1 else TEXT_MUTED


# ==========================================
# SLIDE 8: ANALYSIS
# ==========================================
s8 = prs.slides.add_slide(blank_layout)
apply_background(s8)
add_header(s8, "Quantitative Analysis: The Kalman Overfitting Paradox")
add_footer(s8, 8)

add_card(s8, Inches(0.8), Inches(1.6), Inches(5.6), Inches(5.0), title="Why Static OLS Succeeded (M1)", border_color=ACCENT_EMERALD)
tb8a = s8.shapes.add_textbox(Inches(1.05), Inches(2.2), Inches(5.1), Inches(4.2))
tf8a = tb8a.text_frame
tf8a.word_wrap = True
tf8a.margin_top = tf8a.margin_bottom = tf8a.margin_left = tf8a.margin_right = 0

points8a = [
    ("Stable Mathematical Anchor", "Calibrated parameters (α = 1.4648, β = 1.1678) reflected the structural cointegrating relationship between BTC and ETH across the full 30 days."),
    ("Patience in Entry Execution", "Waited strictly for large ±2.0σ deviations, entering only 76 high-probability round-trips over 8,640 bars."),
    ("Natural Mean-Reversion", "Gave trades sufficient time to revert (average holding duration = 2.15 hours), matching the empirical half-life of 1.19 hours."),
    ("Minimal Fee Overhead", "Kept total transaction costs to just $108.13, preserving over 73% of gross trading profits.")
]
for title, text in points8a:
    p = tf8a.add_paragraph() if tf8a.paragraphs[0].text else tf8a.paragraphs[0]
    p.text = f"✔ {title}: "
    p.font.size = Pt(11)
    p.font.bold = True
    p.font.color.rgb = ACCENT_EMERALD
    p.space_before = Pt(8)
    run = p.add_run()
    run.text = text
    run.font.bold = False
    run.font.color.rgb = TEXT_WHITE

add_card(s8, Inches(6.8), Inches(1.6), Inches(5.7), Inches(5.0), title="Why Dynamic Kalman Failed (M3)", border_color=ACCENT_ROSE)
tb8b = s8.shapes.add_textbox(Inches(7.05), Inches(2.2), Inches(5.2), Inches(4.2))
tf8b = tb8b.text_frame
tf8b.word_wrap = True
tf8b.margin_top = tf8b.margin_bottom = tf8b.margin_left = tf8b.margin_right = 0

points8b = [
    ("Over-Adapting to Micro-Noise", "At 5-minute frequency, the Kalman filter continuously shifted β in response to temporary orderbook imbalances rather than true economic regime shifts."),
    ("The Moving Goalpost Trap", "As the spread expanded, the Kalman filter adjusted β to absorb the divergence, prematurely moving the equilibrium and closing trades at false inflection points."),
    ("Severe Turnover Explosion", "Executed 336 round-trip trades (4.4x more than static), creating continuous churning and whipsaws."),
    ("Catastrophic Fee Drag", "Accumulated $461.84 in taker fees and slippage, wiping out capital and yielding a -45.91 Sharpe ratio.")
]
for title, text in points8b:
    p = tf8b.add_paragraph() if tf8b.paragraphs[0].text else tf8b.paragraphs[0]
    p.text = f"✘ {title}: "
    p.font.size = Pt(11)
    p.font.bold = True
    p.font.color.rgb = ACCENT_ROSE
    p.space_before = Pt(8)
    run = p.add_run()
    run.text = text
    run.font.bold = False
    run.font.color.rgb = TEXT_WHITE


# ==========================================
# SLIDE 9: KEY LEARNINGS
# ==========================================
s9 = prs.slides.add_slide(blank_layout)
apply_background(s9)
add_header(s9, "Key Learnings & Quant Insights")
add_footer(s9, 9)

learnings = [
    ("1. Complexity Does Not Equal Alpha",
     "Sophisticated time-varying algorithms (like Kalman Filters) often underperform simpler static regressions in noisy high-frequency regimes due to parameter variance and fee multiplication."),
    ("2. Execution Friction Dominates Strategy PnL",
     "Theoretical paper returns without modeled taker fees (0.05%) and slippage (0.02%) are completely misleading. Real-world statistical arbitrage is an optimization against transaction costs."),
    ("3. Statistical Hygiene Prevents Overfitting",
     "Controlling the False Discovery Rate (FDR) via Benjamini-Hochberg is indispensable when mining hundreds of asset combinations to avoid trading random statistical artifacts."),
    ("4. Full-Stack Systems Engineering",
     "Building a real quant system requires uniting mathematical modeling (NumPy/Pandas/Statsmodels), backtesting integrity, async API backends (FastAPI), and responsive monitoring (React 18).")
]

for idx, (title, desc) in enumerate(learnings):
    y = Inches(1.5 + idx * 1.35)
    add_card(s9, Inches(0.8), y, Inches(11.733), Inches(1.2), border_color=ACCENT_CYAN)
    tb = s9.shapes.add_textbox(Inches(1.05), y + Inches(0.12), Inches(11.2), Inches(0.95))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_top = tf.margin_bottom = tf.margin_left = tf.margin_right = 0
    
    p = tf.paragraphs[0]
    p.text = title
    p.font.size = Pt(13)
    p.font.bold = True
    p.font.color.rgb = ACCENT_CYAN
    
    p2 = tf.add_paragraph()
    p2.text = desc
    p2.font.size = Pt(10.5)
    p2.font.color.rgb = TEXT_WHITE
    p2.space_before = Pt(3)


# ==========================================
# SLIDE 10: CONCLUSION
# ==========================================
s10 = prs.slides.add_slide(blank_layout)
apply_background(s10)
add_header(s10, "Conclusion: Summary of Achievements")
add_footer(s10, 10)

add_card(s10, Inches(0.8), Inches(1.6), Inches(11.733), Inches(5.0), border_color=ACCENT_EMERALD)
tb10 = s10.shapes.add_textbox(Inches(1.1), Inches(1.9), Inches(11.1), Inches(4.4))
tf10 = tb10.text_frame
tf10.word_wrap = True
tf10.margin_top = tf10.margin_bottom = tf10.margin_left = tf10.margin_right = 0

concl_points = [
    ("Research-Grade Quantitative Rigor", "Engineered a robust pairs trading framework grounded in Engle-Granger cointegration, Augmented Dickey-Fuller tests, and Benjamini-Hochberg FDR control."),
    ("Proven Empirical Edge", "Achieved +2.90% net 30-day return (41.6% annualized) with an exceptional 20.62 Sharpe ratio and 96.05% win rate on BTC/ETH futures, including realistic trading costs."),
    ("Solved Zero-Lookahead Bias", "All signals evaluated strictly at candle close and filled at next-bar open, preventing lookahead leakage present in naive backtesters."),
    ("Production-Ready Full-Stack Software", "Created a standalone simulated Order Management System (OMS) that paper-trades live public orderbooks with zero API secret keys required."),
    ("Open Source & Cloud Deployed", "Full code repository, test suites, React terminal, and documentation publicly accessible on GitHub and GitHub Pages.")
]

for title, text in concl_points:
    p = tf10.add_paragraph() if tf10.paragraphs[0].text else tf10.paragraphs[0]
    p.text = f"✔  {title}: "
    p.font.size = Pt(12)
    p.font.bold = True
    p.font.color.rgb = ACCENT_EMERALD
    p.space_before = Pt(10)
    run = p.add_run()
    run.text = text
    run.font.bold = False
    run.font.color.rgb = TEXT_WHITE


# ==========================================
# SLIDE 11: THANK YOU / Q&A
# ==========================================
s11 = prs.slides.add_slide(blank_layout)
apply_background(s11)

add_card(s11, Inches(1.5), Inches(1.2), Inches(10.333), Inches(5.1), border_color=ACCENT_CYAN)
tb11 = s11.shapes.add_textbox(Inches(1.8), Inches(1.6), Inches(9.7), Inches(4.3))
tf11 = tb11.text_frame
tf11.word_wrap = True

p_ty = tf11.paragraphs[0]
p_ty.text = "THANK YOU!"
p_ty.font.size = Pt(36)
p_ty.font.bold = True
p_ty.font.color.rgb = ACCENT_CYAN
p_ty.alignment = PP_ALIGN.CENTER

p_qa = tf11.add_paragraph()
p_qa.text = "Questions & Answers (Q/A)"
p_qa.font.size = Pt(18)
p_qa.font.bold = True
p_qa.font.color.rgb = TEXT_WHITE
p_qa.alignment = PP_ALIGN.CENTER
p_qa.space_before = Pt(6)

p_event2 = tf11.add_paragraph()
p_event2.text = "TECHYUVA 11.0  |  BUDDHA DEGREE COLLEGE, GIDA, GORAKHPUR"
p_event2.font.size = Pt(12)
p_event2.font.bold = True
p_event2.font.color.rgb = ACCENT_AMBER
p_event2.alignment = PP_ALIGN.CENTER
p_event2.space_before = Pt(16)

p_repo = tf11.add_paragraph()
p_repo.text = "GitHub Repository: https://github.com/vikash21pa-wq/Dynamic_Cointegration-Based_Statistical-_arbitrage"
p_repo.font.size = Pt(11)
p_repo.font.color.rgb = TEXT_MUTED
p_repo.alignment = PP_ALIGN.CENTER
p_repo.space_before = Pt(20)

p_dash = tf11.add_paragraph()
p_dash.text = "Live Web Terminal: https://vikash21pa-wq.github.io/Dynamic_Cointegration-Based_Statistical-_arbitrage/"
p_dash.font.size = Pt(11)
p_dash.font.color.rgb = ACCENT_EMERALD
p_dash.alignment = PP_ALIGN.CENTER
p_dash.space_before = Pt(6)

prs.save(OUTPUT_FILE)
print(f"Successfully generated {OUTPUT_FILE} with {len(prs.slides)} widescreen slides.")
