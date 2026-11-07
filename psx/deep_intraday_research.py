"""
psx/deep_intraday_research.py: Deep Quantitative Research for PSX Intraday Mechanics
Analyzes:
  1. Blue-Chips vs High-Beta Momentum Intraday Daily Ranges (%)
  2. PSX 30-Minute Time-of-Day Volume & Volatility Decay Curve
  3. Pre-Lock Circuit Momentum Acceleration Probability (+3.5% -> +7.5%)
  4. Gap-Up Opening Exhaustion / Gap Fill Rate
"""
import sys
import numpy as np
import pandas as pd
from datetime import datetime, time as dtime

from psx import data

sys.stdout.reconfigure(encoding="utf-8")

BLUE_CHIPS = ["OGDC", "PPL", "SYS", "LUCK", "FFC", "EFERT", "HUBC", "MCB"]
HIGH_BETA = ["PRL", "CNERGY", "PAEL", "WTL", "AIRLINK", "BOP", "HUMNL", "GGL", "TPLP"]

print("⚡ Fetching datasets for Blue-Chips vs High-Beta Momentum...", flush=True)

all_syms = BLUE_CHIPS + HIGH_BETA
stock_dfs = {}
daily_dfs = {}

for s in all_syms:
    df15 = data.fetch_history(s, "15", 30)
    dfd = data.fetch_history(s, "D", 60)
    if df15 is not None and dfd is not None and len(df15) > 50 and len(dfd) > 20:
        stock_dfs[s] = df15
        daily_dfs[s] = dfd

print(f"Loaded {len(stock_dfs)} stocks. Running Deep Forensic Analysis...\n", flush=True)

# -----------------------------------------------------------------------------
# 1. Intraday Daily Range Comparison (Blue-Chip vs High-Beta)
# -----------------------------------------------------------------------------
print("="*85, flush=True)
print("1. INTRADAY EXPANSION CAPACITY: BLUE-CHIPS VS HIGH-BETA RUNNERS", flush=True)
print("="*85, flush=True)

bc_ranges = []
for s in BLUE_CHIPS:
    if s in daily_dfs:
        df = daily_dfs[s]
        rng = ((df["high"] - df["low"]) / df["open"] * 100.0).dropna()
        bc_ranges.append({"sym": s, "avg_range": round(rng.mean(), 2), "max_range": round(rng.max(), 2)})

hb_ranges = []
for s in HIGH_BETA:
    if s in daily_dfs:
        df = daily_dfs[s]
        rng = ((df["high"] - df["low"]) / df["open"] * 100.0).dropna()
        hb_ranges.append({"sym": s, "avg_range": round(rng.mean(), 2), "max_range": round(rng.max(), 2)})

print("BLUE-CHIPS (Slow Intraday Movers):", flush=True)
for r in bc_ranges:
    print(f"  {r['sym']:<8}: Avg Range: {r['avg_range']:>4.2f}% | Peak Single-Day: {r['max_range']}%", flush=True)
avg_bc = round(np.mean([r['avg_range'] for r in bc_ranges]), 2)
print(f"  --> BLUE-CHIP AVERAGE INTRADAY RANGE: {avg_bc}%\n", flush=True)

print("HIGH-BETA MOMENTUM (Volatile Day-Trading Runners):", flush=True)
for r in hb_ranges:
    print(f"  {r['sym']:<8}: Avg Range: {r['avg_range']:>4.2f}% | Peak Single-Day: {r['max_range']}%", flush=True)
avg_hb = round(np.mean([r['avg_range'] for r in hb_ranges]), 2)
print(f"  --> HIGH-BETA AVERAGE INTRADAY RANGE: {avg_hb}%", flush=True)
print(f"  --> HIGH-BETA OFFERS {round(avg_hb / avg_bc, 2)}x LARGER INTRADAY TARGET WINDOW!\n", flush=True)

# -----------------------------------------------------------------------------
# 2. 30-Minute PSX Time-of-Day Volume & Volatility Heatmap
# -----------------------------------------------------------------------------
print("="*85, flush=True)
print("2. PSX 30-MINUTE TIME-OF-DAY VOLUME & VOLATILITY PROFILE", flush=True)
print("="*85, flush=True)

time_bins = {
    "09:15 - 09:45": [],
    "09:45 - 10:30": [],
    "10:30 - 11:30": [],
    "11:30 - 12:30": [],
    "12:30 - 13:30": [],
    "13:30 - 14:30": [],
    "14:30 - 15:15": []
}

for s, df in stock_dfs.items():
    for dt, day_df in df.groupby(df.index.date):
        tot_vol = day_df["volume"].sum() or 1.0
        
        b1 = day_df.between_time("09:15", "09:45")
        b2 = day_df.between_time("09:45", "10:30")
        b3 = day_df.between_time("10:30", "11:30")
        b4 = day_df.between_time("11:30", "12:30")
        b5 = day_df.between_time("12:30", "13:30")
        b6 = day_df.between_time("13:30", "14:30")
        b7 = day_df.between_time("14:30", "15:15")
        
        if len(b1): time_bins["09:15 - 09:45"].append(b1["volume"].sum() / tot_vol * 100.0)
        if len(b2): time_bins["09:45 - 10:30"].append(b2["volume"].sum() / tot_vol * 100.0)
        if len(b3): time_bins["10:30 - 11:30"].append(b3["volume"].sum() / tot_vol * 100.0)
        if len(b4): time_bins["11:30 - 12:30"].append(b4["volume"].sum() / tot_vol * 100.0)
        if len(b5): time_bins["12:30 - 13:30"].append(b5["volume"].sum() / tot_vol * 100.0)
        if len(b6): time_bins["13:30 - 14:30"].append(b6["volume"].sum() / tot_vol * 100.0)
        if len(b7): time_bins["14:30 - 15:15"].append(b7["volume"].sum() / tot_vol * 100.0)

for t_slot, vols in time_bins.items():
    avg_v = round(float(np.mean(vols)), 1) if vols else 0.0
    bar_viz = "█" * int(avg_v / 2)
    print(f"  {t_slot:<15} : {avg_v:>5.1f}% Volume Share | {bar_viz}", flush=True)

# -----------------------------------------------------------------------------
# 3. Pre-Lock Circuit Momentum Acceleration Probability
# -----------------------------------------------------------------------------
print("\n" + "="*85, flush=True)
print("3. CIRCUIT HUNTER: MOMENTUM PUSH INTO +7.5% UPPER CIRCUIT LOCK", flush=True)
print("="*85, flush=True)

circuit_triggers = 0
circuit_locks = 0
mfe_gains = []

for s in HIGH_BETA:
    if s in stock_dfs:
        df = stock_dfs[s]
        for dt, day_df in df.groupby(df.index.date):
            if len(day_df) < 5: continue
            day_open = float(day_df["open"].iloc[0])
            if day_open <= 0: continue
            
            # Detect morning acceleration above +3.5%
            morning = day_df.between_time("09:45", "12:00")
            triggered_today = False
            for ts, row in morning.iterrows():
                chg_from_open = ((row["close"] - day_open) / day_open) * 100.0
                if chg_from_open >= 3.5 and not triggered_today:
                    circuit_triggers += 1
                    triggered_today = True
                    
                    # Check maximum high achieved after trigger
                    rem_day = day_df.loc[ts:]
                    max_p = rem_day["high"].max()
                    max_gain = ((max_p - row["close"]) / row["close"]) * 100.0
                    mfe_gains.append(max_gain)
                    
                    # Did it reach circuit lock level (+7.0% or more from open)?
                    day_max_chg = ((max_p - day_open) / day_open) * 100.0
                    if day_max_chg >= 7.0:
                        circuit_locks += 1
                    break

lock_rate = round(circuit_locks / circuit_triggers * 100.0, 1) if circuit_triggers else 0.0
avg_mfe = round(float(np.mean(mfe_gains)), 2) if mfe_gains else 0.0

print(f"  High-Beta Acceleration Triggers (Morning +3.5% Breakout): {circuit_triggers} Occurrences", flush=True)
print(f"  Successfully Accelerated to Upper Circuit (+7.0% to +7.5%): {circuit_locks} Locked", flush=True)
print(f"  Upper Circuit Hit Rate: {lock_rate}%", flush=True)
print(f"  Average Follow-through Gain after +3.5% Entry: +{avg_mfe}%\n", flush=True)

# -----------------------------------------------------------------------------
# 4. Opening Gap Fade Rate (Gap-Up > 1.5% at 9:15 AM)
# -----------------------------------------------------------------------------
print("="*85, flush=True)
print("4. OPENING GAP-UP FADE TEST: DOES 9:15 AM GAP-UP EXPAND OR TRAP?", flush=True)
print("="*85, flush=True)

gap_ups = 0
gap_fills = 0

for s in all_syms:
    if s in daily_dfs:
        df = daily_dfs[s]
        for i in range(1, len(df)):
            prev_c = float(df["close"].iloc[i-1])
            curr_o = float(df["open"].iloc[i])
            curr_l = float(df["low"].iloc[i])
            
            gap_pct = ((curr_o - prev_c) / prev_c) * 100.0
            if gap_pct >= 1.5:
                gap_ups += 1
                # Did low drop to or below previous close (Gap Fill)?
                if curr_l <= prev_c * 1.002:
                    gap_fills += 1

fade_rate = round(gap_fills / gap_ups * 100.0, 1) if gap_ups else 0.0
print(f"  Total Morning Gap-Up Opens (> +1.5%): {gap_ups} Times", flush=True)
print(f"  Trapped & Completely Filled Gap during the session: {gap_fills} Times", flush=True)
print(f"  Gap Fade / Bull Trap Probability: {fade_rate}%\n", flush=True)
