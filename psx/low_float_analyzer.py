"""
psx/low_float_analyzer.py
=========================
Specialized Engine for PSX Low Free-Float & Low-Volume Stocks ("Cornered" & Syndicate Scrips)
Based on Institutional PSX Research:
- Float Turnover % (Volume / Free Float Shares)
- Syndicate Accumulation & Cornering Detection
- Seasonal Timing Windows (Sugar crushing, Modaraba year-end, Textile cotton cycles)
- Pre-Open 9:15 AM Momentum vs Distribution Traps
"""

from __future__ import annotations
import datetime
from typing import Dict, List, Any, Optional
import pandas as pd
import numpy as np

from concurrent.futures import ThreadPoolExecutor, as_completed
import time
from .data import fetch_history as fetch_scs_history
import logging

logger = logging.getLogger(__name__)

# In-memory cache for screener results (60 seconds)
_CACHE = {"data": None, "timestamp": 0}
CACHE_TTL = 45 # seconds

# Master Universe of Low Free-Float Scrips from PSX Institutional Low-Float Directory
LOW_FLOAT_UNIVERSE = [
    # --- Category 1: Free Float <= 10% AND Float Shares < 10M (Prime Cornered Targets) ---
    {
        "symbol": "AATM",
        "name": "Al-Azhar Textile Mills",
        "sector": "Textile Spinning",
        "category": "Cat-1 (Float <= 10% & <10M)",
        "issued_shares": 44520000,
        "float_pct": 2.08,
        "float_shares": 926016,
        "char": "Ultra-low float; aggressive runs on sudden volume.",
        "season_months": [10, 11, 12, 1], # Oct-Jan Cotton harvest / winter cycle
        "season_desc": "Cotton arrivals & seasonal textile yarn cycles (Oct-Jan)"
    },
    {
        "symbol": "FIL",
        "name": "First Institutional Leather",
        "sector": "Leather & Tanneries",
        "category": "Cat-1 (Float <= 10% & <10M)",
        "issued_shares": 2000000,
        "float_pct": 2.63,
        "float_shares": 52600,
        "char": "Microscopic float (sirf 52k shares); moves with single operator.",
        "season_months": [9, 10, 11, 12],
        "season_desc": "Post-Eid leather processing & winter export cycle"
    },
    {
        "symbol": "BHAT",
        "name": "Bhanero Textile Mills",
        "sector": "Textile Spinning",
        "category": "Cat-1 (Float <= 10% & <10M)",
        "issued_shares": 3040964,
        "float_pct": 5.00,
        "float_shares": 152048,
        "char": "Blue-chip textile; tightly held by sponsor family.",
        "season_months": [10, 11, 12, 1],
        "season_desc": "Yarn demand cycles & dividend announcements"
    },
    {
        "symbol": "BAFS",
        "name": "Baba Farid Sugar Mills",
        "sector": "Sugar & Allied",
        "category": "Cat-1 (Float <= 10% & <10M)",
        "issued_shares": 9450000,
        "float_pct": 5.00,
        "float_shares": 472500,
        "char": "Seasonal sugar play; highly sensitive to supply cornering.",
        "season_months": [11, 12, 1, 2, 3],
        "season_desc": "Crushing season (Nov-Mar) & sugarcane yield announcements"
    },
    {
        "symbol": "KPUS",
        "name": "Khairpur Sugar Mills",
        "sector": "Sugar & Allied",
        "category": "Cat-1 (Float <= 10% & <10M)",
        "issued_shares": 16017500,
        "float_pct": 5.00,
        "float_shares": 800875,
        "char": "Low float; high price volatility during crushing seasons.",
        "season_months": [11, 12, 1, 2, 3],
        "season_desc": "Crushing season (Nov-Mar) & ethanol export rates"
    },
    {
        "symbol": "PIM",
        "name": "Popular Islamic Modaraba",
        "sector": "Modarabas",
        "category": "Cat-1 (Float <= 10% & <10M)",
        "issued_shares": 20000000,
        "float_pct": 5.00,
        "float_shares": 1000000,
        "char": "Modaraba sector favorite for swift, low-capital pumps.",
        "season_months": [9, 10, 11, 12],
        "season_desc": "Post-closing dividend distributions & year-end rotation"
    },
    {
        "symbol": "NATM",
        "name": "Nadeem Textile Mills",
        "sector": "Textile Spinning",
        "category": "Cat-1 (Float <= 10% & <10M)",
        "issued_shares": 21266740,
        "float_pct": 5.00,
        "float_shares": 1063337,
        "char": "Infrequent volume; sharp spikes when activated.",
        "season_months": [10, 11, 12, 1],
        "season_desc": "Winter textile rotation & cotton pricing adjustments"
    },
    {
        "symbol": "DWTM",
        "name": "Dewan Textile Mills",
        "sector": "Textile Spinning",
        "category": "Cat-1 (Float <= 10% & <10M)",
        "issued_shares": 46064609,
        "float_pct": 5.00,
        "float_shares": 2303230,
        "char": "Dewan group legacy penny stock; sudden momentum rallies.",
        "season_months": [10, 11, 12, 1, 2],
        "season_desc": "Speculative debt-settlement & cyclical penny runs"
    },
    {
        "symbol": "RUBY",
        "name": "Ruby Textile Mills",
        "sector": "Textile Spinning",
        "category": "Cat-1 (Float <= 10% & <10M)",
        "issued_shares": 52214400,
        "float_pct": 5.00,
        "float_shares": 2610720,
        "char": "Periodic operator speculative runs from deep discounted base.",
        "season_months": [10, 11, 12, 1],
        "season_desc": "Textile export subsidies & speculative syndicate rotation"
    },
    {
        "symbol": "JKSM",
        "name": "J.K. Spinning Mills",
        "sector": "Textile Spinning",
        "category": "Cat-1 (Float <= 10% & <10M)",
        "issued_shares": 102317502,
        "float_pct": 5.00,
        "float_shares": 5115875,
        "char": "Steady fundamentals with limited public float.",
        "season_months": [10, 11, 12, 1],
        "season_desc": "Cotton procurement season & export yarn bookings"
    },
    {
        "symbol": "TSML",
        "name": "Tandlianwala Sugar Mills",
        "sector": "Sugar & Allied",
        "category": "Cat-1 (Float <= 10% & <10M)",
        "issued_shares": 117706300,
        "float_pct": 5.00,
        "float_shares": 5885315,
        "char": "Large sugar producer heavily locked by sponsors.",
        "season_months": [11, 12, 1, 2, 3],
        "season_desc": "Cane crushing season (Nov-Mar) & quarterly earnings"
    },
    {
        "symbol": "FTMM",
        "name": "First Treet Mfg Modaraba",
        "sector": "Modarabas",
        "category": "Cat-1 (Float <= 10% & <10M)",
        "issued_shares": 195599994,
        "float_pct": 5.00,
        "float_shares": 9780000,
        "char": "Treet group backing; range-bound retail and syndicate favorite.",
        "season_months": [9, 10, 11, 12],
        "season_desc": "Battery unit restructuring & year-end volume runs"
    },
    {
        "symbol": "AGTL",
        "name": "Al-Ghazi Tractors Limited",
        "sector": "Automobile Assembler",
        "category": "Cat-1 (Float <= 10% & <10M)",
        "issued_shares": 57964201,
        "float_pct": 6.34,
        "float_shares": 3674300,
        "char": "Fundamental tractor manufacturer with very tight float.",
        "season_months": [1, 2, 3, 10, 11],
        "season_desc": "Kharif/Rabi harvest tractor buying & agricultural package"
    },
    {
        "symbol": "UPFL",
        "name": "Unilever Pakistan Foods",
        "sector": "Food & Personal Care",
        "category": "Cat-1 (Float <= 10% & <10M)",
        "issued_shares": 6371822,
        "float_pct": 8.18,
        "float_shares": 521215,
        "char": "High-priced MNC (>PKR 25,000); low float dividend aristocrat.",
        "season_months": [2, 3, 8, 9],
        "season_desc": "Annual and half-yearly bumper dividend payouts"
    },
    {
        "symbol": "RCML",
        "name": "Reliance Cotton Spinning",
        "sector": "Textile Spinning",
        "category": "Cat-1 (Float <= 10% & <10M)",
        "issued_shares": 10652000,
        "float_pct": 10.00,
        "float_shares": 1065200,
        "char": "Consistent payout history; small tradable float.",
        "season_months": [10, 11, 12, 1],
        "season_desc": "Cotton season & dividend distribution periods"
    },
    {
        "symbol": "AABS",
        "name": "Al-Abbas Sugar Mills",
        "sector": "Sugar & Allied",
        "category": "Cat-1 (Float <= 10% & <10M)",
        "issued_shares": 17362300,
        "float_pct": 10.00,
        "float_shares": 1736230,
        "char": "High-dividend sugar scrip; low floating float.",
        "season_months": [11, 12, 1, 2, 3],
        "season_desc": "Crushing season (Nov-Mar) & high cash dividend announcements"
    },
    {
        "symbol": "SHCM",
        "name": "Shadman Cotton Mills",
        "sector": "Textile Spinning",
        "category": "Cat-1 (Float <= 10% & <10M)",
        "issued_shares": 17636720,
        "float_pct": 10.00,
        "float_shares": 1763672,
        "char": "Low-priced spinning unit; sharp cyclical rallies.",
        "season_months": [10, 11, 12, 1],
        "season_desc": "Textile penny rotations & winter energy tariff adjustments"
    },
    {
        "symbol": "SZTM",
        "name": "Shahzad Textile Mills",
        "sector": "Textile Spinning",
        "category": "Cat-1 (Float <= 10% & <10M)",
        "issued_shares": 17971370,
        "float_pct": 10.00,
        "float_shares": 1797137,
        "char": "Thin order book; fast response to volume bursts.",
        "season_months": [10, 11, 12, 1],
        "season_desc": "Spinning sector speculative wave & cotton inventory runs"
    },
    {
        "symbol": "IDRT",
        "name": "Idrees Textile Mills",
        "sector": "Textile Spinning",
        "category": "Cat-1 (Float <= 10% & <10M)",
        "issued_shares": 19852800,
        "float_pct": 10.00,
        "float_shares": 1985280,
        "char": "Consistent low liquidity; fast percentage gains on volume.",
        "season_months": [10, 11, 12, 1],
        "season_desc": "Cyclical speculative wave in dormant spinning scrips"
    },
    {
        "symbol": "PINLR",
        "name": "Premier Insurance Limited",
        "sector": "Insurance",
        "category": "Cat-1 (Float <= 10% & <10M)",
        "issued_shares": 20226042,
        "float_pct": 10.00,
        "float_shares": 2022604,
        "char": "Small insurance scrip; susceptible to sudden syndicate interest.",
        "season_months": [4, 5, 11, 12],
        "season_desc": "Insurance sector quarterly runs & regulatory capital reviews"
    },
    {
        "symbol": "SAPT",
        "name": "Sapphire Textile Mills",
        "sector": "Textile Composite",
        "category": "Cat-1 (Float <= 10% & <10M)",
        "issued_shares": 21689790,
        "float_pct": 10.00,
        "float_shares": 2168979,
        "char": "Sapphire flagship; high-priced, heavily sponsor-held.",
        "season_months": [10, 11, 12, 1, 2],
        "season_desc": "Export power subsidies & high-grade spinning rotations"
    },
    {
        "symbol": "FZCM",
        "name": "Fazal Cloth Mills",
        "sector": "Textile Composite",
        "category": "Cat-1 (Float <= 10% & <10M)",
        "issued_shares": 30000000,
        "float_pct": 10.00,
        "float_shares": 3000000,
        "char": "Export giant; tight market availability.",
        "season_months": [10, 11, 12, 1, 2],
        "season_desc": "Winter export surge & currency depreciation moves"
    },
    {
        "symbol": "GLPL",
        "name": "Gillette Pakistan Limited",
        "sector": "Food & Personal Care",
        "category": "Cat-1 (Float <= 10% & <10M)",
        "issued_shares": 31872000,
        "float_pct": 10.00,
        "float_shares": 3187200,
        "char": "MNC brand; low float resulting in wide price gaps.",
        "season_months": [6, 7, 11, 12],
        "season_desc": "Consumer FMCG volume jumps & pricing revisions"
    },
    {
        "symbol": "SINDM",
        "name": "Sindh Modaraba",
        "sector": "Modarabas",
        "category": "Cat-1 (Float <= 10% & <10M)",
        "issued_shares": 45000000,
        "float_pct": 10.00,
        "float_shares": 4500000,
        "char": "Provincial entity; low market turnover, sudden locked rallies.",
        "season_months": [9, 10, 11, 12],
        "season_desc": "Dividend announcement periods & Modaraba sector momentum"
    },
    {
        "symbol": "FTSM",
        "name": "First Tri-Star Modaraba",
        "sector": "Modarabas",
        "category": "Cat-1 (Float <= 10% & <10M)",
        "issued_shares": 21000000,
        "float_pct": 5.00,
        "float_shares": 1050000,
        "char": "High-beta Modaraba penny stock; swift volume accumulation pumps.",
        "season_months": [9, 10, 11],
        "season_desc": "Annual balance sheet closing & dividend payout speculation"
    },
    {
        "symbol": "KOSM",
        "name": "Kohinoor Modaraba",
        "sector": "Modarabas",
        "category": "Cat-1 (Float <= 10% & <10M)",
        "issued_shares": 20400000,
        "float_pct": 10.00,
        "float_shares": 2040000,
        "char": "Kohinoor group modaraba; strong November-December seasonality.",
        "season_months": [10, 11, 12],
        "season_desc": "Modaraba annual profit payout window (90% distribution rule)"
    },
    {
        "symbol": "ARM",
        "name": "Al-Noor Modaraba",
        "sector": "Modarabas",
        "category": "Cat-1 (Float <= 10% & <10M)",
        "issued_shares": 21000000,
        "float_pct": 12.00,
        "float_shares": 2520000,
        "char": "Al-Noor group entity; low turnover, cornered by syndicates.",
        "season_months": [9, 10, 11],
        "season_desc": "Modaraba year-end distribution & Islamic financing cycles"
    },
    {
        "symbol": "FHAM",
        "name": "First Habib Modaraba",
        "sector": "Modarabas",
        "category": "Cat-1 (Float <= 10% & <10M)",
        "issued_shares": 100800000,
        "float_pct": 9.50,
        "float_shares": 9576000,
        "char": "Flagship blue-chip modaraba; consistent dividend payer.",
        "season_months": [9, 10, 11],
        "season_desc": "Annual dividend payout cycle & consistent book-value backing"
    },
    {
        "symbol": "BFMOD",
        "name": "B.F. Modaraba",
        "sector": "Modarabas",
        "category": "Cat-1 (Float <= 10% & <10M)",
        "issued_shares": 7515000,
        "float_pct": 8.00,
        "float_shares": 601200,
        "char": "Tight float; sharp price runs on low volume.",
        "season_months": [9, 10, 11, 12],
        "season_desc": "Speculative float cornering & dividend payout season"
    },
    {
        "symbol": "ADMM",
        "name": "Artistic Denim Mills",
        "sector": "Textile Composite",
        "category": "Cat-1 (Float <= 10% & <10M)",
        "issued_shares": 84000000,
        "float_pct": 10.00,
        "float_shares": 8400000,
        "char": "Clean balance sheet with low float; steady accumulation waves.",
        "season_months": [10, 11, 12, 1],
        "season_desc": "Denim garment exports & global fashion ordering seasons"
    },
    {
        "symbol": "IMSL",
        "name": "Imperial Sugar Limited",
        "sector": "Sugar & Allied",
        "category": "Cat-1 (Float <= 10% & <10M)",
        "issued_shares": 99020000,
        "float_pct": 10.00,
        "float_shares": 9902000,
        "char": "Active sugar turnaround candidate; speculative leader.",
        "season_months": [11, 12, 1, 2, 3],
        "season_desc": "Crushing season (Nov-Mar) & sugar export quota approvals"
    },

    # --- Category 2: Low Total Floating Shares (< 10M Shares) with Higher Float % (> 10%) ---
    {
        "symbol": "BUXL",
        "name": "Buxly Paints Limited",
        "sector": "Chemicals",
        "category": "Cat-2 (Float Shares < 10M)",
        "issued_shares": 1440000,
        "float_pct": 40.00,
        "float_shares": 576000,
        "char": "Micro-cap; rapid circuit moves on tiny volumes (5.7 Lakh shares).",
        "season_months": [3, 4, 10, 11],
        "season_desc": "Construction/repainting seasons (pre-summer & post-monsoon)"
    },
    {
        "symbol": "FIMM",
        "name": "First Imrooz Modaraba",
        "sector": "Modarabas",
        "category": "Cat-2 (Float Shares < 10M)",
        "issued_shares": 3000000,
        "float_pct": 30.00,
        "float_shares": 900000,
        "char": "Very low capital base (sirf 9 Lakh float); tightly controlled.",
        "season_months": [9, 10, 11, 12],
        "season_desc": "Financial year-end payout cycles & swift price locks"
    },
    {
        "symbol": "AKDHL",
        "name": "AKD Hospitality Limited",
        "sector": "Miscellaneous",
        "category": "Cat-2 (Float Shares < 10M)",
        "issued_shares": 2507273,
        "float_pct": 40.00,
        "float_shares": 1002909,
        "char": "AKD group hospitality scrip; easily cornered by group syndicates.",
        "season_months": [11, 12, 1, 6, 7],
        "season_desc": "Winter tourism / hospitality booking cycles"
    },
    {
        "symbol": "PAKL",
        "name": "Pak Leather Crafts",
        "sector": "Leather & Tanneries",
        "category": "Cat-2 (Float Shares < 10M)",
        "issued_shares": 3400000,
        "float_pct": 30.00,
        "float_shares": 1020000,
        "char": "Penny range; active during export policy announcements.",
        "season_months": [9, 10, 11, 12],
        "season_desc": "Winter leather garment export shipment window"
    },
    {
        "symbol": "AHTM",
        "name": "Ahmad Hassan Textile Mills",
        "sector": "Textile Composite",
        "category": "Cat-2 (Float Shares < 10M)",
        "issued_shares": 8471535,
        "float_pct": 15.00,
        "float_shares": 1270730,
        "char": "Small float; sharp reactions to exchange rate movements.",
        "season_months": [10, 11, 12, 1],
        "season_desc": "Textile spinning & composite winter yarn runs"
    },
    {
        "symbol": "ANTM",
        "name": "AN Textile Mills",
        "sector": "Textile Spinning",
        "category": "Cat-2 (Float Shares < 10M)",
        "issued_shares": 9660000,
        "float_pct": 15.00,
        "float_shares": 1449000,
        "char": "High retail speculation when volume emerges (14.5 Lakh shares).",
        "season_months": [10, 11, 12, 1],
        "season_desc": "Cotton season price discovery & spinning rallies"
    },
    {
        "symbol": "IDSM",
        "name": "Ideal Spinning Mills",
        "sector": "Textile Spinning",
        "category": "Cat-2 (Float Shares < 10M)",
        "issued_shares": 9920000,
        "float_pct": 15.00,
        "float_shares": 1488000,
        "char": "Low float base; sharp upward extensions.",
        "season_months": [10, 11, 12, 1],
        "season_desc": "Spinning sector liquidity rotations & local yarn demand"
    },
    {
        "symbol": "BATA",
        "name": "Bata Pakistan Limited",
        "sector": "Leather & Tanneries",
        "category": "Cat-2 (Float Shares < 10M)",
        "issued_shares": 7560000,
        "float_pct": 23.68,
        "float_shares": 1789870,
        "char": "High share price (~Rs. 800+); institutional and high-net-worth play.",
        "season_months": [3, 4, 8, 9, 12],
        "season_desc": "Eid shopping seasons & school opening demand peaks"
    },
    {
        "symbol": "JATM",
        "name": "J.A. Textile Mills",
        "sector": "Textile Spinning",
        "category": "Cat-2 (Float Shares < 10M)",
        "issued_shares": 12601160,
        "float_pct": 15.00,
        "float_shares": 1890174,
        "char": "Frequently active in speculative penny rotations.",
        "season_months": [10, 11, 12, 1],
        "season_desc": "Penny stock rotations & speculative textile volume surges"
    },
    {
        "symbol": "PRET",
        "name": "Premium Textile Mills",
        "sector": "Textile Spinning",
        "category": "Cat-2 (Float Shares < 10M)",
        "issued_shares": 6163000,
        "float_pct": 35.00,
        "float_shares": 2157050,
        "char": "High price per share (~Rs. 600); very low daily float volume.",
        "season_months": [10, 11, 12, 1],
        "season_desc": "High-count combed yarn exports & cash payouts"
    },
    {
        "symbol": "STML",
        "name": "Shams Textile Mills",
        "sector": "Textile Composite",
        "category": "Cat-2 (Float Shares < 10M)",
        "issued_shares": 8640000,
        "float_pct": 30.00,
        "float_shares": 2592000,
        "char": "Classic textile player with under 2.6M shares float.",
        "season_months": [10, 11, 12, 1],
        "season_desc": "Fabric exports & winter spinning margins"
    },
    {
        "symbol": "LEUL",
        "name": "Leather Up Limited",
        "sector": "Leather & Tanneries",
        "category": "Cat-2 (Float Shares < 10M)",
        "issued_shares": 6000000,
        "float_pct": 45.00,
        "float_shares": 2700000,
        "char": "Frequent target of PSX price/volume surge inquiries; rapid locks.",
        "season_months": [9, 10, 11, 12],
        "season_desc": "Leather jacket export season & periodic operator cornering"
    },
    {
        "symbol": "DIIL",
        "name": "Diamond Industries",
        "sector": "Chemicals",
        "category": "Cat-2 (Float Shares < 10M)",
        "issued_shares": 9000000,
        "float_pct": 35.00,
        "float_shares": 3150000,
        "char": "Low base; quick price swings on low volume.",
        "season_months": [1, 2, 7, 8, 11],
        "season_desc": "Foam & chemical demand cycles & speculative spikes"
    },
    {
        "symbol": "ADAMS",
        "name": "Adam Sugar Mills",
        "sector": "Sugar & Allied",
        "category": "Cat-2 (Float Shares < 10M)",
        "issued_shares": 17291008,
        "float_pct": 20.00,
        "float_shares": 3458192,
        "char": "Small sugar scrip; swift seasonal price movement.",
        "season_months": [11, 12, 1, 2, 3],
        "season_desc": "Crushing season (Nov-Mar) & sugar recovery rate spikes"
    }
]


def _analyze_single_scrip(item: Dict[str, Any], current_month: int) -> Optional[Dict[str, Any]]:
    sym = item["symbol"]
    float_shares = item["float_shares"]
    
    # Check seasonal window
    in_season = current_month in item.get("season_months", [])
    if in_season:
        season_badge = f"🔥 IN ACTIVE SEASON"
    else:
        season_badge = f"⏳ OFF-SEASON"

    # Fetch SCSTrade historical candles
    df = fetch_scs_history(sym, resolution="D", days=45)
    
    if df is None or len(df) == 0:
        return {
            **item,
            "price": 0.0,
            "change_pct": 0.0,
            "volume": 0,
            "avg_vol_20d": 0,
            "float_turnover_pct": 0.0,
            "vol_surge_x": 0.0,
            "syndicate_phase": "DORMANT (Awaiting Data)",
            "phase_code": "DORMANT",
            "in_season": in_season,
            "season_badge": season_badge,
            "actionable_insight": "Market feed historical data abhi fetch nahi hua."
        }

    try:
        # Standardize column names to lowercase
        df.columns = [str(c).lower() for c in df.columns]
        
        latest = df.iloc[-1]
        prev = df.iloc[-2] if len(df) > 1 else latest
        
        price = float(latest["close"])
        prev_close = float(prev["close"])
        change_pct = round(((price - prev_close) / prev_close) * 100, 2) if prev_close > 0 else 0.0
        
        vol = float(latest.get("volume", 0))
        
        # 20-day average volume
        avg_vol = float(df["volume"].tail(20).mean()) if len(df) >= 5 else vol
        vol_surge_x = round(vol / max(avg_vol, 500.0), 1)

        # Float turnover %: (today_volume / float_shares) * 100
        float_turnover = round((vol / max(float_shares, 1)) * 100, 2)

        # High/Low/Open for wick analysis
        high = float(latest.get("high", price))
        low = float(latest.get("low", price))
        candle_range = max(high - low, 0.001)
        upper_wick = high - max(price, float(latest.get("open", price)))
        upper_wick_ratio = upper_wick / candle_range

        # Determine Syndicate / Game Phase (Scaled for Micro & Low Float Realities - 10% / Rs. 1.00 Circuit Rule)
        min_lock_gain = max(price * 0.095, 0.95) # 10% or Rs. 1.00 circuit limit
        price_gain = price - float(latest.get("open", price))
        if change_pct >= 9.5 or (price <= 12.0 and price_gain >= 0.95):
            phase = "🚀 UPPER CIRCUIT LOCK"
            phase_code = "UPPER_LOCK"
            insight = "Supply cornered; locked at 10% upper circuit. Continuous session mein retail entry mushkil hoti hai, pre-open 9:15 AM limit order se follow hota hai."
        
        elif float_turnover >= 8.0 or (vol_surge_x >= 2.5 and float_turnover >= 1.8):
            if upper_wick_ratio >= 0.45 and change_pct < 2.0:
                phase = "⚠️ DISTRIBUTION TRAP"
                phase_code = "DISTRIBUTION"
                insight = "Heavy turnover bana magar upper lock hold nahi hua (upper wick rejection). Syndicate public par dump kar rahi hai, foran exit karein!"
            else:
                phase = "⚡ VOLUME BREAKOUT (Game On)"
                phase_code = "BREAKOUT"
                insight = f"Daily turnover tradable float ka {float_turnover}% absorb kar gaya! Syndicate buying wave actively ignite ho chuki hai."

        elif (float_turnover >= 1.8 or vol_surge_x >= 1.4) and (-1.5 <= change_pct <= 5.5):
            phase = "🟢 ACTIVE ACCUMULATION (Game Forming)"
            phase_code = "ACCUMULATION"
            insight = f"Silent absorption base! Volume float ka {float_turnover}% absorb ho chuka hai bina baray price jump ke. Chupke se float corner ho raha hai."

        elif float_turnover < 0.5 and vol_surge_x < 1.2:
            phase = "😴 DORMANT BASE"
            phase_code = "DORMANT"
            insight = f"Volume abhi dry hai ({int(vol):,} shares · {float_turnover}% of float). Float absorption trigger hone tak capital freeze na karein."
        
        else:
            phase = "⚖️ RANGE CONSOLIDATION"
            phase_code = "RANGE"
            insight = "Normal secondary trading; volume ignition catalyst ka intezar."

        if in_season:
            insight += f" | Season: {item['season_desc']}"

        return {
            **item,
            "price": price,
            "change_pct": change_pct,
            "volume": int(vol),
            "avg_vol_20d": int(avg_vol),
            "float_turnover_pct": float_turnover,
            "vol_surge_x": vol_surge_x,
            "syndicate_phase": phase,
            "phase_code": phase_code,
            "in_season": in_season,
            "season_badge": season_badge,
            "actionable_insight": insight
        }
    except Exception as e:
        logger.error(f"Error evaluating {sym}: {e}")
        return None


def analyze_low_float_stocks(force_refresh: bool = False) -> Dict[str, Any]:
    global _CACHE
    now = time.time()
    if not force_refresh and _CACHE["data"] and (now - _CACHE["timestamp"]) < CACHE_TTL:
        return _CACHE["data"]

    current_month = datetime.datetime.now().month
    month_name = datetime.datetime.now().strftime("%B")

    results = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(_analyze_single_scrip, item, current_month): item for item in LOW_FLOAT_UNIVERSE}
        for future in as_completed(futures):
            res = future.result()
            if res:
                results.append(res)

    # Sort results
    priority_order = {
        "UPPER_LOCK": 1,
        "BREAKOUT": 2,
        "ACCUMULATION": 3,
        "DISTRIBUTION": 4,
        "RANGE": 5,
        "DORMANT": 6
    }
    results.sort(key=lambda x: (
        priority_order.get(x["phase_code"], 99),
        -x["float_turnover_pct"],
        -x["vol_surge_x"]
    ))

    upper_lock_count = sum(1 for s in results if s["phase_code"] == "UPPER_LOCK")
    volume_breakout_count = sum(1 for s in results if s["phase_code"] == "BREAKOUT")
    game_forming_count = sum(1 for s in results if s["phase_code"] == "ACCUMULATION")
    active_season_count = sum(1 for s in results if s["in_season"])

    payload = {
        "current_month": month_name,
        "total_tracked": len(results),
        "upper_lock_count": upper_lock_count,
        "volume_breakout_count": volume_breakout_count,
        "game_forming_count": game_forming_count,
        "active_season_count": active_season_count,
        "stocks": results
    }

    _CACHE["data"] = payload
    _CACHE["timestamp"] = now
    return payload

if __name__ == "__main__":
    data = analyze_low_float_stocks()
    print(f"Tracked: {data['total_tracked']}, Active Season: {data['active_season_count']}, Game Forming: {data['game_forming_count']}, Upper Lock: {data['upper_lock_count']}")
    for s in data["stocks"][:12]:
        print(f"[{s['symbol']:<5}] Rs.{s['price']:<7.2f} ({s['change_pct']:>+5.2f}%) | Vol:{s['volume']:>8,} ({s['vol_surge_x']:>4.1f}x) | FloatTurn:{s['float_turnover_pct']:>5.1f}% | {s['syndicate_phase']} | {s['char'][:40]}")
