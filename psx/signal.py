"""Ek jagah jahan 'signal' banta hai. Live analyzer, backtest aur journal teeno yehi use karte hain."""
import numpy as np

import config
from .indicators import add_indicators
from .smc import analyze_smc
from . import scoring


def gates(df, price: float, ldcp: float) -> dict:
    change_pct = round((price - ldcp) / ldcp * 100, 2) if ldcp else 0.0
    peak5 = float(df["high"].tail(5).max())
    dump = round((peak5 - price) / peak5 * 100, 1) if peak5 else 0.0
    avg_vol = float(df["volume"].tail(20).mean()) if len(df) else 0.0
    edge = config.CIRCUIT_PCT - 0.5
    return {
        "change_pct": change_pct, "dump_from_peak_pct": dump, "avg_volume": round(avg_vol),
        "crash": change_pct <= -edge or (dump >= 20 and change_pct <= -6),
        "upper_lock": change_pct >= edge,
        "low_liquidity": avg_vol < config.MIN_AVG_VOLUME,
    }


def evaluate(df_done, price: float | None = None, ldcp: float | None = None, mtf_alignment=None,
             pb=None, eps=None, micro_bearish=False, regime=None) -> dict:
    """df_done = COMPLETED daily candles (adhoori aaj ki candle nahi)."""
    price = float(price if price else df_done["close"].iloc[-1])
    if ldcp is None:
        ldcp = float(df_done["close"].iloc[-2]) if len(df_done) > 1 else price
    d = add_indicators(df_done)
    smc = analyze_smc(df_done, price)
    g = gates(df_done, price, ldcp)

    factors = scoring.compute_factors(d, smc, price, mtf_alignment, pb, eps, regime)
    score = scoring.total_score(factors)
    d_status = "BULLISH" if factors["trend"] > 0.5 else "BEARISH" if factors["trend"] < -0.5 else "MIXED"
    mtf_conflict = mtf_alignment is not None and np.sign(mtf_alignment) * np.sign(score) < 0 and abs(mtf_alignment) > 0.2
    conf = scoring.confidence(factors, score, len(df_done), g["low_liquidity"], mtf_conflict)

    verdict, mode = scoring.decide(score, smc, d_status, micro_bearish)
    note = None
    if g["crash"]:
        verdict, mode = "🚨 AVOID / DO NOT BUY (Violent Free-Fall / Lower Circuit)", "none"
    elif g["upper_lock"]:
        verdict, mode = "🟡 UPPER CIRCUIT LOCK (Chase mat karein — wait)", "none"

    levels = scoring.build_levels(d, smc, price, mode if mode != "none" else "trend")
    if mode != "none":
        if levels["rr"] < config.MIN_RR:
            verdict, mode, note = "🟡 GOOD SETUP BUT R:R POOR (Wait for better entry)", "none", f"R:R sirf 1:{levels['rr']}"
        elif conf < config.MIN_CONFIDENCE:
            verdict, mode, note = "🟡 LOW-CONFIDENCE SETUP (Wait)", "none", f"Confidence {conf}% < {config.MIN_CONFIDENCE}%"

    if g["crash"] or score <= -25:
        action = "AVOID"
    elif mode in ("trend", "ote"):
        action = "BUY"
    elif mode == "pullback":
        action = "WATCH"
    else:
        action = "WAIT"
    return {"d": d, "smc": smc, "gates": g, "factors": factors, "score": score, "confidence": conf,
            "verdict": verdict, "mode": mode, "action": action, "levels": levels, "d_status": d_status,
            "price": round(price, 2), "ldcp": ldcp, "note": note}
