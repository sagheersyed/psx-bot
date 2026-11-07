"""Multi-timeframe analysis — weighted alignment (1D ka wazan 1M se 7x)."""
from concurrent.futures import ThreadPoolExecutor

import numpy as np

import config
from . import data
from .indicators import ema, rsi


def _sgn(x):
    x = float(x)
    return 1.0 if x > 0 else -1.0 if x < 0 else 0.0


def analyze_timeframe(tf: dict, symbol: str, df=None) -> dict:
    base = {"tf": tf["name"], "label": tf["label"], "weight": tf["weight"], "df": None,
            "status": "NO_DATA", "badge": "⚪ NO DATA", "close": 0.0, "rsi": 50.0,
            "ema9": 0.0, "ema20": 0.0, "trend_desc": "Data available nahi", "score": 0.0}
    if df is None:
        df = data.fetch_history(symbol, tf["res"], tf["days"])
    min_len = 2 if tf["name"] == "1Y" else (4 if tf["name"] in ("1MO", "1W") else 8)
    if df is None or len(df) < min_len:
        return base

    c = df["close"]
    if tf["name"] == "1Y" and len(df) < 9:
        close = float(c.iloc[-1])
        prev_yr = float(c.iloc[-2]) if len(df) > 1 else close
        op = float(df["open"].iloc[-1])
        s = 0.5 * _sgn(close - prev_yr) + 0.5 * _sgn(close - op)
        v9, v20 = prev_yr, op
        vr = 65.0 if s > 0 else (35.0 if s < 0 else 50.0)
        desc = f"Annual Macro Trend {'BULLISH (Higher than 2025)' if s > 0 else 'BEARISH'}"
    else:
        e9, e20, r = ema(c, 9), ema(c, 20), rsi(c)
        close, v9, v20, vr = float(c.iloc[-1]), float(e9.iloc[-1]), float(e20.iloc[-1]), float(r.iloc[-1])
        # continuous score in [-1, 1]
        s = (0.4 * _sgn(close - v20) + 0.2 * _sgn(v9 - v20) + 0.2 * _sgn(close - v9)
             + 0.2 * float(np.clip((vr - 50) / 20, -1, 1)))
        desc = f"Above 9 & 20 EMA (RSI {vr:.0f})" if s >= 0.5 else (f"Below 9 & 20 EMA (RSI {vr:.0f})" if s <= -0.5 else (f"Testing 20 EMA support (RSI {vr:.0f})" if close > v20 else f"Consolidating near EMAs (RSI {vr:.0f})"))

    if s >= 0.5:
        status, badge = "BULLISH", "🟢 BULLISH"
    elif s <= -0.5:
        status, badge = "BEARISH", "🔴 BEARISH"
    elif close > v20:
        status, badge = "PULLBACK_SUPPORT", "🟡 PULLBACK"
    else:
        status, badge = "CONSOLIDATING", "🟡 NEUTRAL"
    base.update(status=status, badge=badge, close=round(close, 2), rsi=round(vr, 1), ema9=round(v9, 2),
                ema20=round(v20, 2), trend_desc=desc, score=round(float(s), 3), df=df)
    return base


def run_all(symbol: str) -> dict:
    out = {}
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = {tf["name"]: ex.submit(analyze_timeframe, tf, symbol) for tf in config.TIMEFRAMES}
        for name, f in futs.items():
            try:
                out[name] = f.result()
            except Exception:
                out[name] = None
    return out


def weighted_alignment(results: dict) -> tuple[float, int, int]:
    """(-1..+1 alignment, #bullish, #bearish). NO_DATA timeframes ignore hoti hain."""
    tot_w = tot = 0.0
    bull = bear = 0
    for tf in config.TIMEFRAMES:
        r = results.get(tf["name"])
        if not r or r["status"] == "NO_DATA":
            continue
        tot_w += tf["weight"]
        tot += tf["weight"] * r["score"]
        bull += r["status"] == "BULLISH"
        bear += r["status"] == "BEARISH"
    return (tot / tot_w if tot_w else 0.0), bull, bear
