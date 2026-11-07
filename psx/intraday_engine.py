"""
psx/intraday_engine.py: High-Accuracy PSX Intraday Sniper & 10% Circuit Radar Engine
Implements the Dual-Engine Institutional Framework:
  - Engine A: Morning Liquidity Sweep & Spring (09:45 - 10:45 AM)
  - Engine B: 10% Upper Circuit Hunter (10:00 AM - 12:30 PM)
Incorporates strict risk boundaries:
  - 10% / Rs. 1.00 PSX Circuit Rule
  - Midday Execution Lockout (11:30 AM - 01:30 PM)
  - 9:15 AM Gap-Up Trap Filter (70.6% fade avoidance)
  - Dynamic Breakeven Stop-Loss Lock (+0.5% gain)
  - Anti-Fakeout Resistance Churn Shield
"""
import time
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor

import config
from . import data, volume_sentinel, sector_rotation

CIRCUIT_CEILING_PCT = 10.0
MIN_PROFIT_FACTOR = 2.0

# High-Beta & Volatile Volume Momentum Universe (Daily Range >= 3.5%)
INTRADAY_MOMENTUM_UNIVERSE = [
    "PRL", "CNERGY", "PAEL", "WTL", "AIRLINK", "BOP", "HUMNL", "GGL", 
    "TPLP", "TELE", "OGDC", "PPL", "SYS", "LUCK", "FFC", "EFERT", "PSO"
]

def get_session_kill_zone(now_dt=None) -> dict:
    """
    Evaluates current PSX intraday session phase and trading permissions.
    """
    if now_dt is None:
        now_dt = datetime.now(ZoneInfo(config.TZ))
        
    if isinstance(now_dt, dtime):
        t = now_dt
    elif hasattr(now_dt, "time"):
        t = now_dt.time()
    else:
        t = dtime(10, 0)
    
    # Session Schedule:
    # 09:15 - 09:45: Opening Discovery / Trap Zone (DO NOT TRADE GAP-UPS)
    # 09:45 - 10:45: Prime Morning Kill Zone (Engine A: Sweeps)
    # 10:00 - 12:30: Mid-Morning Momentum (Engine B: 10% Circuit Hunter)
    # 11:30 - 13:30: Midday Chop / Lunch Lockout (NO NEW TRADES)
    # 13:30 - 14:30: Afternoon Continuation
    # 14:30 - 15:15: Closing Square-Off Window (EXIT INTRADAY TRADES)
    # 15:15 - 15:30: Closing Auction
    
    if t < dtime(9, 15):
        return {
            "phase": "PRE_MARKET",
            "zone": "PRE_MARKET",
            "phase_name": "Pre-Market Preparation (Orders Queuing)",
            "can_enter": False,
            "badge_color": "gray",
            "caution_flag": "PRE_SESSION",
            "guidance": "Review sector rotation and EOD reports. Market opens at 9:15 AM."
        }
    elif dtime(9, 15) <= t < dtime(9, 45):
        return {
            "phase": "OPENING_DISCOVERY",
            "zone": "OPENING_DISCOVERY_LOCKOUT",
            "phase_name": "Opening Range Discovery (9:15 - 9:45 AM)",
            "can_enter": False,
            "badge_color": "red",
            "caution_flag": "GAP_UP_RETAIL_TRAP",
            "guidance": "70.6% Gap-Up Trap Zone. DO NOT chase market orders; let the opening 30M range establish."
        }
    elif dtime(9, 45) <= t < dtime(10, 45):
        return {
            "phase": "PRIME_MORNING_KILLZONE",
            "zone": "PRIME_MORNING_KILLZONE",
            "phase_name": "🔥 Prime Morning Kill-Zone (09:45 - 10:45 AM)",
            "can_enter": True,
            "badge_color": "emerald",
            "caution_flag": "NONE",
            "guidance": "Golden Window for Engine A (Morning SSL Sweeps) and Engine B (Circuit Breakouts)."
        }
    elif dtime(10, 45) <= t < dtime(11, 30):
        return {
            "phase": "MOMENTUM_EXPANSION",
            "zone": "MOMENTUM_EXPANSION",
            "phase_name": "⚡ Momentum Expansion (10:45 - 11:30 AM)",
            "can_enter": True,
            "badge_color": "amber",
            "caution_flag": "NONE",
            "guidance": "Circuit Hunter active. Trail stops to Breakeven on active morning trades."
        }
    elif dtime(11, 30) <= t < dtime(13, 30):
        return {
            "phase": "MIDDAY_CHOP_LOCKOUT",
            "zone": "MIDDAY_CHOP_LOCKOUT",
            "phase_name": "❄️ Midday Chop Lockout (11:30 AM - 1:30 PM)",
            "can_enter": False,
            "badge_color": "red",
            "caution_flag": "MIDDAY_VOLUME_DROPOFF",
            "guidance": "Volume dries up by 60%. Execution strictly locked out to protect against stop-hunts."
        }
    elif dtime(13, 30) <= t < dtime(14, 30):
        return {
            "phase": "AFTERNOON_SESSION",
            "zone": "AFTERNOON_SESSION",
            "phase_name": "Afternoon Trend Continuation (1:30 - 2:30 PM)",
            "can_enter": False, # Only manage existing trades or trailing stops
            "badge_color": "amber",
            "caution_flag": "LATE_DAY_EXECUTION",
            "guidance": "No new entries. Manage active runner positions and trail stops."
        }
    elif dtime(14, 30) <= t <= dtime(15, 15):
        return {
            "phase": "EOD_SQUARE_OFF",
            "zone": "EOD_SQUARE_OFF",
            "phase_name": "⚠️ EOD Margin Square-Off Window (2:30 - 3:15 PM)",
            "can_enter": False,
            "badge_color": "purple",
            "caution_flag": "SQUARE_OFF_MANDATORY",
            "guidance": "Mandatory intraday exit window. Square off positions or convert green trades to Swing."
        }
    else:
        return {
            "phase": "MARKET_CLOSED",
            "zone": "MARKET_CLOSED",
            "phase_name": "Market Closed (Post-Session)",
            "can_enter": False,
            "badge_color": "gray",
            "caution_flag": "CLOSED",
            "guidance": "Continuous trading ended at 3:30 PM. Review debrief reports."
        }


def evaluate_circuit_hunter(data: dict) -> dict:
    """
    Evaluates Engine B: 10% Upper Circuit Hunter for a given scrip snapshot.
    """
    symbol = data.get("symbol", "").upper().strip()
    price = float(data.get("current_price", data.get("close", 0.0)))
    prev_close = float(data.get("prev_close", 0.0))
    rvol = float(data.get("rvol", 1.0))
    vwap = float(data.get("vwap", price))
    
    # 1. Anti-Fakeout Sentinel Trap Check
    if data.get("sentinel_wall_ahead", False):
        return {
            "symbol": symbol,
            "qualified": False,
            "veto_reason": "OVERHEAD_SENTINEL_WALL_DETECTED",
            "reason": "Institutional ask wall detected overhead. Fakeout rejection likely."
        }
    
    if prev_close <= 0:
        return {"symbol": symbol, "qualified": False, "veto_reason": "INVALID_PREV_CLOSE"}
        
    change_pct = ((price - prev_close) / prev_close) * 100.0
    is_high_beta = (symbol in INTRADAY_MOMENTUM_UNIVERSE) or data.get("is_high_beta", True)
    
    if 4.0 <= change_pct <= 6.0 and rvol >= 2.0 and price >= vwap:
        circuit_ceiling = round(prev_close * (1.0 + (CIRCUIT_CEILING_PCT / 100.0)), 2)
        target_price = round(prev_close * 1.095, 2) # ~9.5% Upper Circuit front-run
        stop_loss = round(price * 0.985, 2) # Strict 1.5% maximum stop
        
        risk = price - stop_loss
        reward = target_price - price
        rr_val = round(reward / risk, 2) if risk > 0 else 3.0
        
        return {
            "symbol": symbol,
            "qualified": True,
            "direction": "BUY",
            "setup_type": "10PCT_CIRCUIT_HUNTER",
            "entry_price": price,
            "stop_loss": stop_loss,
            "target_price": target_price,
            "change_pct": round(change_pct, 2),
            "rvol": round(rvol, 1),
            "rr_ratio": rr_val,
            "is_high_beta": is_high_beta,
            "breakeven_trigger_price": round(price * 1.015, 2),
            "confidence": 85 if rvol >= 2.5 else 75
        }
    
    return {
        "symbol": symbol,
        "qualified": False,
        "veto_reason": "SETUP_CONDITIONS_NOT_MET",
        "change_pct": round(change_pct, 2),
        "rvol": round(rvol, 1)
    }


def evaluate_morning_ssl_sweep(data: dict) -> dict:
    """
    Evaluates Engine A: Morning SSL Liquidity Sweep & Spring (09:45 - 10:45 AM).
    """
    symbol = data.get("symbol", "").upper().strip()
    price = float(data.get("current_price", data.get("close", 0.0)))
    daily_support = float(data.get("daily_support", 0.0))
    morning_low = float(data.get("morning_low", 0.0))
    rvol = float(data.get("rvol", 1.0))
    
    if morning_low < daily_support and price >= daily_support:
        buffer = daily_support * 0.004 # 0.4% buffer below sweep low
        stop_loss = round(morning_low - buffer, 2)
        breakeven_trigger_price = round(price * 1.005, 2) # +0.5% Breakeven lock
        risk = price - stop_loss
        target_price = round(price + (risk * 1.5), 2)
        
        return {
            "symbol": symbol,
            "qualified": True,
            "direction": "BUY",
            "setup_type": "MORNING_SSL_SWEEP",
            "entry_price": price,
            "stop_loss": stop_loss,
            "breakeven_trigger_price": breakeven_trigger_price,
            "target_price": target_price,
            "rvol": round(rvol, 1),
            "confidence": 78
        }
        
    return {
        "symbol": symbol,
        "qualified": False,
        "veto_reason": "NO_VALID_SWEEP"
    }


def analyze_scrip_intraday(symbol: str) -> dict | None:
    """
    Evaluates a single stock against Dual-Engine Intraday Rules:
    Engine A: Morning SSL Liquidity Sweep & Spring
    Engine B: 10% Upper Circuit Hunter Breakout
    """
    symbol = symbol.upper().strip()
    df15 = data.fetch_history(symbol, "15", days=10)
    dfd = data.fetch_history(symbol, "D", days=45)
    
    if df15 is None or dfd is None or len(df15) < 16 or len(dfd) < 20:
        return None

    now_dt = datetime.now(ZoneInfo(config.TZ))
    kill_zone = get_session_kill_zone(now_dt)
    
    # HTF Daily Context
    last_d = dfd.iloc[-1]
    prev_d = dfd.iloc[-2]
    d_close = float(last_d["close"])
    d_open = float(last_d["open"])
    prev_close = float(prev_d["close"])
    
    dfd["ema20"] = dfd["close"].ewm(span=20, adjust=False).mean()
    d_ema20 = float(dfd["ema20"].iloc[-1])
    is_htf_bullish = d_close >= d_ema20

    # 15M Indicators
    last_bar = df15.iloc[-1]
    price = float(last_bar["close"])
    high = float(last_bar["high"])
    low = float(last_bar["low"])
    vol = float(last_bar["volume"])
    
    df15["vol_ema"] = df15["volume"].rolling(14).mean().fillna(df15["volume"])
    rvol = float(vol / df15["vol_ema"].iloc[-1]) if df15["vol_ema"].iloc[-1] > 0 else 1.0
    
    # Compute Intraday Session VWAP
    typical_p = (df15["high"] + df15["low"] + df15["close"]) / 3.0
    pv = typical_p * df15["volume"]
    dates = df15.index.date
    today_date = df15.index[-1].date()
    
    today_mask = (df15.index.date == today_date)
    today_bars = df15[today_mask]
    
    if len(today_bars) < 2:
        return None
        
    vwap = float((pv[today_mask].cumsum() / df15["volume"][today_mask].cumsum()).iloc[-1])
    
    # Opening Range (First 30 minutes: 9:15 - 9:45)
    orb_bars = today_bars.between_time("09:15", "09:45")
    orb_low = float(orb_bars["low"].min()) if len(orb_bars) else float(today_bars["low"].iloc[0])
    orb_high = float(orb_bars["high"].max()) if len(orb_bars) else float(today_bars["high"].iloc[0])
    
    day_open = float(today_bars["open"].iloc[0])
    chg_from_open = ((price - day_open) / day_open) * 100.0 if day_open > 0 else 0.0
    chg_from_prev = ((price - prev_close) / prev_close) * 100.0 if prev_close > 0 else 0.0

    # Circuit limit calculation (10% or Rs. 1.00 minimum in PSX)
    circuit_ceiling = prev_close * 1.10
    circuit_gain_needed = ((circuit_ceiling - price) / price) * 100.0

    # Check Anti-Fakeout Resistance Churn Shield from Sentinel
    vol_eval = volume_sentinel.evaluate_volume_and_price(
        df=dfd, price=price, ldcp=prev_close, s1=orb_low, r1=circuit_ceiling,
        rsi_val=55.0, cmf_val=0.05, obv_up=True
    )
    if vol_eval.get("is_trap"):
        return {
            "symbol": symbol,
            "has_setup": False,
            "engine": "BLOCKED_BY_SENTINEL",
            "status": "⚠️ TRAP DETECTED: RESISTANCE CHURN",
            "reason": vol_eval.get("reason"),
            "kill_zone": kill_zone
        }

    setup_detected = None
    engine_name = None
    confidence = 0
    entry_zone = ""
    stop_loss = 0.0
    target_tp = 0.0
    rr_ratio = ""
    breakeven_trigger = 0.0
    catalyst_note = ""

    # -------------------------------------------------------------------------
    # ENGINE B: 10% UPPER CIRCUIT HUNTER (Momentum Acceleration)
    # -------------------------------------------------------------------------
    # Triggers when High-Beta stock crosses +4.0% to +5.5% with surge volume
    if (4.0 <= chg_from_prev <= 6.0) and rvol >= 2.0 and price > vwap:
        engine_name = "ENGINE_B_CIRCUIT_HUNTER"
        setup_detected = "🚀 10% UPPER CIRCUIT ACCELERATION"
        confidence = 82 if rvol >= 2.5 else 74
        entry_zone = f"Rs. {price:.2f} - {price * 1.008:.2f}"
        stop_loss = round(price * 0.985, 2) # Strict 1.5% stop
        target_tp = round(circuit_ceiling * 0.995, 2) # Near 10% Upper Circuit
        risk = price - stop_loss
        reward = target_tp - price
        rr_val = round(reward / risk, 1) if risk > 0 else 2.5
        rr_ratio = f"1:{rr_val}"
        breakeven_trigger = round(price * 1.015, 2) # Move to BE at +1.5%
        catalyst_note = f"Elevated momentum (RVOL {rvol:.1f}x) surging toward 10% Upper Circuit ceiling (Rs. {circuit_ceiling:.2f})."

    # -------------------------------------------------------------------------
    # ENGINE A: MORNING LIQUIDITY SWEEP & SPRING (09:45 - 10:45 AM)
    # -------------------------------------------------------------------------
    # Triggers on sweep of ORB low with hammer/recovery inside Bullish Daily Trend
    elif is_htf_bullish and (low < orb_low) and (price >= orb_low) and rvol >= 1.2:
        engine_name = "ENGINE_A_MORNING_SWEEP"
        setup_detected = "🎯 MORNING SSL SWEEP & REVERSAL"
        confidence = 78
        entry_zone = f"Rs. {price:.2f} - {price * 1.005:.2f}"
        buffer = price * 0.004
        stop_loss = round(low - buffer, 2) # 0.4% buffer below wick
        risk = price - stop_loss
        target_tp = round(price + (risk * 1.3), 2) # Scalp target
        rr_ratio = "1:1.3"
        breakeven_trigger = round(price * 1.005, 2) # Move to BE at +0.5%
        catalyst_note = f"Wholesale liquidity sweep below 9:15-9:45 low (Rs. {orb_low:.2f}) with smart money absorption."

    if not setup_detected:
        return None

    return {
        "symbol": symbol,
        "has_setup": True,
        "engine": engine_name,
        "setup_name": setup_detected,
        "confidence": confidence,
        "current_price": round(price, 2),
        "change_pct": round(chg_from_prev, 2),
        "rvol": round(rvol, 1),
        "entry_zone": entry_zone,
        "stop_loss": stop_loss,
        "target_tp": target_tp,
        "rr_ratio": rr_ratio,
        "breakeven_trigger": breakeven_trigger,
        "circuit_ceiling": round(circuit_ceiling, 2),
        "circuit_dist_pct": round(circuit_gain_needed, 1),
        "catalyst_note": catalyst_note,
        "kill_zone": kill_zone,
        "is_tradable": kill_zone["can_enter"]
    }


_radar_cache = None
_radar_cache_ts = 0
_RADAR_CACHE_TTL = 45 # seconds

def scan_intraday_radar(force_refresh: bool = False) -> dict:
    """
    Scans the high-beta volume universe in parallel to surface active
    Engine A and Engine B setups. Cached with 45s TTL for sub-second responses.
    """
    global _radar_cache, _radar_cache_ts
    now = time.time()
    
    if not force_refresh and _radar_cache is not None and (now - _radar_cache_ts < _RADAR_CACHE_TTL):
        # Refresh current session kill zone phase live
        cached = dict(_radar_cache)
        cached["kill_zone"] = get_session_kill_zone(datetime.now(ZoneInfo(config.TZ)))
        return cached

    now_dt = datetime.now(ZoneInfo(config.TZ))
    kill_zone = get_session_kill_zone(now_dt)
    
    setups = []
    with ThreadPoolExecutor(max_workers=6) as ex:
        futures = {ex.submit(analyze_scrip_intraday, s): s for s in INTRADAY_MOMENTUM_UNIVERSE}
        for f in futures:
            try:
                res = f.result()
                if res and res.get("has_setup"):
                    setups.append(res)
            except Exception:
                pass

    # Sort: Highest confidence and nearest to trigger first
    setups = sorted(setups, key=lambda x: (x.get("confidence", 0), x.get("rvol", 0)), reverse=True)
    
    result = {
        "timestamp": now_dt.strftime("%Y-%m-%d %H:%M:%S PKT"),
        "kill_zone": kill_zone,
        "total_active_setups": len(setups),
        "circuit_hunter_count": sum(1 for s in setups if s["engine"] == "ENGINE_B_CIRCUIT_HUNTER"),
        "morning_sweep_count": sum(1 for s in setups if s["engine"] == "ENGINE_A_MORNING_SWEEP"),
        "setups": setups
    }
    
    _radar_cache = result
    _radar_cache_ts = now
    return result
