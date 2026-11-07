"""
psx/volume_sentinel.py: Institutional Volume & Price Expansion Engine
Equipped with an Anti-Fakeout & Trap-Protection Shield.

Evaluates stocks for genuine institutional footprint:
  1. RVOL (Relative Volume vs. 20-Day Moving Average)
  2. Price Spread Expansion & Green Body Ratio
  3. Close-Position Ratio (Dominance check: Close near high vs. low)
  4. Rejection Upper-Wick Ratio (Trap filter: Prevents buying distribution churn)
  5. Minimum Traded Turnover Filter (Prevents illiquid penny stock traps)
  6. RSI Parabolic Climax & Circuit Lock Guards
"""
import numpy as np
import pandas as pd
import config


def evaluate_volume_and_price(df: pd.DataFrame, price: float, ldcp: float | None = None,
                              s1: float = 0.0, r1: float = 0.0, rsi_val: float = 50.0,
                              cmf_val: float = 0.0, obv_up: bool = False) -> dict:
    """
    Performs institutional quantitative evaluation of volume and price action.
    Returns full metrics and signal classification with Anti-Fakeout verification.
    """
    if df is None or len(df) < 15:
        return {"has_signal": False, "metrics": {}}

    vols = df["volume"].values
    # Exclude the current active bar to compute the baseline 20-day average
    avg_vol_20 = float(np.mean(vols[-21:-1])) if len(vols) >= 21 else (float(np.mean(vols[:-1])) if len(vols) > 1 else float(vols[0]))
    curr_vol = float(vols[-1]) if len(vols) else 0.0
    
    rvol = round(curr_vol / avg_vol_20, 2) if avg_vol_20 > 0 else 1.0
    turnover_pkr = round(curr_vol * price, 2)
    
    last_bar = df.iloc[-1]
    c_open = float(last_bar["open"])
    c_high = float(last_bar["high"])
    c_low = float(last_bar["low"])
    c_close = float(last_bar["close"])
    c_range = c_high - c_low
    
    if ldcp is None:
        ldcp = float(df["close"].iloc[-2]) if len(df) > 1 else c_open
    
    change_pct = round((price - ldcp) / ldcp * 100, 2) if ldcp > 0 else 0.0
    
    # Candle geometry
    upper_wick = c_high - max(c_open, c_close)
    lower_wick = min(c_open, c_close) - c_low
    body = abs(c_close - c_open)
    
    upper_wick_ratio = round(upper_wick / c_range, 2) if c_range > 0 else 0.0
    lower_wick_ratio = round(lower_wick / c_range, 2) if c_range > 0 else 0.0
    close_pos_ratio = round((c_close - c_low) / c_range, 2) if c_range > 0 else 0.5
    is_green = c_close >= c_open

    # Circuit limit check
    circuit_ceiling = config.CIRCUIT_PCT - 0.4
    is_upper_lock = change_pct >= circuit_ceiling
    is_lower_lock = change_pct <= -circuit_ceiling

    # Liquidity check (Minimum 50k volume OR 2.5 Million PKR traded value)
    is_liquid = (avg_vol_20 >= config.MIN_AVG_VOLUME) or (turnover_pkr >= 2_500_000)

    metrics = {
        "current_volume": int(curr_vol),
        "avg_volume_20": int(avg_vol_20),
        "rvol": rvol,
        "turnover_pkr": turnover_pkr,
        "turnover_m": round(turnover_pkr / 1_000_000, 2),
        "change_pct": change_pct,
        "upper_wick_ratio": upper_wick_ratio,
        "lower_wick_ratio": lower_wick_ratio,
        "close_pos_ratio": close_pos_ratio,
        "is_green": is_green,
        "is_liquid": is_liquid,
        "is_upper_lock": is_upper_lock,
        "is_lower_lock": is_lower_lock
    }

    # =========================================================================
    # ANTI-FAKEOUT SIGNAL CLASSIFICATION
    # =========================================================================
    
    # 1. UPPER CIRCUIT LOCK GUARD:
    # If already locked, never send an active buy breakout alert (buying into lock traps)
    if is_upper_lock:
        return {
            "has_signal": True,
            "trigger": "UPPER_CIRCUIT_CEILING",
            "badge": "🔒 UPPER CIRCUIT CEILING",
            "bias": "HOLD_WAIT",
            "confidence": 95,
            "metrics": metrics,
            "anti_fakeout_status": "LOCKED_CEILING",
            "details": (
                f"Upper Circuit reached (+{change_pct:.2f}%). Volume: {int(curr_vol):,} shares ({rvol}x normal). "
                f"⚠️ Strictly DO NOT chase at the locked ceiling; entry should only be taken on structured dips."
            )
        }

    # 2. LOWER CIRCUIT / DUMP GUARD:
    if is_lower_lock or change_pct <= -6.5:
        return {
            "has_signal": True,
            "trigger": "CRASH_LOWER_LOCK",
            "badge": "🚨 LOWER CIRCUIT / HEAVY CRASH",
            "bias": "AVOID",
            "confidence": 98,
            "metrics": metrics,
            "anti_fakeout_status": "DUMP_ACTIVE",
            "details": (
                f"Severe selling pressure / lower circuit drop ({change_pct:.2f}%). "
                f"Volume {rvol}x normal. Smart money dumping / zero buyers lock."
            )
        }

    # 3. TRAP FILTER: DISTRIBUTION CHURN AT RESISTANCE
    # High volume entered, but created a massive upper wick or dumped into the close
    if is_liquid and rvol >= 1.4 and (upper_wick_ratio >= 0.38 or close_pos_ratio <= 0.40):
        if r1 > 0 and (c_high >= r1 * 0.99 or rsi_val >= 68):
            return {
                "has_signal": True,
                "trigger": "DISTRIBUTION_CHURN_WARNING",
                "badge": "⚠️ VOLUME REJECTION / CHURN TRAP",
                "bias": "AVOID_BUY",
                "confidence": 92,
                "metrics": metrics,
                "anti_fakeout_status": "TRAP_BLOCKED",
                "details": (
                    f"ANTI-FAKEOUT SHIELD TRIGGERED: Elevated volume ({rvol}x normal, Rs. {metrics['turnover_m']}M) "
                    f"hit overhead resistance Rs. {r1:.2f}, creating a {int(upper_wick_ratio*100)}% upper rejection wick. "
                    f"Smart money is offloading into retail FOMO. DO NOT BUY."
                )
            }

    # 4. TRAP FILTER: ILLIQUID PENNY MANIPULATION
    # If someone pushed a stock with thin turnover (< 2.0M PKR and < 35k shares)
    if not is_liquid and turnover_pkr < 2_000_000:
        # Suppress alerts for illiquid stocks to protect user capital
        return {"has_signal": False, "metrics": metrics, "anti_fakeout_status": "ILLIQUID_SUPPRESSED"}

    # 5. HIGH-CONFLUENCE INSTITUTIONAL VOLUME BREAKOUT (Verified Bullish Markup)
    # Genuine institutional accumulation: RVOL >= 1.4x, Price up >= +0.8%, Green bar, strong close, clean candle
    if (
        is_liquid
        and rvol >= 1.4
        and change_pct >= 0.85
        and is_green
        and close_pos_ratio >= 0.58
        and upper_wick_ratio <= 0.28
        and rsi_val <= 78
    ):
        urgency = "🔥 HIGH MOMENTUM" if rvol >= 2.0 else "🟢 INSTITUTIONAL"
        return {
            "has_signal": True,
            "trigger": "INSTITUTIONAL_VOLUME_BREAKOUT",
            "badge": f"🚀 {urgency} VOLUME BREAKOUT",
            "bias": "BULLISH",
            "confidence": 90 if rvol >= 2.0 else 84,
            "metrics": metrics,
            "anti_fakeout_status": "PASSED_VERIFIED",
            "details": (
                f"Smart money volume expansion confirmed: Traded {int(curr_vol):,} shares ({rvol}x 20D average, Rs. {metrics['turnover_m']}M). "
                f"Price expanding (+{change_pct:.2f}%) with strong close in upper {int(close_pos_ratio*100)}% of range. "
                f"✅ Verified: Clean body, no distribution wick."
            )
        }

    # 6. EARLY VOLUME ACCUMULATION PULSE (Smart Money Absorbing Supply in POI)
    # RVOL >= 1.25x, price stable/modest (+0.2% to +1.8%), near support S1 or in discount, CMF positive
    if (
        is_liquid
        and rvol >= 1.25
        and -0.4 <= change_pct <= 1.80
        and upper_wick_ratio <= 0.32
        and (cmf_val > 0.04 or obv_up)
        and (s1 > 0 and (price - s1) / s1 <= 0.025)
    ):
        return {
            "has_signal": True,
            "trigger": "VOLUME_ACCUMULATION_PULSE",
            "badge": "⚡ VOLUME ACCUMULATION PULSE",
            "bias": "BULLISH_POI",
            "confidence": 82,
            "metrics": metrics,
            "anti_fakeout_status": "PASSED_POI",
            "details": (
                f"Quiet institutional absorption: Volume {rvol}x normal ({int(curr_vol):,} shares) at demand level Rs. {s1:.2f}. "
                f"Money Flow positive (CMF: {cmf_val:+.2f}). Supply being cornered before the markup leg."
            )
        }

    # 7. INSTITUTIONAL LIQUIDATION / SELLING PRESSURE
    # Heavy volume with downward displacement
    if is_liquid and rvol >= 1.5 and change_pct <= -1.20 and not is_green and close_pos_ratio <= 0.35:
        return {
            "has_signal": True,
            "trigger": "INSTITUTIONAL_LIQUIDATION",
            "badge": "🚨 INSTITUTIONAL LIQUIDATION / DUMP",
            "bias": "BEARISH",
            "confidence": 88,
            "metrics": metrics,
            "anti_fakeout_status": "HEAVY_SELLING",
            "details": (
                f"HEAVY SELLING PRESSURE: Institutional exit underway ({rvol}x normal volume, Rs. {metrics['turnover_m']}M). "
                f"Price dropping ({change_pct:.2f}%) with close near lows. Stay sidelined or exit long positions."
            )
        }

    return {"has_signal": False, "metrics": metrics, "anti_fakeout_status": "NORMAL"}
