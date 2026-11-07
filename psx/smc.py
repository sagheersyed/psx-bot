"""Smart Money Concepts engine (fractals, FVG, OB, sweeps, structure, OTE).

Fixes vs. purani smc_engine.py:
  * OTE fib ab sahi 'leg' (swing low -> uske baad wala swing high) par lagta hai
  * volume ratio aakhri 3 bars / 20-bar average (adhoora intraday candle nahi)
  * order-block 'expansion' ab rolling average body se (look-ahead nahi)
  * FVG/OB mitigation vectorised (O(n))
  * Liquidity sweeps (BSL/SSL) — dashboard isi ko expect karta tha
"""
import numpy as np
import pandas as pd


def find_swings(df: pd.DataFrame, window: int = 2):
    h, l, n = df["high"].values, df["low"].values, len(df)
    shs, sls = [], []
    for i in range(window, n - window):
        if all(h[i] > h[i - w] and h[i] >= h[i + w] for w in range(1, window + 1)):
            shs.append({"index": i, "time": str(df.index[i]), "price": round(float(h[i]), 2)})
        if all(l[i] < l[i - w] and l[i] <= l[i + w] for w in range(1, window + 1)):
            sls.append({"index": i, "time": str(df.index[i]), "price": round(float(l[i]), 2)})
    return shs, sls


def detect_fvgs(df: pd.DataFrame, min_gap_pct: float = 0.003):
    h, l = df["high"].values, df["low"].values
    n = len(df)
    suf_min_low = np.minimum.accumulate(l[::-1])[::-1]
    suf_max_high = np.maximum.accumulate(h[::-1])[::-1]
    out = []
    for i in range(2, n):
        if l[i] > h[i - 2] and (l[i] - h[i - 2]) / h[i - 2] >= min_gap_pct:
            bottom, top = h[i - 2], l[i]
            if not (i + 1 < n and suf_min_low[i + 1] <= bottom):
                out.append({"type": "BULLISH_FVG", "bottom": round(float(bottom), 2), "top": round(float(top), 2),
                            "midpoint": round(float((top + bottom) / 2), 2), "time": str(df.index[i - 1])})
        elif l[i - 2] > h[i] and (l[i - 2] - h[i]) / l[i - 2] >= min_gap_pct:
            top, bottom = l[i - 2], h[i]
            if not (i + 1 < n and suf_max_high[i + 1] >= top):
                out.append({"type": "BEARISH_FVG", "bottom": round(float(bottom), 2), "top": round(float(top), 2),
                            "midpoint": round(float((top + bottom) / 2), 2), "time": str(df.index[i - 1])})
    return out


def detect_order_blocks(df: pd.DataFrame, k: float = 1.2):
    o, c, h, l = (df[x].values for x in ("open", "close", "high", "low"))
    n = len(df)
    body = pd.Series(np.abs(c - o)).rolling(20, min_periods=5).mean().shift(1).bfill().values
    suf_min_low = np.minimum.accumulate(l[::-1])[::-1]
    suf_max_high = np.maximum.accumulate(h[::-1])[::-1]
    out = []
    for i in range(1, n - 1):
        up_move, dn_move = c[i + 1] - o[i + 1], o[i + 1] - c[i + 1]
        if c[i] < o[i] and up_move > k * body[i + 1] and c[i + 1] > h[i]:
            if not (i + 2 < n and suf_min_low[i + 2] < l[i]):
                out.append({"type": "BULLISH_OB", "top": round(float(h[i]), 2), "bottom": round(float(l[i]), 2),
                            "mid": round(float((h[i] + l[i]) / 2), 2), "time": str(df.index[i])})
        elif c[i] > o[i] and dn_move > k * body[i + 1] and c[i + 1] < l[i]:
            if not (i + 2 < n and suf_max_high[i + 2] > h[i]):
                out.append({"type": "BEARISH_OB", "top": round(float(h[i]), 2), "bottom": round(float(l[i]), 2),
                            "mid": round(float((h[i] + l[i]) / 2), 2), "time": str(df.index[i])})
    return out


def detect_sweeps(df, shs, sls, lookback: int = 10):
    h, l, c, n = df["high"].values, df["low"].values, df["close"].values, len(df)
    out, seen = [], set()
    for k in range(max(0, n - lookback), n):
        bars_ago = (n - 1) - k
        for s in shs[-3:]:
            if s["index"] < k and h[k] > s["price"] and c[k] < s["price"] and ("B", s["price"]) not in seen:
                seen.add(("B", s["price"]))
                out.append({"type": "BSL_SWEEP", "level": s["price"], "time": str(df.index[k]), "bias": "BEARISH", "bars_ago": bars_ago})
        for s in sls[-3:]:
            if s["index"] < k and l[k] < s["price"] and c[k] > s["price"] and ("S", s["price"]) not in seen:
                seen.add(("S", s["price"]))
                out.append({"type": "SSL_SWEEP", "level": s["price"], "time": str(df.index[k]), "bias": "BULLISH", "bars_ago": bars_ago})
    return out


def active_leg(shs, sls):
    """Aakhri bullish impulse leg: (swing low) -> (uske baad wala swing high)."""
    if not shs or not sls:
        return None
    sh = shs[-1]
    lows_before = [s for s in sls if s["index"] < sh["index"]]
    if not lows_before:
        return None
    return {"low": lows_before[-1]["price"], "high": sh["price"], "low_idx": lows_before[-1]["index"], "high_idx": sh["index"]}


def ote_levels(price, leg, obs, fvgs):
    if not leg or leg["high"] <= leg["low"]:
        return None
    hi, lo = leg["high"], leg["low"]
    diff = hi - lo
    fib = {k: round(hi - r * diff, 2) for k, r in (("fib_50", .5), ("fib_62", .618), ("fib_705", .705), ("fib_79", .786))}
    leg_valid = price >= lo
    bull_obs = [o for o in obs if o["type"] == "BULLISH_OB" and o["top"] <= fib["fib_50"]]
    bull_fvgs = [f for f in fvgs if f["type"] == "BULLISH_FVG" and f["top"] <= fib["fib_50"]]
    return {
        "ote_range": f"Rs. {fib['fib_79']} - {fib['fib_62']}", **fib,
        "leg_low": lo, "leg_high": hi, "leg_valid": leg_valid,
        "in_ote_zone": leg_valid and fib["fib_79"] <= price <= fib["fib_62"],
        "in_discount": leg_valid and price < fib["fib_50"],
        "position_pct": round((price - lo) / diff * 100, 1),
        "active_ob": bull_obs[-1] if bull_obs else None,
        "active_fvg": bull_fvgs[-1] if bull_fvgs else None,
    }


def analyze_smc(df: pd.DataFrame, price: float | None = None) -> dict:
    """df = COMPLETED daily candles. price = live price (optional)."""
    price = round(float(price if price else df["close"].iloc[-1]), 2)
    shs, sls = find_swings(df, 2)
    last_sh = shs[-1]["price"] if shs else float(df["high"].max())
    last_sl = sls[-1]["price"] if sls else float(df["low"].min())
    fvgs, obs = detect_fvgs(df), detect_order_blocks(df)
    sweeps = detect_sweeps(df, shs, sls)
    leg = active_leg(shs, sls)
    ote = ote_levels(price, leg, obs, fvgs)

    vols = df["volume"].values
    avg20 = float(np.mean(vols[-20:])) if len(vols) else 0.0
    rec3 = float(np.mean(vols[-3:])) if len(vols) else 0.0
    vol_ratio = round(rec3 / avg20, 2) if avg20 > 0 else 1.0
    dryup, climax = vol_ratio < 0.65, vol_ratio > 1.8

    # --- structure ---
    trend = "RANGE"
    if len(shs) >= 2 and len(sls) >= 2:
        hh, hl = shs[-1]["price"] > shs[-2]["price"], sls[-1]["price"] > sls[-2]["price"]
        lh, ll = shs[-1]["price"] < shs[-2]["price"], sls[-1]["price"] < sls[-2]["price"]
        trend = "BULL" if (hh and hl) else "BEAR" if (lh and ll) else "RANGE"
    events = []
    if len(shs) < 2 or len(sls) < 2:
        structure = "CONSOLIDATION"
    elif price > last_sh:
        structure = "BULLISH_BOS" if trend == "BULL" else "BULLISH_CHOCH"
        events.append(f"🟢 {'BOS' if trend == 'BULL' else 'CHoCH'}: price swing high Rs. {last_sh} ke upar")
    elif price < last_sl:
        structure = "BEARISH_BOS" if trend == "BEAR" else "BEARISH_CHOCH"
        events.append(f"🔴 {'BOS' if trend == 'BEAR' else 'CHoCH'}: price swing low Rs. {last_sl} ke neeche")
    elif trend == "BULL":
        structure = "BULLISH_STRUCTURE"
        events.append("🟢 Higher Highs & Higher Lows")
    elif trend == "BEAR":
        structure = "BEARISH_STRUCTURE"
        events.append("🔴 Lower Highs & Lower Lows")
    else:
        structure = "RANGE_BOUND"
        events.append("🟡 Range / Accumulation")
    for s in sweeps:
        events.append(f"{'🟢' if s['bias'] == 'BULLISH' else '🔴'} {s['type']} @ Rs. {s['level']}")

    # --- bias & narrative ---
    ob_ok = structure not in ("BEARISH_BOS", "BEARISH_CHOCH")
    if ote and ote["in_ote_zone"] and dryup and ob_ok:
        bias = "🟢 OTE DISCOUNT ACCUMULATION (Smart Money Absorption Zone)"
        summary = (f"Price OTE discount zone ({ote['ote_range']}) mein hai aur pullback volume {(1 - vol_ratio) * 100:.0f}% "
                   f"dry-up hai (sellers thak chuke). High-probability long POI — structure low toot'ne par setup invalid.")
    elif structure in ("BEARISH_BOS", "BEARISH_CHOCH"):
        bias = "🚨 BEARISH BREAKDOWN (Smart Money Exiting)"
        summary = "Structure neeche toot chuka hai. Naya long tab tak nahi jab tak price swing low wapas reclaim na kare."
    elif ote and ote["in_discount"] and trend == "BEAR":
        bias = "🟡 DISCOUNT BUT DOWNTREND (Falling-knife risk)"
        summary = "Price discount mein hai lekin structure Lower Highs/Lows hai. Bounce ke liye pehle structure reclaim ka intezar karein."
    elif ote and ote["in_discount"]:
        bias = "🟢 DISCOUNT PRICING (below 50% equilibrium)"
        summary = f"Price equilibrium (Rs. {ote['fib_50']}) se neeche discount zone mein hai; volume confirmation ka intezar behtar."
    elif structure in ("BULLISH_BOS", "BULLISH_CHOCH"):
        bias = "🟢 BULLISH EXPANSION (Breakout)"
        summary = "Swing high ke upar close hua. Entry retest par (OB/FVG) behtar hai, breakout chase karna risky."
    elif structure == "BEARISH_STRUCTURE":
        bias = "🔴 BEARISH STRUCTURE (Lower Highs & Lows)"
        summary = "Order flow bearish hai; har rally par overhead supply expect karein."
    else:
        bias = "🟡 RANGE CONSOLIDATION (Waiting for Liquidity Sweep)"
        summary = "Price range mein hai; breakout se pehle liquidity sweep aam hai."

    return {
        "structure": structure, "trend": trend, "smc_bias": bias, "smc_summary": summary,
        "last_swing_high": last_sh, "last_swing_low": last_sl,
        "swing_highs": [s["price"] for s in shs[-6:]], "swing_lows": [s["price"] for s in sls[-6:]],
        "ote_poi": ote, "order_blocks": obs[-4:], "active_fvgs": fvgs[-4:],
        "all_obs": obs, "liquidity_sweeps": sweeps,
        "vol_ratio": vol_ratio, "is_volume_dryup": dryup, "is_climax_volume": climax, "events": events,
    }
