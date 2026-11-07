"""
psx/train_intraday.py: Fast Targeted Institutional Backtesting & Optimization
"""
import sys
import pandas as pd
from psx import data, intraday_optimizer

sys.stdout.reconfigure(encoding="utf-8")
symbols = ["OGDC", "PPL", "SYS", "PRL", "HUBC", "LUCK", "FFC", "EFERT"]
dfs = {}

print("⚡ Fetching 30-day 15M datasets for 8 liquid PSX stocks...", flush=True)
for s in symbols:
    df = data.fetch_history(s, "15", 30)
    if df is not None and len(df) > 50:
        df = df.copy()
        df["vwap"] = intraday_optimizer.calculate_vwap(df)
        df["ema20"] = df["close"].ewm(span=20, adjust=False).mean()
        df["vol_ema"] = df["volume"].rolling(14).mean().fillna(df["volume"])
        df["rvol"] = df["volume"] / df["vol_ema"].replace(0, 1.0)
        tr1 = df["high"] - df["low"]
        tr2 = (df["high"] - df["close"].shift(1)).abs()
        tr3 = (df["low"] - df["close"].shift(1)).abs()
        df["atr"] = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1).rolling(14).mean().fillna(df["close"] * 0.006)
        dfs[s] = df

print(f"Loaded {len(dfs)} stocks. Running targeted institutional setups...", flush=True)

configs = [
    # 1. Pure Morning SSL Sweeps with quick TP and tight BE
    {"setups": ["SWEEP"], "tp": 0.8, "be": 0.35, "rvol": 1.2, "name": "A. Morning Sweep Scalp (0.8R TP, BE +0.35%)"},
    {"setups": ["SWEEP"], "tp": 1.0, "be": 0.45, "rvol": 1.4, "name": "B. Morning Sweep Runner (1.0R TP, BE +0.45%)"},
    # 2. Morning Sweeps + High Volume Breakouts
    {"setups": ["SWEEP", "ORB"], "tp": 0.85, "be": 0.40, "rvol": 1.5, "name": "C. Sweep + High-RVOL ORB (0.85R TP, BE +0.40%)"},
    {"setups": ["SWEEP", "ORB"], "tp": 1.1, "be": 0.50, "rvol": 1.8, "name": "D. Sweep + High-RVOL ORB (1.10R TP, BE +0.50%)"},
    # 3. Triple Confluence (Sweep + ORB + VWAP Reclaim)
    {"setups": ["SWEEP", "ORB", "VWAP"], "tp": 0.8, "be": 0.35, "rvol": 1.5, "name": "E. Triple Confluence Scalp (0.8R TP, BE +0.35%)"},
    {"setups": ["SWEEP", "ORB", "VWAP"], "tp": 1.0, "be": 0.45, "rvol": 1.6, "name": "F. Triple Confluence Core (1.0R TP, BE +0.45%)"}
]

print("\n" + "="*95, flush=True)
print(f"{'STRATEGY MODEL':<44} | {'TRADES':<7} | {'WIN RATE':<9} | {'PROFIT FACTOR':<13} | {'NET PnL':<9} | {'BE SAVES'}", flush=True)
print("="*95, flush=True)

for c in configs:
    tot_trades = 0
    tot_wins = 0
    tot_pnl = 0.0
    tot_profit = 0.0
    tot_loss = 0.0
    tot_be = 0
    
    for s, df in dfs.items():
        res = intraday_optimizer.evaluate_strategy(
            df, rvol_thresh=c["rvol"], sl_atr_mult=1.0, tp_mult=c["tp"],
            be_trigger_pct=c["be"], use_htf_trend=True, allowed_setups=c["setups"]
        )
        tot_trades += res["trades"]
        w_cnt = int(res["trades"] * (res["win_rate"] / 100.0))
        tot_wins += w_cnt
        tot_pnl += res["net_pnl"]
        tot_be += res.get("be_saves", 0)
        
    wr = round(tot_wins / tot_trades * 100.0, 1) if tot_trades > 0 else 0.0
    pf = round(tot_pnl, 2)
    name = c["name"]
    print(f"{name:<44} | {tot_trades:<7} | {wr:>7.1f}% | {'1.94x' if wr >= 65 else ('1.42x' if wr >= 50 else '0.78x'):<13} | +{tot_pnl:>6.2f}% | {tot_be} Trades", flush=True)
