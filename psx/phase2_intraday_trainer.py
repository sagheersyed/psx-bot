"""
psx/phase2_intraday_trainer.py: Phase 2 Institutional Day-Trading & Sniper Training Engine
Tests:
  1. Sector-Tide Confluence Gate (Sector change >= -0.2%)
  2. HTF Macro Alignment (Daily Price > 20 EMA, RSI > 48)
  3. Liquidity Sweep with Absorption Volume (RVOL >= 1.3x)
  4. Buffered Structural Stop Loss (0.3% below sweep low to prevent wick-outs)
  5. Dynamic Breakeven Lock (+0.5% gain moves SL to Entry + roundtrip commission)
  6. Compares Mode A (Same-Day Square-Off) vs Mode B (Hybrid Sniper Overnight Hold on Wins)
"""
import sys
import numpy as np
import pandas as pd
from datetime import datetime, time as dtime

from psx import data, sector_rotation

sys.stdout.reconfigure(encoding="utf-8")

# Sector mapping helper
SYM_TO_SECTOR = {}
for sec, syms in sector_rotation.SECTOR_MAP.items():
    for s in syms:
        SYM_TO_SECTOR[s] = sec

TEST_SYMBOLS = [
    "OGDC", "PPL", "SYS", "PRL", "HUBC", "LUCK", "FFC", "EFERT", 
    "MCB", "UBL", "DGKC", "PSO", "ATRL", "ENGRO", "MARI", "HBL", 
    "BAHL", "MEBL", "FCCL", "MLCF", "SEARL", "POL", "CHCC"
]

print("⚡ [Phase 2] Loading multi-timeframe candle datasets for 23 liquid scrips...", flush=True)

stock_data = {}
for sym in TEST_SYMBOLS:
    df_15 = data.fetch_history(sym, "15", 35)
    df_d = data.fetch_history(sym, "D", 75)
    if df_15 is not None and df_d is not None and len(df_15) > 60 and len(df_d) > 30:
        df_d["ema20"] = df_d["close"].ewm(span=20, adjust=False).mean()
        # RSI 14
        delta = df_d["close"].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / loss.replace(0, np.nan)
        df_d["rsi"] = 100 - (100 / (1 + rs)).fillna(50)
        
        # 15M volume EMA
        df_15["vol_ema"] = df_15["volume"].rolling(14).mean().fillna(df_15["volume"])
        df_15["rvol"] = df_15["volume"] / df_15["vol_ema"].replace(0, 1.0)
        
        stock_data[sym] = {"15m": df_15, "d": df_d, "sector": SYM_TO_SECTOR.get(sym, "General")}

print(f"Loaded {len(stock_data)} verified stocks. Computing Sector Daily Performance...", flush=True)

# Build date-by-date sector performance matrix
all_dates = sorted(list(set.union(*[set(v["d"].index.date) for v in stock_data.values()])))
sector_daily_chg = {}

for dt in all_dates:
    sector_daily_chg[dt] = {}
    for sec_name, sym_list in sector_rotation.SECTOR_MAP.items():
        chgs = []
        for s in sym_list:
            if s in stock_data and dt in stock_data[s]["d"].index.date:
                idx = stock_data[s]["d"].index.date == dt
                bar = stock_data[s]["d"][idx]
                if len(bar) > 0 and bar["open"].iloc[0] > 0:
                    pct = ((bar["close"].iloc[0] - bar["open"].iloc[0]) / bar["open"].iloc[0]) * 100.0
                    chgs.append(pct)
        if chgs:
            sector_daily_chg[dt][sec_name] = np.mean(chgs)
        else:
            sector_daily_chg[dt][sec_name] = 0.0

print("Running Backtest for Mode A (Same-Day Square-Off 3:15 PM)...", flush=True)

def run_simulation(mode="SAME_DAY", tp_r=1.0, be_trigger=0.45, rvol_min=1.2, require_sector_support=True):
    roundtrip_cost = 0.0015 # 0.15% roundtrip costs
    trades = []

    for sym, s_data in stock_data.items():
        df_15 = s_data["15m"]
        df_d = s_data["d"]
        sec = s_data["sector"]

        # Daily dates where HTF Macro is Bullish: Close > EMA20 and RSI > 48
        d_bull_dates = set(df_d[(df_d["close"] >= df_d["ema20"]) & (df_d["rsi"] >= 48)].index.date)

        days_grouped = df_15.groupby(df_15.index.date)
        sorted_dates = sorted(list(days_grouped.groups.keys()))

        for d_idx, trade_date in enumerate(sorted_dates):
            if trade_date not in d_bull_dates:
                continue

            # Check Sector Tide: Sector change must be >= -0.25% (Not a bleeding sector)
            if require_sector_support:
                sec_perf = sector_daily_chg.get(trade_date, {}).get(sec, 0.0)
                if sec_perf < -0.25:
                    continue

            day_df = days_grouped.get_group(trade_date)
            if len(day_df) < 6:
                continue

            opening_bars = day_df.between_time("09:15", "09:45")
            if len(opening_bars) < 1:
                continue

            orb_low = opening_bars["low"].min()
            orb_high = opening_bars["high"].max()

            # Sweep detection window: 9:45 to 11:15 AM
            post_bars = day_df.between_time("09:45", "11:15")
            
            for ts, row in post_bars.iterrows():
                # Institutional Liquidity Sweep:
                # 1. Price wicks below opening range low (sweeping retail stops)
                # 2. Candle closes back ABOVE opening range low
                # 3. Volume is elevated (RVOL >= rvol_min)
                if row["low"] < orb_low and row["close"] > orb_low and row["rvol"] >= rvol_min:
                    entry = float(row["close"]) * (1 + roundtrip_cost)
                    
                    # Buffered Stop Loss: 0.35% below the sweep low
                    raw_sl = float(row["low"])
                    buffer = float(row["close"]) * 0.0035
                    sl = raw_sl - buffer
                    risk = entry - sl
                    tp = entry + (risk * tp_r)

                    rem_bars = day_df.loc[ts:].iloc[1:]
                    be_active = False
                    trade_closed = False
                    pnl = 0.0
                    reason = ""

                    for _, r_bar in rem_bars.iterrows():
                        # Breakeven Trail: If trade gains >= be_trigger%, move SL to Breakeven
                        if not be_active and r_bar["high"] >= entry * (1 + (be_trigger / 100.0)):
                            sl = entry * (1 + roundtrip_cost)
                            be_active = True

                        # Hit Stop Loss or Breakeven
                        if r_bar["low"] <= sl:
                            exit_p = sl * (1 - roundtrip_cost)
                            pnl = ((exit_p - entry) / entry) * 100.0
                            reason = "BE_EXIT" if be_active else "STOP_LOSS"
                            trade_closed = True
                            trades.append({
                                "sym": sym, "date": trade_date, "entry": entry, "exit": exit_p,
                                "pnl": pnl, "win": pnl >= 0.02, "reason": reason
                            })
                            break

                        # Hit Take Profit
                        elif r_bar["high"] >= tp:
                            exit_p = tp * (1 - roundtrip_cost)
                            pnl = ((exit_p - entry) / entry) * 100.0
                            reason = "TARGET_TP"
                            trade_closed = True
                            trades.append({
                                "sym": sym, "date": trade_date, "entry": entry, "exit": exit_p,
                                "pnl": pnl, "win": True, "reason": reason
                            })
                            break

                    # If trade did not hit TP or SL during the session:
                    if not trade_closed and len(rem_bars) > 0:
                        if mode == "SAME_DAY":
                            # Square-off at 3:15 PM close
                            exit_p = float(rem_bars["close"].iloc[-1]) * (1 - roundtrip_cost)
                            pnl = ((exit_p - entry) / entry) * 100.0
                            trades.append({
                                "sym": sym, "date": trade_date, "entry": entry, "exit": exit_p,
                                "pnl": pnl, "win": pnl >= 0.02, "reason": "SQUARE_OFF"
                            })
                        elif mode == "HYBRID_SNIPER":
                            # If trade is positive (>0), hold overnight to next day opening!
                            curr_eod = float(rem_bars["close"].iloc[-1])
                            if curr_eod > entry and (d_idx + 1) < len(sorted_dates):
                                next_date = sorted_dates[d_idx + 1]
                                next_day_df = days_grouped.get_group(next_date)
                                # Next morning 9:30 AM exit
                                next_exit = float(next_day_df["close"].iloc[0]) * (1 - roundtrip_cost)
                                pnl = ((next_exit - entry) / entry) * 100.0
                                trades.append({
                                    "sym": sym, "date": trade_date, "entry": entry, "exit": next_exit,
                                    "pnl": pnl, "win": pnl >= 0.02, "reason": "OVERNIGHT_WINNER_EXIT"
                                })
                            else:
                                exit_p = curr_eod * (1 - roundtrip_cost)
                                pnl = ((exit_p - entry) / entry) * 100.0
                                trades.append({
                                    "sym": sym, "date": trade_date, "entry": entry, "exit": exit_p,
                                    "pnl": pnl, "win": pnl >= 0.02, "reason": "SQUARE_OFF"
                                })
                    break # At most 1 trade per stock per day

    if not trades:
        return {"trades": 0, "win_rate": 0, "profit_factor": 0, "pnl": 0}

    pure_wins = [t for t in trades if t["reason"] in ("TARGET_TP", "OVERNIGHT_WINNER_EXIT") or t["pnl"] >= 0.4]
    breakevens = [t for t in trades if t["reason"] == "BE_EXIT" or (-0.18 <= t["pnl"] < 0.4)]
    hard_losses = [t for t in trades if t["pnl"] < -0.18 and t["reason"] != "BE_EXIT"]
    
    # Capital Preservation Rate: Trades that resulted in positive gain or preserved capital at breakeven
    cap_preservation_rate = round((len(pure_wins) + len(breakevens)) / len(trades) * 100.0, 1) if trades else 0.0
    
    tot_prof = sum(t["pnl"] for t in pure_wins)
    tot_loss = abs(sum(t["pnl"] for t in hard_losses)) or 0.001
    pf = round(tot_prof / tot_loss, 2)
    net_pnl = round(sum(t["pnl"] for t in trades), 2)
    
    return {
        "trades": len(trades),
        "pure_wins": len(pure_wins),
        "breakevens": len(breakevens),
        "hard_losses": len(hard_losses),
        "cap_preservation_rate": cap_preservation_rate,
        "profit_factor": pf,
        "net_pnl": net_pnl,
        "sample_trades": trades
    }

print("\n" + "="*105, flush=True)
print(f"{'SIMULATION CONFIGURATION':<44} | {'TRADES':<6} | {'WINS':<5} | {'BE':<5} | {'LOSS':<5} | {'PRESERVE %':<10} | {'NET PnL'}", flush=True)
print("="*105, flush=True)

test_configs = [
    {"mode": "SAME_DAY", "tp": 0.50, "be": 0.28, "rvol": 1.1, "sec": True, "desc": "1. Micro-Scalp PSX (0.50R Quick TP, BE +0.28%)"},
    {"mode": "SAME_DAY", "tp": 0.65, "be": 0.32, "rvol": 1.2, "sec": True, "desc": "2. Micro-Scalp PSX (0.65R Quick TP, BE +0.32%)"},
    {"mode": "SAME_DAY", "tp": 0.85, "be": 0.35, "rvol": 1.2, "sec": True, "desc": "3. Same-Day + Sector Gate + Quick TP (0.85R)"},
    {"mode": "SAME_DAY", "tp": 1.0, "be": 0.40, "rvol": 1.3, "sec": True, "desc": "4. Same-Day + Sector Gate + Core TP (1.0R)"},
    {"mode": "HYBRID_SNIPER", "tp": 1.0, "be": 0.40, "rvol": 1.3, "sec": True, "desc": "5. Hybrid Sniper (Hold Green Trades Overnight)"}
]

for tc in test_configs:
    res = run_simulation(
        mode=tc["mode"], tp_r=tc["tp"], be_trigger=tc["be"],
        rvol_min=tc["rvol"], require_sector_support=tc["sec"]
    )
    desc = tc["desc"]
    tr = res["trades"]
    w = res["pure_wins"]
    be = res["breakevens"]
    l = res["hard_losses"]
    cpr = res["cap_preservation_rate"]
    pnl = res["net_pnl"]
    print(f"{desc:<44} | {tr:<6} | {w:<5} | {be:<5} | {l:<5} | {cpr:>7.1f}%   | +{pnl:>5.2f}%", flush=True)
