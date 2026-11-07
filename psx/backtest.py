"""Backtest + trade simulator. Maqsad: pata chalna ke signal historically kaam karta hai ya nahi."""
import numpy as np
import pandas as pd

import config
from .signal import evaluate


def simulate_trade(fut: pd.DataFrame, entry_high: float, stop: float, t1: float,
                   fill_bars: int = 3, hold_days: int = config.HOLD_DAYS) -> dict:
    """Limit order entry_high par; stop pehle (conservative) agar ek hi din dono hit hon."""
    fill = fill_i = None
    for i, (_, b) in enumerate(fut.iterrows()):
        o, h, l, c = float(b["open"]), float(b["high"]), float(b["low"]), float(b["close"])
        if fill is None:
            if i >= fill_bars:
                return {"result": "NO_FILL", "r": 0.0, "bars": i}
            if l > entry_high:
                continue
            fill, fill_i = min(o, entry_high), i
            if fill - stop <= 0:
                return {"result": "NO_FILL", "r": 0.0, "bars": i + 1}
        risk = fill - stop
        if i > fill_i and o <= stop:                       # gap-down through stop
            return {"result": "STOP", "r": round((o - fill) / risk, 2), "bars": i + 1, "fill": fill}
        if l <= stop:
            return {"result": "STOP", "r": round((stop - fill) / risk, 2), "bars": i + 1, "fill": fill}
        if h >= t1:
            return {"result": "T1", "r": round((t1 - fill) / risk, 2), "bars": i + 1, "fill": fill}
        if i - fill_i + 1 >= hold_days:
            return {"result": "TIMEOUT", "r": round((c - fill) / risk, 2), "bars": i + 1, "fill": fill}
    if fill is None:
        return {"result": "NO_FILL" if len(fut) >= fill_bars else "PENDING", "r": 0.0, "bars": len(fut)}
    return {"result": "PENDING", "r": 0.0, "bars": len(fut), "fill": fill}


def run_backtest(df: pd.DataFrame, min_bars: int = 120, hold_days: int = config.HOLD_DAYS) -> list[dict]:
    trades, i, n = [], min_bars, len(df)
    while i < n - 2:
        sl = df.iloc[: i + 1]
        sig = evaluate(sl, price=float(sl["close"].iloc[-1]), ldcp=float(sl["close"].iloc[-2]))
        if sig["action"] in ("BUY", "WATCH"):
            lv, fill_bars = sig["levels"], (3 if sig["mode"] != "pullback" else 5)
            fut = df.iloc[i + 1: i + 1 + fill_bars + hold_days]
            res = simulate_trade(fut, lv["entry_high"], lv["stop"], lv["t1"], fill_bars, hold_days)
            if res["result"] == "PENDING":
                break
            if res["result"] != "NO_FILL":
                trades.append({"date": str(df.index[i].date()), "mode": sig["mode"], "score": sig["score"],
                               "confidence": sig["confidence"], **res})
            i += max(1, res["bars"])
        else:
            i += 1
    return trades


def summarize(trades: list[dict]) -> dict:
    if not trades:
        return {"n": 0, "win_rate": None, "avg_r": None, "profit_factor": None, "expectancy": None}
    r = np.array([t["r"] for t in trades])
    wins, losses = r[r > 0], r[r < 0]
    pf = float(wins.sum() / abs(losses.sum())) if len(losses) and losses.sum() != 0 else None
    return {"n": len(r), "win_rate": round(float((r > 0).mean() * 100), 1), "avg_r": round(float(r.mean()), 2),
            "expectancy": round(float(r.mean()), 2), "profit_factor": round(pf, 2) if pf else None,
            "t1_hits": sum(t["result"] == "T1" for t in trades), "stops": sum(t["result"] == "STOP" for t in trades),
            "timeouts": sum(t["result"] == "TIMEOUT" for t in trades)}


def by_bucket(trades: list[dict]) -> dict:
    buckets = {"score 25-50": [t for t in trades if 25 <= t["score"] < 50],
               "score 50+": [t for t in trades if t["score"] >= 50],
               "ote": [t for t in trades if t["mode"] == "ote"],
               "pullback": [t for t in trades if t["mode"] == "pullback"]}
    return {k: summarize(v) for k, v in buckets.items()}
