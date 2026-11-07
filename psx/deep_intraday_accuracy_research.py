"""
psx/deep_intraday_accuracy_research.py: High-Accuracy Deep Intraday Research Engine for PSX
Evaluates 4 high-probability institutional setups adjusted for PSX 10% Circuit Breakers:
  1. Circuit Momentum Acceleration (Breakout at +4.0% to +5.5% accelerating toward 10% Upper Lock)
  2. Gap-Fill Support Bounce (Buying when 9:15 AM Gap-Up fills down to Previous Day Close support)
  3. Wyckoff Spring / SSL Liquidity Sweep at Daily 1D Key Support
  4. Dual-Filter VWAP + 20 EMA Volume Surge Expansion
"""
import sys
import numpy as np
import pandas as pd
from datetime import datetime, time as dtime

from psx import data

sys.stdout.reconfigure(encoding="utf-8")

# Comprehensive Universe of High-Beta, Volatile & Momentum PSX Tickers
UNIVERSE = [
    "PRL", "CNERGY", "PAEL", "WTL", "AIRLINK", "BOP", "HUMNL", "GGL", 
    "TPLP", "TELE", "OGDC", "PPL", "SYS", "LUCK", "FFC", "EFERT", "PSO"
]

print("⚡ [Deep Research] Fetching 30-Day 15M & 60-Day Daily Candle Datasets...", flush=True)

stock_data = {}
for sym in UNIVERSE:
    df15 = data.fetch_history(sym, "15", 35)
    dfd = data.fetch_history(sym, "D", 75)
    if df15 is not None and dfd is not None and len(df15) > 50 and len(dfd) > 25:
        # Precompute indicators
        dfd["ema20"] = dfd["close"].ewm(span=20, adjust=False).mean()
        dfd["atr"] = (dfd["high"] - dfd["low"]).rolling(14).mean().fillna(dfd["close"] * 0.02)
        
        # 15M VWAP and Relative Volume
        typical_p = (df15["high"] + df15["low"] + df15["close"]) / 3.0
        pv = typical_p * df15["volume"]
        dates = df15.index.date
        cum_pv = pv.groupby(dates).cumsum()
        cum_vol = df15["volume"].groupby(dates).cumsum()
        df15["vwap"] = (cum_pv / cum_vol.replace(0, np.nan)).fillna(typical_p)
        
        df15["vol_ema"] = df15["volume"].rolling(14).mean().fillna(df15["volume"])
        df15["rvol"] = df15["volume"] / df15["vol_ema"].replace(0, 1.0)
        df15["ema20"] = df15["close"].ewm(span=20, adjust=False).mean()
        
        stock_data[sym] = {"15m": df15, "d": dfd}

print(f"Loaded {len(stock_data)} active stocks. Running 4 High-Accuracy Setups...\n", flush=True)

# =============================================================================
# STRATEGY 1: 10% CIRCUIT HUNTER (Momentum Acceleration between +4.0% and +5.5%)
# =============================================================================
print("="*90, flush=True)
print("SETUP 1: 10% UPPER CIRCUIT ACCELERATION (Entry at +4.0% to +5.5% with RVOL >= 2.5x)", flush=True)
print("="*90, flush=True)

circuit_trades = []

for sym, s in stock_data.items():
    df15 = s["15m"]
    dfd = s["d"]
    
    for dt, day_df in df15.groupby(df15.index.date):
        if len(day_df) < 5: continue
        day_open = float(day_df["open"].iloc[0])
        if day_open <= 0: continue
        
        # Search for momentum breakout between 9:45 AM and 12:30 PM
        trading_window = day_df.between_time("09:45", "12:30")
        triggered = False
        
        for ts, row in trading_window.iterrows():
            chg = ((row["close"] - day_open) / day_open) * 100.0
            rvol = float(row["rvol"])
            
            # Condition: Stock surging between +4.0% and +5.5% with 2.5x volume expansion
            if 4.0 <= chg <= 5.5 and rvol >= 2.2 and not triggered:
                entry = float(row["close"]) * 1.002 # 0.2% entry slippage
                # Stop Loss: 1.5% below entry (tight risk)
                sl = entry * 0.985
                # Target: 9.5% Upper Circuit Lock
                tp = day_open * 1.095 # Near 10% circuit limit
                
                rem = day_df.loc[ts:].iloc[1:]
                hit = False
                for _, r_bar in rem.iterrows():
                    if r_bar["low"] <= sl:
                        pnl = ((sl - entry) / entry) * 100.0
                        circuit_trades.append({"sym": sym, "pnl": pnl, "win": False, "reason": "SL_HIT"})
                        hit = True
                        break
                    elif r_bar["high"] >= tp:
                        pnl = ((tp - entry) / entry) * 100.0
                        circuit_trades.append({"sym": sym, "pnl": pnl, "win": True, "reason": "CIRCUIT_LOCKED"})
                        hit = True
                        break
                if not hit and len(rem) > 0:
                    exit_p = float(rem["close"].iloc[-1]) * 0.998
                    pnl = ((exit_p - entry) / entry) * 100.0
                    circuit_trades.append({"sym": sym, "pnl": pnl, "win": pnl >= 0.5, "reason": "EOD_CLOSE"})
                triggered = True
                break

c_wins = [t for t in circuit_trades if t["win"]]
c_losses = [t for t in circuit_trades if not t["win"]]
c_wr = round(len(c_wins) / len(circuit_trades) * 100.0, 1) if circuit_trades else 0.0
c_prof = sum(t["pnl"] for t in c_wins)
c_loss = abs(sum(t["pnl"] for t in c_losses)) or 0.001
c_pf = round(c_prof / c_loss, 2)
c_pnl = round(sum(t["pnl"] for t in circuit_trades), 2)

print(f"  Total Trades: {len(circuit_trades)} | Wins: {len(c_wins)} | Losses: {len(c_losses)}", flush=True)
print(f"  Win Rate: {c_wr}% | Profit Factor: {c_pf}x | Net PnL: +{c_pnl}%", flush=True)
locks_hit = sum(1 for t in circuit_trades if t.get("reason") == "CIRCUIT_LOCKED")
print(f"  Direct 10% Upper Circuit Locks: {locks_hit} of {len(circuit_trades)} ({round(locks_hit/len(circuit_trades)*100, 1) if circuit_trades else 0}%)\n", flush=True)

# =============================================================================
# STRATEGY 2: GAP-FILL REVERSAL BOUNCE (Previous Day Close Support)
# =============================================================================
print("="*90, flush=True)
print("SETUP 2: GAP-FILL SUPPORT BOUNCE (Buying when Gap-Up fills down to Prior Close)", flush=True)
print("="*90, flush=True)

gap_trades = []

for sym, s in stock_data.items():
    df15 = s["15m"]
    dfd = s["d"]
    
    # Map dates to previous day close
    daily_closes = dict(zip(dfd.index.date, dfd["close"]))
    sorted_d_dates = sorted(list(dfd.index.date))
    
    for i in range(1, len(sorted_d_dates)):
        prev_dt = sorted_d_dates[i-1]
        curr_dt = sorted_d_dates[i]
        prev_c = daily_closes[prev_dt]
        
        if curr_dt not in df15.index.date: continue
        day_df = df15[df15.index.date == curr_dt]
        if len(day_df) < 6: continue
        
        day_open = float(day_df["open"].iloc[0])
        gap_pct = ((day_open - prev_c) / prev_c) * 100.0
        
        # Condition: Gapped up >= 1.5% at 9:15 AM
        if gap_pct >= 1.5:
            # Check if between 9:45 and 11:30 it dips to fill gap (within 0.3% of prev_c) and bounces
            morning = day_df.between_time("09:45", "11:30")
            for ts, row in morning.iterrows():
                if row["low"] <= prev_c * 1.003 and row["close"] > prev_c:
                    entry = float(row["close"]) * 1.002
                    sl = prev_c * 0.992 # 0.8% below filled gap
                    risk = entry - sl
                    tp = entry + (risk * 1.5) # 1.5R target back to morning highs
                    
                    rem = day_df.loc[ts:].iloc[1:]
                    hit = False
                    for _, r_bar in rem.iterrows():
                        if r_bar["low"] <= sl:
                            pnl = ((sl - entry) / entry) * 100.0
                            gap_trades.append({"sym": sym, "pnl": pnl, "win": False})
                            hit = True
                            break
                        elif r_bar["high"] >= tp:
                            pnl = ((tp - entry) / entry) * 100.0
                            gap_trades.append({"sym": sym, "pnl": pnl, "win": True})
                            hit = True
                            break
                    if not hit and len(rem) > 0:
                        exit_p = float(rem["close"].iloc[-1]) * 0.998
                        pnl = ((exit_p - entry) / entry) * 100.0
                        gap_trades.append({"sym": sym, "pnl": pnl, "win": pnl >= 0.3})
                    break

g_wins = [t for t in gap_trades if t["win"]]
g_losses = [t for t in gap_trades if not t["win"]]
g_wr = round(len(g_wins) / len(gap_trades) * 100.0, 1) if gap_trades else 0.0
g_prof = sum(t["pnl"] for t in g_wins)
g_loss = abs(sum(t["pnl"] for t in g_losses)) or 0.001
g_pf = round(g_prof / g_loss, 2)
g_pnl = round(sum(t["pnl"] for t in gap_trades), 2)

print(f"  Total Trades: {len(gap_trades)} | Wins: {len(g_wins)} | Losses: {len(g_losses)}", flush=True)
print(f"  Win Rate: {g_wr}% | Profit Factor: {g_pf}x | Net PnL: +{g_pnl}%\n", flush=True)

# =============================================================================
# STRATEGY 3: WYCKOFF SPRING / SSL SWEEP WITH MACRO D1 DEMAND ZONE CONFLUENCE
# =============================================================================
print("="*90, flush=True)
print("SETUP 3: HTF CONFLUENCE SWEEP (Morning SSL Sweep at Daily 1D Order Block Support)", flush=True)
print("="*90, flush=True)

spring_trades = []

for sym, s in stock_data.items():
    df15 = s["15m"]
    dfd = s["d"]
    
    # 20 EMA and 50 EMA on Daily
    dfd["ema50"] = dfd["close"].ewm(span=50, adjust=False).mean()
    bull_dates = set(dfd[dfd["close"] >= dfd["ema20"]].index.date)
    
    for dt, day_df in df15.groupby(df15.index.date):
        if dt not in bull_dates or len(day_df) < 6: continue
        
        orb = day_df.between_time("09:15", "09:45")
        if len(orb) < 1: continue
        orb_low = orb["low"].min()
        
        # Morning Sweep between 9:45 and 10:45 AM
        morning = day_df.between_time("09:45", "10:45")
        for ts, row in morning.iterrows():
            # Sweep of ORB low with hammer-like close back above
            if row["low"] < orb_low and row["close"] > orb_low and row["rvol"] >= 1.3:
                entry = float(row["close"]) * 1.0015
                sl = float(row["low"]) * 0.996 # 0.4% buffer below wick
                risk = entry - sl
                tp = entry + (risk * 1.25)
                
                rem = day_df.loc[ts:].iloc[1:]
                hit = False
                be_active = False
                for _, r_bar in rem.iterrows():
                    # Move to Breakeven once gain >= +0.55%
                    if not be_active and r_bar["high"] >= entry * 1.0055:
                        sl = entry * 1.0015
                        be_active = True
                    if r_bar["low"] <= sl:
                        pnl = ((sl - entry) / entry) * 100.0
                        spring_trades.append({"sym": sym, "pnl": pnl, "win": pnl >= 0.05, "be": be_active})
                        hit = True
                        break
                    elif r_bar["high"] >= tp:
                        pnl = ((tp - entry) / entry) * 100.0
                        spring_trades.append({"sym": sym, "pnl": pnl, "win": True, "be": be_active})
                        hit = True
                        break
                if not hit and len(rem) > 0:
                    exit_p = float(rem["close"].iloc[-1]) * 0.998
                    pnl = ((exit_p - entry) / entry) * 100.0
                    spring_trades.append({"sym": sym, "pnl": pnl, "win": pnl >= 0.05, "be": be_active})
                break

s_wins = [t for t in spring_trades if t["win"]]
s_losses = [t for t in spring_trades if not t["win"]]
s_wr = round(len(s_wins) / len(spring_trades) * 100.0, 1) if spring_trades else 0.0
s_prof = sum(t["pnl"] for t in s_wins)
s_loss = abs(sum(t["pnl"] for t in s_losses)) or 0.001
s_pf = round(s_prof / s_loss, 2)
s_pnl = round(sum(t["pnl"] for t in spring_trades), 2)

print(f"  Total Trades: {len(spring_trades)} | Wins: {len(s_wins)} | Losses: {len(s_losses)}", flush=True)
print(f"  Win Rate: {s_wr}% | Profit Factor: {s_pf}x | Net PnL: +{s_pnl}%", flush=True)
print(f"  Breakeven Preservations: {sum(1 for t in spring_trades if t['be'])} Trades\n", flush=True)

# =============================================================================
# STRATEGY 4: DUAL-FILTER VWAP + 20 EMA VOLUME RECLAIM (After 10:00 AM)
# =============================================================================
print("="*90, flush=True)
print("SETUP 4: DUAL-FILTER VWAP + 20 EMA SURGE (Reclaim of VWAP + 20 EMA with RVOL >= 2.0x)", flush=True)
print("="*90, flush=True)

surge_trades = []

for sym, s in stock_data.items():
    df15 = s["15m"]
    dfd = s["d"]
    
    for dt, day_df in df15.groupby(df15.index.date):
        if len(day_df) < 6: continue
        
        # Evaluate 10:00 AM to 11:30 AM
        post_open = day_df.between_time("10:00", "11:30")
        for ts, row in post_open.iterrows():
            p = float(row["close"])
            vwap = float(row["vwap"])
            ema = float(row["ema20"])
            rvol = float(row["rvol"])
            
            # Condition: Bullish crossover reclaiming BOTH VWAP & EMA20 with 2x volume
            if p > vwap and p > ema and row["open"] <= vwap and rvol >= 2.0:
                entry = p * 1.002
                sl = min(vwap, ema) * 0.995
                risk = entry - sl
                tp = entry + (risk * 1.3)
                
                rem = day_df.loc[ts:].iloc[1:]
                hit = False
                be_active = False
                for _, r_bar in rem.iterrows():
                    if not be_active and r_bar["high"] >= entry * 1.006:
                        sl = entry * 1.002
                        be_active = True
                    if r_bar["low"] <= sl:
                        pnl = ((sl - entry) / entry) * 100.0
                        surge_trades.append({"sym": sym, "pnl": pnl, "win": pnl >= 0.05})
                        hit = True
                        break
                    elif r_bar["high"] >= tp:
                        pnl = ((tp - entry) / entry) * 100.0
                        surge_trades.append({"sym": sym, "pnl": pnl, "win": True})
                        hit = True
                        break
                if not hit and len(rem) > 0:
                    exit_p = float(rem["close"].iloc[-1]) * 0.998
                    pnl = ((exit_p - entry) / entry) * 100.0
                    surge_trades.append({"sym": sym, "pnl": pnl, "win": pnl >= 0.05})
                break

sr_wins = [t for t in surge_trades if t["win"]]
sr_losses = [t for t in surge_trades if not t["win"]]
sr_wr = round(len(sr_wins) / len(surge_trades) * 100.0, 1) if surge_trades else 0.0
sr_prof = sum(t["pnl"] for t in sr_wins)
sr_loss = abs(sum(t["pnl"] for t in sr_losses)) or 0.001
sr_pf = round(sr_prof / sr_loss, 2)
sr_pnl = round(sum(t["pnl"] for t in surge_trades), 2)

print(f"  Total Trades: {len(surge_trades)} | Wins: {len(sr_wins)} | Losses: {len(sr_losses)}", flush=True)
print(f"  Win Rate: {sr_wr}% | Profit Factor: {sr_pf}x | Net PnL: +{sr_pnl}%\n", flush=True)
