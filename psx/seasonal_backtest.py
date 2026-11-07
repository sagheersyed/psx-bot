"""
psx/seasonal_backtest.py: Multi-Year Seasonal Cycle Backtester for Low-Float Stocks
Analyzes historical calendar seasonality, industry catalysts (Sugar crushing, Modaraba year-end,
Textile cotton harvest), and computes month-by-month historical win-rates and return matrices.
"""
from datetime import datetime
from zoneinfo import ZoneInfo
import pandas as pd
import numpy as np

import config
from . import data

MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

# Industry Seasonal Catalyst Registry
SECTOR_CATALYSTS = {
    "Sugar & Allied": {
        "peak_months": [10, 11, 12, 1, 2],
        "name": "Sugarcane Crushing Season",
        "description": "Mills begin crushing in Nov-Dec. Syndicates corner low-float shares ahead of production and sugar price announcements."
    },
    "Sugar & Allied (High-Beta)": {
        "peak_months": [10, 11, 12, 1, 2],
        "name": "Sugarcane Crushing Season",
        "description": "Mills begin crushing in Nov-Dec. Syndicates corner low-float shares ahead of production and sugar price announcements."
    },
    "Modarabas": {
        "peak_months": [9, 10, 11],
        "name": "Annual Financial Year-End & 90% Payout Window",
        "description": "Modarabas are legally mandated to distribute 90% of profits as dividends in Sep-Nov, triggering swift dividend-hunting pumps."
    },
    "Modarabas & Financials": {
        "peak_months": [9, 10, 11],
        "name": "Annual Financial Year-End & 90% Payout Window",
        "description": "Modarabas are legally mandated to distribute 90% of profits as dividends in Sep-Nov, triggering swift dividend-hunting pumps."
    },
    "Textile Spinning": {
        "peak_months": [10, 11, 12, 1],
        "name": "Cotton Harvest & Yarn Export Window",
        "description": "Cotton arrivals and yarn price spikes in winter create speculative liquidity waves across small-cap spinning mills."
    },
    "Textile Composite": {
        "peak_months": [10, 11, 12, 1],
        "name": "Global Winter Apparel & Textile Ordering Season",
        "description": "Export orders for spring/summer retail collections peak during Q3/Q4, driving composite textile revenues."
    },
    "Fertilizer": {
        "peak_months": [10, 11, 12, 4, 5],
        "name": "Rabi / Kharif Crop Sowing & Off-take Season",
        "description": "Wheat sowing in winter and Kharif planting in spring trigger heavy Urea and DAP seasonal off-take."
    },
    "Cement": {
        "peak_months": [1, 2, 3, 4, 5, 10, 11],
        "name": "Peak Construction & Infrastructure Season",
        "description": "Dry winter/spring construction weather boosts domestic dispatches before monsoon disruptions."
    },
    "Oil & Gas Exploration (E&P)": {
        "peak_months": [11, 12, 1, 2],
        "name": "Winter Peak Gas Demand & Field Production Cycle",
        "description": "Winter heating demand drives natural gas off-take to annual highs, improving cash flows."
    },
    "Commercial Banks": {
        "peak_months": [11, 12, 1, 6],
        "name": "Year-End Balance Sheet Closing & Dividend Cycle",
        "description": "Corporate year-end asset positioning and annual dividend declarations drive banking sector volume."
    },
    "Refinery": {
        "peak_months": [10, 11, 12, 1],
        "name": "Winter Fuel Oil & Diesel Demand Cycle",
        "description": "Transport diesel demand and winter furnace fuel utilization support refinery crack spreads."
    },
    "Technology & Communication": {
        "peak_months": [11, 12, 5, 6],
        "name": "Fiscal Year-End IT Billing & Export Settlement",
        "description": "Quarterly IT service invoicing and currency hedge positioning drive speculative technology momentum."
    },
    "Power Generation": {
        "peak_months": [4, 5, 6, 7],
        "name": "Summer Peak Load Dispatch & Capacity Payments",
        "description": "High summer electricity consumption raises plant load factors and dispatch incentives."
    },
    "Leather & Tanneries": {
        "peak_months": [9, 10, 11, 12],
        "name": "Post-Eid Raw Hide Collection & Winter Export Cycle",
        "description": "Leather garment and shoe export shipments peak during Q3/Q4 winter cycles."
    },
    "Automobile Assembler": {
        "peak_months": [11, 12, 1],
        "name": "New Year Model Invoicing & Agri-Tractor Demand",
        "description": "Tractor and auto assemblers see seasonal bookings spike post-crop harvests."
    }
}


def backtest_stock_seasonality(symbol: str, days: int = 1500) -> dict:
    """
    Backtests calendar seasonality across past 3-5 years:
    - Generates 12-Month Performance Heatmap (Years x Months)
    - Computes Historical Win Rate % and Average Return % for each calendar month
    - Evaluates Current Month Cycle Status & Industry Catalyst
    """
    symbol = symbol.upper().strip()
    df = data.fetch_history(symbol, "D", days=days)
    now_dt = datetime.now(ZoneInfo(config.TZ))
    current_month_idx = now_dt.month  # 1 to 12
    current_month_name = MONTH_NAMES[current_month_idx - 1]

    if df is None or len(df) < 30:
        return {
            "symbol": symbol,
            "has_data": False,
            "message": f"Historical candle data insufficient for multi-year backtesting."
        }

    try:
        # Resample daily candles to Calendar Month End
        monthly = df.resample("ME").agg({
            "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"
        }).dropna()

        if len(monthly) < 6:
            return {"symbol": symbol, "has_data": False, "message": "Less than 6 monthly bars available."}

        # Calculate monthly percentage return
        monthly["return_pct"] = ((monthly["close"] - monthly["open"]) / monthly["open"]) * 100.0
        monthly["year"] = monthly.index.year
        monthly["month"] = monthly.index.month

        years = [int(y) for y in sorted(list(monthly["year"].unique()))]
        
        # Build Heatmap Grid: rows = years, cols = months (1 to 12)
        grid_by_year = {}
        for y in years:
            grid_by_year[int(y)] = {m: None for m in range(1, 13)}

        for _, row in monthly.iterrows():
            y = int(row["year"])
            m = int(row["month"])
            val = round(float(row["return_pct"]), 1)
            if y in grid_by_year:
                grid_by_year[y][m] = val

        # Compute Month-by-Month Aggregate Statistics
        month_stats = []
        for m in range(1, 13):
            m_returns = monthly[monthly["month"] == m]["return_pct"].tolist()
            if m_returns:
                n = len(m_returns)
                green_count = sum(1 for r in m_returns if r > 0)
                win_rate = round((green_count / n) * 100, 1)
                avg_ret = round(float(np.mean(m_returns)), 1)
                max_ret = round(float(max(m_returns)), 1)
                min_ret = round(float(min(m_returns)), 1)
            else:
                win_rate, avg_ret, max_ret, min_ret, n = 50.0, 0.0, 0.0, 0.0, 0

            month_stats.append({
                "month_num": m,
                "month_name": MONTH_NAMES[m - 1],
                "sample_years": n,
                "win_rate": win_rate,
                "avg_return": avg_ret,
                "max_return": max_ret,
                "min_return": min_ret,
                "is_current": (m == current_month_idx)
            })

        # Find Best & Worst Months
        valid_stats = [ms for ms in month_stats if ms["sample_years"] >= 2]
        if valid_stats:
            best_m = max(valid_stats, key=lambda x: (x["win_rate"], x["avg_return"]))
            worst_m = min(valid_stats, key=lambda x: (x["win_rate"], x["avg_return"]))
        else:
            best_m = month_stats[0]
            worst_m = month_stats[0]

        # Current Month Evaluation
        curr_stat = month_stats[current_month_idx - 1]
        next_month_idx = (current_month_idx % 12) + 1
        next_stat = month_stats[next_month_idx - 1]

        # Determine Cycle Phase
        if curr_stat["win_rate"] >= 75.0 and curr_stat["avg_return"] >= 8.0:
            cycle_phase = "🔥 PRIME SEASONAL MARKUP WINDOW (Strong Bullish History)"
            cycle_code = "PRIME_MARKUP"
            badge_color = "amber"
        elif curr_stat["win_rate"] >= 60.0 or curr_stat["avg_return"] >= 4.0:
            cycle_phase = "🟢 FAVORABLE ACCUMULATION CYCLE"
            cycle_code = "FAVORABLE"
            badge_color = "emerald"
        elif curr_stat["win_rate"] <= 35.0 or curr_stat["avg_return"] <= -4.0:
            cycle_phase = "❄️ HISTORICAL OFF-SEASON (Low-Liquidity / Correction Window)"
            cycle_code = "OFF_SEASON"
            badge_color = "red"
        else:
            cycle_phase = "🟡 CONSOLIDATION / NEUTRAL SEASONAL PERIOD"
            cycle_code = "NEUTRAL"
            badge_color = "gray"

        # Check Industry Catalyst matching
        from . import low_float_analyzer, sector_rotation
        scrip_meta = next((item for item in low_float_analyzer.LOW_FLOAT_UNIVERSE if item["symbol"] == symbol), None)
        sec_name = scrip_meta.get("sector", "") if scrip_meta else ""
        
        # Fallback to sector_rotation SECTOR_MAP if not in low-float universe
        if not sec_name:
            for s_name, syms in sector_rotation.SECTOR_MAP.items():
                if symbol in syms:
                    sec_name = s_name
                    break

        catalyst = SECTOR_CATALYSTS.get(sec_name, {
            "name": "General Speculative Rotation",
            "description": "Cyclical market accumulation and liquidity turnover cycle."
        })

        return {
            "symbol": symbol,
            "has_data": True,
            "years": years,
            "heatmap": grid_by_year,
            "month_stats": month_stats,
            "current_month": {
                "month_name": current_month_name,
                "win_rate": curr_stat["win_rate"],
                "avg_return": curr_stat["avg_return"],
                "sample_years": curr_stat["sample_years"],
                "cycle_phase": cycle_phase,
                "cycle_code": cycle_code,
                "badge_color": badge_color
            },
            "best_month": {
                "name": best_m["month_name"],
                "win_rate": best_m["win_rate"],
                "avg_return": best_m["avg_return"]
            },
            "worst_month": {
                "name": worst_m["month_name"],
                "win_rate": worst_m["win_rate"],
                "avg_return": worst_m["avg_return"]
            },
            "next_month": {
                "name": next_stat["month_name"],
                "win_rate": next_stat["win_rate"],
                "avg_return": next_stat["avg_return"]
            },
            "industry_catalyst": {
                "sector": sec_name,
                "name": catalyst.get("name"),
                "description": catalyst.get("description"),
                "scrip_char": scrip_meta.get("char", "") if scrip_meta else ""
            }
        }
    except Exception as e:
        return {"symbol": symbol, "has_data": False, "message": str(e)}
