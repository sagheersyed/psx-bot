"""Scoring engine — har factor [-1,+1], wazan se multiply, total score [-100,+100].

Purani if/elif cascade ki jagah ek hi score banta hai jo:
  * kuch bhi 'first match wins' nahi karta (har factor vote deta hai)
  * confidence nikalta hai (factors kitne agree karte hain, data kitna acha hai)
  * backtest ho sakta hai (backtest.py wahi function use karta hai)
"""
import numpy as np

import config

WEIGHTS = {"trend": 25, "momentum": 15, "flow": 15, "structure": 20, "location": 10, "mtf": 10, "valuation": 5,
           "regime": 15}   # regime = beta-weighted KSE-100/sector trend (psx/regime.py); None ho to skip

STRUCT_VALUE = {
    "BULLISH_BOS": 0.8, "BULLISH_CHOCH": 0.6, "BULLISH_STRUCTURE": 0.6, "RANGE_BOUND": 0.0, "CONSOLIDATION": 0.0,
    "BEARISH_STRUCTURE": -0.6, "BEARISH_BOS": -0.9, "BEARISH_CHOCH": -1.0,
}


def _clip(x, a=-1.0, b=1.0):
    return float(max(a, min(b, x)))


def _sgn(x):
    x = float(x)
    return 1.0 if x > 0 else -1.0 if x < 0 else 0.0


def compute_factors(d, smc: dict, price: float, mtf_alignment=None, pb=None, eps=None, regime=None) -> dict:
    """d = add_indicators(completed daily df). mtf_alignment / pb None ho to factor skip hota hai."""
    last, prev5 = d.iloc[-1], d.iloc[-6] if len(d) > 6 else d.iloc[0]
    atr = float(last["atr"]) or price * 0.02
    f = {}

    parts = [_sgn(price - last["ema20"]), _sgn(price - last["ema50"]), _sgn(last["ema20"] - last["ema50"]),
             _clip((last["ema20"] - prev5["ema20"]) / atr)]
    if len(d) >= 200:
        parts.append(_sgn(price - last["ema200"]))
    f["trend"] = float(np.mean(parts))

    r = float(last["rsi"])
    rsi_v = -0.2 if r > 75 else -0.3 if r < 25 else _clip((r - 50) / 20)   # overextended (>75) = chase mat karo
    h, hp = float(last["macd_hist"]), float(d["macd_hist"].iloc[-2]) if len(d) > 1 else 0.0
    f["momentum"] = 0.6 * rsi_v + 0.4 * (0.5 * _sgn(h) + 0.5 * _sgn(h - hp))

    # Upthrust / Climactic blow-off check (ICT Distribution Framework)
    bar_range = max(0.01, float(last["high"] - last["low"]))
    upper_wick = float(last["high"] - max(last["open"], last["close"]))
    if (upper_wick / bar_range > 0.45) and (smc.get("vol_ratio", 1.0) > 1.5):
        f["momentum"] = _clip(f["momentum"] - 0.4)

    f["flow"] = 0.6 * _clip(float(last["cmf20"]) / 0.15) + 0.4 * _sgn(last["obv"] - last["obv_ema"])

    sv = STRUCT_VALUE.get(smc["structure"], 0.0)
    for s in smc.get("liquidity_sweeps", []):
        sv += 0.3 if s["bias"] == "BULLISH" else -0.3
    f["structure"] = _clip(sv)

    ote, loc = smc.get("ote_poi"), 0.0
    if ote and ote["leg_valid"]:
        pos = ote["position_pct"] / 100
        loc = _clip(1 - 2 * pos) if pos <= 1 else -0.2          # discount = +, premium/extended = -
        if ote["in_ote_zone"] and smc["is_volume_dryup"]:
            loc = 1.0
    f["location"] = loc

    if mtf_alignment is not None:
        f["mtf"] = _clip(mtf_alignment)
    if pb is not None or eps is not None:
        v = 0.0
        if pb:
            v += 0.6 if pb < 0.9 else 0.0 if pb <= 1.5 else -0.2 if pb <= 2.5 else -0.4
        if eps is not None and eps < 0:
            v -= 0.5
        f["valuation"] = _clip(v)
    if regime is not None:
        f["regime"] = _clip(regime)
    return f


def total_score(factors: dict) -> float:
    """Baqi factors ka normalised average; 'regime' alag se ADD hota hai (max +-WEIGHTS['regime'] points),
    taake index se azad stock (regime ~ 0) ka score bilkul na badle - sirf index-linked stocks par asar."""
    base = {k: v for k, v in factors.items() if k != "regime"}
    w = sum(WEIGHTS[k] for k in base)
    score = 100 * sum(WEIGHTS[k] * v for k, v in base.items()) / w if w else 0.0
    score += WEIGHTS["regime"] * factors.get("regime", 0.0)
    return round(_clip(score, -100.0, 100.0), 1)


def confidence(factors: dict, score: float, n_bars: int, low_liquidity=False, mtf_conflict=False) -> int:
    """0-100. Probability NAHI hai — 'signal kitna mazboot aur saaf hai' ka andaza."""
    sg = _sgn(score)
    if sg == 0:
        return 20
    core = {k: v for k, v in factors.items() if k != "regime"}   # regime score mein hai, agreement mein nahi
    w_tot = sum(WEIGHTS[k] for k, v in core.items() if v != 0) or 1
    agree = sum(WEIGHTS[k] for k, v in core.items() if _sgn(v) == sg) / w_tot
    strength = min(1.0, abs(score) / 60)
    q = 1.0 if n_bars >= 200 else 0.9 if n_bars >= 100 else 0.75 if n_bars >= 60 else 0.5
    c = 100 * (0.6 * agree + 0.4 * strength) * q
    if low_liquidity:
        c *= 0.85
    if mtf_conflict:
        c *= 0.85
    return int(round(c))


# ---------------------------------------------------------------- levels
def build_levels(d, smc: dict, price: float, mode: str) -> dict:
    """mode: 'trend' (abhi entry), 'pullback' (dip ka intezar), 'ote' (discount zone entry)."""
    atr = float(d["atr"].iloc[-1]) or price * 0.02
    last = d.iloc[-1]
    sup_c = [x for x in smc["swing_lows"] if x < price * 0.998]
    sup_c += [o["bottom"] for o in smc.get("all_obs", []) if o["type"] == "BULLISH_OB" and o["top"] < price]
    sup_c += [float(last[e]) for e in ("ema20", "ema50") if last[e] < price * 0.998]
    support = max(sup_c) if sup_c else price - 1.5 * atr
    res = sorted(x for x in smc["swing_highs"] if x > price * 1.002)
    res += [o["bottom"] for o in smc.get("all_obs", []) if o["type"] == "BEARISH_OB" and o["bottom"] > price]
    res = sorted(set(round(x, 2) for x in res))

    ote = smc.get("ote_poi")
    if mode == "ote" and ote:
        lo, hi = max(ote["fib_79"], price - atr), price
        struct = min(ote["leg_low"], lo)
    elif mode == "pullback":
        lo, hi = support, min(price, support + 0.5 * atr)
        struct = support
    else:
        lo, hi = max(support, price - 0.5 * atr), price
        struct = support
    lo, hi = min(lo, hi), max(lo, hi)
    mid = (lo + hi) / 2
    stop = min(struct - 0.5 * atr, mid - 0.8 * atr)
    risk = max(mid - stop, 0.01)

    def pick(min_r, fallback_r):
        for lvl in res:
            if lvl >= mid + min_r * risk:
                return lvl
        return mid + fallback_r * risk

    t1 = pick(1.0, 1.5)
    t2 = max(pick(2.0, 2.5), t1 + 0.5 * risk)
    t3 = max(mid + 4.0 * risk, t2 + 0.5 * risk)
    rr = (t1 - mid) / risk
    return {"entry_low": round(lo, 2), "entry_high": round(hi, 2), "stop": round(stop, 2),
            "t1": round(t1, 2), "t2": round(t2, 2), "t3": round(t3, 2),
            "rr": round(rr, 2), "support": round(support, 2), "resistance": round(res[0], 2) if res else None,
            "atr": round(atr, 2), "risk": round(risk, 2),
            "breakeven_trigger": round(t1, 2),
            "management_rule": f"Jab price Rs. {round(t1, 2)} (TP1) pohnche to Stop Loss ko foran Entry (Rs. {round(mid, 2)}) par shift kar dein (Risk-Free Trade)."}


# ---------------------------------------------------------------- decision
def decide(score: float, smc: dict, d_status: str, micro_bearish: bool) -> tuple[str, str]:
    """-> (verdict, mode)   mode: trend | pullback | ote | none"""
    bearish_struct = smc["structure"] in ("BEARISH_BOS", "BEARISH_CHOCH")
    ote = smc.get("ote_poi")
    if ote and (ote["in_ote_zone"] or ote["in_discount"]) and smc["is_volume_dryup"] and not bearish_struct and score >= 10:
        return "🟢 SMC DISCOUNT ACCUMULATION (BUY zone — sellers exhausted)", "ote"
    if score >= config.SCORE_STRONG_BUY:
        return "🟢 STRONG BUY (High-Confluence Setup)", "trend"
    if score >= config.SCORE_BUY:
        if micro_bearish:
            return "🟡 PULLBACK IN UPTREND (Wait for 5M/15M trigger)", "pullback"
        return "🟢 BUY (Trend + Flow aligned)", "trend"
    if score >= 10 and d_status == "BULLISH" and micro_bearish:
        return "🟡 PULLBACK IN UPTREND (Wait for 5M/15M trigger)", "pullback"
    if score <= -50:
        return "🔴 STRONG DOWNTREND — AVOID", "none"
    if score <= -25:
        return "🔴 DOWNTREND DOMINANT (Sell on rallies, no longs)", "none"
    return "🟡 SIDEWAYS / NO CLEAR EDGE (Wait)", "none"


def explain(factors: dict, n: int = 3) -> str:
    names = {"trend": "Trend (EMAs)", "momentum": "Momentum (RSI/MACD)", "flow": "Money flow (CMF/OBV)",
             "structure": "Market structure", "location": "Price location (discount/premium)",
             "mtf": "Multi-timeframe alignment", "valuation": "Valuation",
             "regime": "Market/sector regime"}
    ranked = sorted(factors.items(), key=lambda kv: abs(WEIGHTS[kv[0]] * kv[1]), reverse=True)[:n]
    return ", ".join(f"{names[k]} {'↑' if v > 0 else '↓' if v < 0 else '→'}" for k, v in ranked if v != 0) or "koi factor nahi"
