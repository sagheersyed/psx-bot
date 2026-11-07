"""
psx/intraday_optimizer.py: Machine Optimization & Training Engine for PSX Day Trading
Grid searches across execution parameters, time windows, and indicator filters
to maximize Win Rate, Profit Factor, and Risk-to-Reward while minimizing Drawdown.
"""
import numpy as np
import pandas as pd
from datetime import datetime, time as dtime
from . import data

def calculate_vwap(df: pd.DataFrame) -> pd.Series:
    typical_price = (df["high"] + df["low"] + df["close"]) / 3.0
    pv = typical_price * df["volume"]
    dates = df.index.date
    cum_pv = pv.groupby(dates).cumsum()
    cum_vol = df["volume"].groupby(dates).cumsum()
    vwap = cum_pv / cum_vol.replace(0, np.nan)
    return vwap.fillna(typical_price)


def evaluate_strategy(
    df: pd.DataFrame,
    rvol_thresh: float = 1.5,
    sl_atr_mult: float = 1.0,
    tp_mult: float = 1.0,
    be_trigger_pct: float = 0.5,
    use_htf_trend: bool = True,
    allowed_setups: list = None
) -> dict:
    allowed_setups = allowed_setups or ["SWEEP", "ORB", "VWAP"]
    roundtrip_cost = 0.0015 # 0.15% commission + slippage
    
    trades = []
    days_grouped = df.groupby(df.index.date)

    for trade_date, day_df in days_grouped:
        if len(day_df) < 6:
            continue
            
        opening_bars = day_df.between_time("09:15", "09:45")
        if len(opening_bars) < 1:
            continue
            
        orb_high = opening_bars["high"].max()
        orb_low = opening_bars["low"].min()
        
        in_trade = False
        trade_entry = None
        be_active = False

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

            if in_trade:
                # 1. Breakeven Trail Activation
                gain_from_entry = ((high - trade_entry["price"]) / trade_entry["price"]) * 100.0
                if not be_active and gain_from_entry >= be_trigger_pct:
                    trade_entry["sl"] = trade_entry["price"] * (1 + roundtrip_cost)
                    be_active = True

                # 2. Check Stop Loss / Breakeven
                if low <= trade_entry["sl"]:
                    exit_p = trade_entry["sl"] * (1 - roundtrip_cost)
                    pnl = ((exit_p - trade_entry["price"]) / trade_entry["price"]) * 100.0
                    r_ret = (exit_p - trade_entry["price"]) / trade_entry["risk"]
                    trades.append({
                        "pnl": pnl, "r": r_ret,
                        "win": pnl >= 0.02,
                        "reason": "BE" if be_active else "SL",
                        "setup": trade_entry["setup"]
                    })
                    in_trade = False
                    trade_entry = None
                    continue

                # 3. Check Take Profit
                elif high >= trade_entry["tp"]:
                    exit_p = trade_entry["tp"] * (1 - roundtrip_cost)
                    pnl = ((exit_p - trade_entry["price"]) / trade_entry["price"]) * 100.0
                    r_ret = (exit_p - trade_entry["price"]) / trade_entry["risk"]
                    trades.append({
                        "pnl": pnl, "r": r_ret, "win": True,
                        "reason": "TP", "setup": trade_entry["setup"]
                    })
                    in_trade = False
                    trade_entry = None
                    continue

                # 4. Mandatory Session Square-Off at 3:15 PM
                elif time_of_day >= dtime(15, 10):
                    exit_p = price * (1 - roundtrip_cost)
                    pnl = ((exit_p - trade_entry["price"]) / trade_entry["price"]) * 100.0
                    r_ret = (exit_p - trade_entry["price"]) / trade_entry["risk"]
                    trades.append({
                        "pnl": pnl, "r": r_ret, "win": pnl > 0.05,
                        "reason": "EOD", "setup": trade_entry["setup"]
                    })
                    in_trade = False
                    trade_entry = None
                    continue

            # Entry Trigger: ONLY during Morning Kill Zone (9:45 - 11:15 AM)
            if not in_trade and (dtime(9, 45) <= time_of_day <= dtime(11, 15)):
                if use_htf_trend and price < ema20:
                    continue

                setup = None
                # Setup 1: Sweep of ORB low with strong close back inside
                if "SWEEP" in allowed_setups and low < orb_low and price > orb_low and rvol >= rvol_thresh:
                    setup = "SWEEP"
                # Setup 2: ORB Breakout with high volume
                elif "ORB" in allowed_setups and price > orb_high and rvol >= (rvol_thresh * 1.2) and price > vwap:
                    setup = "ORB"
                # Setup 3: VWAP Reclaim with high volume
                elif "VWAP" in allowed_setups and price > vwap and row["open"] <= vwap and rvol >= rvol_thresh:
                    setup = "VWAP"

                if setup:
                    sl_dist = max(atr * sl_atr_mult, price * 0.006)
                    sl = price - sl_dist
                    risk = price - sl
                    tp = price + (risk * tp_mult)
                    
                    trade_entry = {
                        "price": price * (1 + roundtrip_cost),
                        "sl": sl, "tp": tp, "risk": risk, "setup": setup
                    }
                    in_trade = True
                    be_active = False

    if not trades:
        return {"trades": 0, "win_rate": 0, "profit_factor": 0, "net_pnl": 0, "be_saves": 0}

    wins = [t for t in trades if t["win"]]
    losses = [t for t in trades if not t["win"]]
    win_rate = round(len(wins) / len(trades) * 100.0, 1)
    
    tot_profit = sum(t["pnl"] for t in wins)
    tot_loss = abs(sum(t["pnl"] for t in losses)) or 0.001
    profit_factor = round(tot_profit / tot_loss, 2)
    net_pnl = round(sum(t["pnl"] for t in trades), 2)
    
    return {
        "trades": len(trades),
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "net_pnl": net_pnl,
        "be_saves": sum(1 for t in trades if t["reason"] == "BE")
    }
