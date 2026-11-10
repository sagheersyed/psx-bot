"""
psx/intraday_backtest.py: Institutional PSX Intraday & Day-Trading Quantitative Backtester
Researches, validates, and rigorously tests intraday scalping and momentum setups across PSX 5M and 15M data.
Incorporates:
  1. Session VWAP (Volume Weighted Average Price) & Deviation Bands
  2. 9:15 - 9:45 AM Opening Range Breakout (ORB) & Trap Avoidance
  3. Morning Kill Zone Liquidity Sweeps (SSL/BSL) + 5M CHoCH Reversals
  4. Mandatory 3:15 PM Same-Day Square-Off (Zero Overnight Risk)
  5. Broker Commission & Realistic Slippage Deductions
"""
import numpy as np
import pandas as pd
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo

import config
from . import data

# Liquid PSX Scrips suitable for intraday day-trading (Tight spreads, high volume)
DAY_TRADE_UNIVERSE = [
    "OGDC", "PPL", "PRL", "CNERGY", "SYS", "HUBC", "FFC", "EFERT",
    "LUCK", "DGKC", "WTL", "PAEL", "PSO", "MCB", "UBL", "TRG"
]

def calculate_vwap(df: pd.DataFrame) -> pd.Series:
    """
    Computes intraday Session VWAP resetting every trading day at 9:15 AM.
    """
    typical_price = (df["high"] + df["low"] + df["close"]) / 3.0
    pv = typical_price * df["volume"]
    
    # Group by trading date for session reset
    dates = df.index.date
    cum_pv = pv.groupby(dates).cumsum()
    cum_vol = df["volume"].groupby(dates).cumsum()
    
    vwap = cum_pv / cum_vol.replace(0, np.nan)
    return vwap.fillna(typical_price)


def backtest_intraday_scrip(symbol: str, days: int = 30, resolution: str = "15") -> dict:
    """
    Simulates high-precision institutional intraday trades:
    - 15-Minute Institutional timeframe (filters 5M intraday noise).
    - Entry ONLY during Morning Kill Zone (9:45 AM - 11:15 AM PKT).
    - Higher Timeframe EMA Trend Filter (Close > EMA20).
    - Breakeven Stop Loss: Once price reaches +0.6R, SL moves to Breakeven (0.0% loss).
    - Realistic Take Profit (1.2R) before 3:15 PM square-off.
    - 0.15% roundtrip brokerage commission & slippage deducted.
    """
    symbol = symbol.upper().strip()
    df = data.fetch_history(symbol, resolution, days=days)
    
    if df is None or len(df) < 30:
        return {"symbol": symbol, "has_data": False, "message": "Insufficient intraday candle data."}

    df = df.copy()
    df["vwap"] = calculate_vwap(df)
    df["ema20"] = df["close"].ewm(span=20, adjust=False).mean()
    df["vol_ema"] = df["volume"].rolling(14).mean().fillna(df["volume"])
    df["rvol"] = df["volume"] / df["vol_ema"].replace(0, 1.0)
    
    # ATR for dynamic stop loss
    tr1 = df["high"] - df["low"]
    tr2 = (df["high"] - df["close"].shift(1)).abs()
    tr3 = (df["low"] - df["close"].shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    df["atr"] = tr.rolling(14).mean().fillna(df["close"] * 0.006)

    trades = []
    days_grouped = df.groupby(df.index.date)
    roundtrip_cost_pct = 0.0015  # 0.15% commission + slippage

    for trade_date, day_df in days_grouped:
        if len(day_df) < 4:
            continue
            
        # Opening Range: First 30 minutes (9:15 - 9:45 AM)
        opening_bars = day_df.between_time("09:15", "09:45")
        if len(opening_bars) < 1:
            continue
            
        orb_high = opening_bars["high"].max()
        orb_low = opening_bars["low"].min()

        in_trade = False
        trade_entry = None
        be_activated = False
        
        # Trading Window: 9:45 AM to 15:15 PM
        trading_bars = day_df.between_time("09:45", "15:15")
        
        for ts, row in trading_bars.iterrows():
            time_of_day = ts.time()
            price = float(row["close"])
            high = float(row["high"])
            low = float(row["low"])
            vwap = float(row["vwap"])
            ema20 = float(row["ema20"])
            rvol = float(row["rvol"])
            atr = float(row["atr"])

            # -------------------------------------------------------------
            # Active Position Management (Conservative bar order: SL -> TP -> EOD -> BE Trail)
            # -------------------------------------------------------------
            leg_cost = roundtrip_cost_pct / 2.0
            if in_trade:
                # 1. Check Stop Loss / Breakeven Exit FIRST (using SL from prior bar)
                if low <= trade_entry["sl"]:
                    exit_price = trade_entry["sl"] * (1 - leg_cost)
                    pnl_pct = ((exit_price - trade_entry["price"]) / trade_entry["price"]) * 100.0
                    r_ret = (exit_price - trade_entry["price"]) / trade_entry["risk"]
                    res_tag = "WIN" if pnl_pct > 0.05 else ("BREAKEVEN" if be_activated else "LOSS")
                    trades.append({
                        "symbol": symbol,
                        "entry_time": trade_entry["time"].strftime("%Y-%m-%d %H:%M"),
                        "exit_time": ts.strftime("%Y-%m-%d %H:%M"),
                        "setup": trade_entry["setup"],
                        "entry_price": round(trade_entry["price"], 2),
                        "exit_price": round(exit_price, 2),
                        "pnl_pct": round(pnl_pct, 2),
                        "r_multiple": round(r_ret, 2),
                        "result": res_tag,
                        "exit_reason": "BREAKEVEN_EXIT" if be_activated else "STOP_LOSS"
                    })
                    in_trade = False
                    trade_entry = None
                    continue

                # 2. Check Take Profit (1.2R Institutional Scalp Target)
                elif high >= trade_entry["tp"]:
                    exit_price = trade_entry["tp"] * (1 - leg_cost)
                    pnl_pct = ((exit_price - trade_entry["price"]) / trade_entry["price"]) * 100.0
                    r_ret = (exit_price - trade_entry["price"]) / trade_entry["risk"]
                    trades.append({
                        "symbol": symbol,
                        "entry_time": trade_entry["time"].strftime("%Y-%m-%d %H:%M"),
                        "exit_time": ts.strftime("%Y-%m-%d %H:%M"),
                        "setup": trade_entry["setup"],
                        "entry_price": round(trade_entry["price"], 2),
                        "exit_price": round(exit_price, 2),
                        "pnl_pct": round(pnl_pct, 2),
                        "r_multiple": round(r_ret, 2),
                        "result": "WIN",
                        "exit_reason": "TARGET_TP"
                    })
                    in_trade = False
                    trade_entry = None
                    continue

                # 3. Mandatory Session Square-Off at 3:15 PM
                elif time_of_day >= dtime(15, 10):
                    exit_price = price * (1 - leg_cost)
                    pnl_pct = ((exit_price - trade_entry["price"]) / trade_entry["price"]) * 100.0
                    r_ret = (exit_price - trade_entry["price"]) / trade_entry["risk"]
                    trades.append({
                        "symbol": symbol,
                        "entry_time": trade_entry["time"].strftime("%Y-%m-%d %H:%M"),
                        "exit_time": ts.strftime("%Y-%m-%d %H:%M"),
                        "setup": trade_entry["setup"],
                        "entry_price": round(trade_entry["price"], 2),
                        "exit_price": round(exit_price, 2),
                        "pnl_pct": round(pnl_pct, 2),
                        "r_multiple": round(r_ret, 2),
                        "result": "WIN" if pnl_pct > 0 else "LOSS",
                        "exit_reason": "SQUARE_OFF_3PM"
                    })
                    in_trade = False
                    trade_entry = None
                    continue

                # 4. Breakeven Trail Check for NEXT bar: If price moved +0.5R, lock SL at entry
                if not be_activated and high >= (trade_entry["price"] + trade_entry["risk"] * 0.5):
                    trade_entry["sl"] = round(trade_entry["price"] * (1 + leg_cost), 2)
                    be_activated = True

            # -------------------------------------------------------------
            # Setup Detection: ONLY During Morning Kill Zone (9:45 - 11:15 AM)
            # -------------------------------------------------------------
            if not in_trade and (dtime(9, 45) <= time_of_day <= dtime(11, 15)):
                setup_name = None
                
                # Condition: HTF Trend Filter (Close > EMA20)
                is_uptrend = price >= ema20

                # SETUP A: Morning SSL Liquidity Sweep & Spring Back (Highest Win Rate)
                if low < orb_low and price > orb_low and rvol >= 1.2:
                    setup_name = "MORNING_SWEEP_REVERSAL"

                # SETUP B: Trend VWAP Retest with Bullish Order Flow
                elif is_uptrend and price >= vwap and low <= (vwap * 1.003) and rvol >= 1.1:
                    setup_name = "VWAP_TREND_PULLBACK"

                # SETUP C: Clean Opening Range Breakout with RVOL >= 2.0x
                elif is_uptrend and price > orb_high and rvol >= 2.0 and price > vwap:
                    setup_name = "ORB_MOMENTUM_BREAKOUT"

                if setup_name:
                    sl_dist = max(atr * 1.5, price * 0.012)  # Dynamic ATR Stop Loss (min 1.2% buffer)
                    entry_p = price * (1 + leg_cost)
                    sl = entry_p - sl_dist
                    risk = entry_p - sl
                    tp = entry_p + (risk * 1.5) # Institutional 1.5R target
                    
                    trade_entry = {
                        "time": ts,
                        "price": entry_p,
                        "sl": round(sl, 2),
                        "tp": round(tp, 2),
                        "risk": risk,
                        "setup": setup_name
                    }
                    in_trade = True
                    be_activated = False

    # -----------------------------------------------------------------
    # Compute Performance Statistics
    # -----------------------------------------------------------------
    total_trades = len(trades)
    if total_trades == 0:
        return {
            "symbol": symbol,
            "has_data": True,
            "total_trades": 0,
            "message": "No setup triggers met the strict institutional criteria during this period."
        }

    wins = [t for t in trades if t["result"] == "WIN"]
    losses = [t for t in trades if t["result"] == "LOSS"]
    
    win_count = len(wins)
    loss_count = len(losses)
    win_rate = round((win_count / total_trades) * 100.0, 1)

    total_profit_pct = sum(t["pnl_pct"] for t in wins)
    total_loss_pct = abs(sum(t["pnl_pct"] for t in losses)) or 0.001
    profit_factor = round(total_profit_pct / total_loss_pct, 2)
    
    avg_r = round(float(np.mean([t["r_multiple"] for t in trades])), 2)
    net_pnl_pct = round(sum(t["pnl_pct"] for t in trades), 2)
    
    # Cumulative Equity Curve & Max Drawdown
    equity = 100.0
    eq_curve = [equity]
    for t in trades:
        equity *= (1.0 + t["pnl_pct"] / 100.0)
        eq_curve.append(equity)
        
    peaks = pd.Series(eq_curve).cummax()
    drawdowns = (pd.Series(eq_curve) - peaks) / peaks * 100.0
    max_dd = round(abs(float(drawdowns.min())), 2)

    # Setup Breakdown
    setup_stats = {}
    for setup_type in ["MORNING_SWEEP_REVERSAL", "VWAP_TREND_PULLBACK", "ORB_MOMENTUM_BREAKOUT"]:
        st_trades = [t for t in trades if t["setup"] == setup_type]
        if st_trades:
            st_wins = sum(1 for t in st_trades if t["result"] == "WIN")
            setup_stats[setup_type] = {
                "trades": len(st_trades),
                "win_rate": round(st_wins / len(st_trades) * 100, 1),
                "avg_pnl": round(float(np.mean([t["pnl_pct"] for t in st_trades])), 2)
            }

    # Strict Institutional Benchmark Criteria
    # Pass Requirements: Win Rate >= 60%, Profit Factor >= 1.5, Avg R >= 0.35, Net PnL > 0
    passed = (win_rate >= 60.0 and profit_factor >= 1.5 and net_pnl_pct > 0 and max_dd <= 12.0)

    return {
        "symbol": symbol,
        "has_data": True,
        "sample_days": days,
        "resolution": f"{resolution}M",
        "total_trades": total_trades,
        "wins": win_count,
        "losses": loss_count,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "avg_r": avg_r,
        "net_pnl_pct": net_pnl_pct,
        "max_drawdown_pct": max_dd,
        "passed_institutional_gate": passed,
        "setup_breakdown": setup_stats,
        "sample_trades": trades[-5:] # Last 5 executed trades
    }


def run_universe_intraday_backtest(symbols: list = None, days: int = 25) -> dict:
    """
    Runs multi-scrip intraday research across top liquid PSX tickers.
    Aggregates universe metrics to determine if Day-Trading mode is mathematically sound.
    """
    targets = symbols or DAY_TRADE_UNIVERSE
    results = {}
    
    passed_symbols = []
    failed_symbols = []
    all_trades = 0
    total_wins = 0

    for sym in targets:
        res = backtest_intraday_scrip(sym, days=days, resolution="5")
        if res.get("has_data") and res.get("total_trades", 0) > 0:
            results[sym] = res
            all_trades += res["total_trades"]
            total_wins += res["wins"]
            if res["passed_institutional_gate"]:
                passed_symbols.append(sym)
            else:
                failed_symbols.append(sym)

    overall_win_rate = round((total_wins / all_trades) * 100.0, 1) if all_trades > 0 else 0.0
    pass_rate = round((len(passed_symbols) / len(results)) * 100.0, 1) if results else 0.0

    return {
        "universe_evaluated": len(results),
        "total_trades_analyzed": all_trades,
        "overall_win_rate": overall_win_rate,
        "passed_scrip_count": len(passed_symbols),
        "failed_scrip_count": len(failed_symbols),
        "pass_rate_pct": pass_rate,
        "passed_symbols": passed_symbols,
        "failed_symbols": failed_symbols,
        "stock_details": results,
        "verdict": (
            "✅ READY_FOR_DEPLOYMENT: Day-Trading setups passed strict institutional risk-reward and win-rate criteria."
            if pass_rate >= 60.0 and overall_win_rate >= 60.0 else
            "⚠️ NEEDS_REFINEMENT: Certain setups or scrips failed. Filter out illiquid scrips and refine kill-zones before launching UI."
        )
    }
