"""
psx/eagle_eye.py: Autonomous Real-Time Sentinel & Market Scanner
Equipped with Institutional Volume & Price Expansion Engine + Anti-Fakeout Shield.

Continuously monitors registered PSX stocks with eagle-eye precision:
  1. High-Confluence Institutional Volume Breakout (Anti-Fakeout Verified)
  2. Early Smart Money Accumulation Pulse in Discount POIs
  3. Anti-Trap Shield: Volume Rejection / Distribution Churn at Resistance
  4. Institutional Liquidation / Heavy Selling Warning
  5. Upper Circuit Ceiling Guards
  6. Support & Resistance Proximity POIs (Within 1.2%)
  7. SMC Liquidity Sweeps (Turtle Soup Reversals - Fresh Reclaims Only)

Features:
  - Smart Conflict Resolution Matrix (Dumps/Traps suppress Bullish alerts)
  - Stale Sweep Filter (Fresh within 1 bar and 3.5% price proximity only)
  - Single Consolidated High-Confluence Alert per Stock per Scan Cycle
"""
import time
import threading
from concurrent.futures import ThreadPoolExecutor

import config
from . import data, analyzer, notifier, symbols, volume_sentinel

_COOLDOWN = {}
COOLDOWN_SECONDS = 1200  # 20 minutes cooldown per symbol+trigger
SYMBOL_COOLDOWN_SECONDS = 300  # 5 minutes min between alerts for the same symbol
_RUNNING = False
_MONITOR_THREAD = None

ALERT_PRIORITY = {
    # DEFENSIVE & DANGER (Highest priority - capital preservation first)
    "CRASH_LOWER_LOCK": 100,
    "DISTRIBUTION_CHURN_WARNING": 95,
    "INSTITUTIONAL_LIQUIDATION": 90,
    "UPPER_CIRCUIT_CEILING": 85,
    
    # HIGH-CONFLUENCE ACTIONABLE BULLISH SETUPS
    "INSTITUTIONAL_VOLUME_BREAKOUT": 80,
    "TURTLE_SOUP_SSL_SWEEP": 75,
    "VOLUME_ACCUMULATION_PULSE": 70,
    "BULLISH_TREND_START": 65,
    
    # BEARISH BREAKDOWNS
    "BEARISH_TREND_START": 60,
    
    # SECONDARY POIs
    "OTE_DISCOUNT_ACCUMULATION": 50,
    "APPROACHING_RESISTANCE": 40,
    "APPROACHING_SUPPORT": 35,
}


def check_stock_triggers(symbol: str) -> list[dict]:
    """
    Analyzes a single stock and returns triggered alerts if criteria met.
    Applies strict Institutional Confluence, Conflict Suppression, and Anti-Trap Shielding.
    """
    symbol = symbol.upper().strip()
    try:
        r = analyzer.analyze_stock(symbol, chart_tf="1D", log=False)
        if not r or r.get("error"):
            return []
    except Exception:
        return []

    alerts = []
    price = r.get("current_price", 0)
    if price <= 0:
        return []

    smc = r.get("smc", {})
    structure = smc.get("structure", "")
    ote = smc.get("ote_poi")
    score = r.get("score", 0)
    action = r.get("action", "WAIT")
    chg_pct = float(r.get("change_pct") or 0)
    rsi_val = float(r.get("rsi") or 50)
    cmf_val = float(r.get("cmf") or 0)
    accum_status = str(r.get("accumulation_status", ""))
    obv_up = "ACCUMULATION" in accum_status
    
    s1 = float(r.get("support_1") or 0)
    r1 = float(r.get("resistance_1") or 0)

    # -------------------------------------------------------------------------
    # 1. INSTITUTIONAL VOLUME & PRICE SURGE EVALUATION (ANTI-FAKEOUT SHIELD)
    # -------------------------------------------------------------------------
    vol_eval = {}
    try:
        df_hist = data.fetch_history(symbol, "D", 30)
        if df_hist is not None and len(df_hist) >= 15:
            vol_eval = volume_sentinel.evaluate_volume_and_price(
                df=df_hist,
                price=price,
                ldcp=None,
                s1=s1,
                r1=r1,
                rsi_val=rsi_val,
                cmf_val=cmf_val,
                obv_up=obv_up
            )
            if vol_eval.get("has_signal"):
                m = vol_eval.get("metrics", {})
                alerts.append({
                    "trigger": vol_eval["trigger"],
                    "badge": vol_eval["badge"],
                    "details": vol_eval["details"],
                    "rvol": m.get("rvol"),
                    "turnover_m": m.get("turnover_m"),
                    "anti_fakeout_status": vol_eval.get("anti_fakeout_status")
                })
    except Exception as e:
        print(f"Volume Sentinel check error for {symbol}: {e}")

    # Determine Institutional Risk / Conflict States
    trap_status = vol_eval.get("anti_fakeout_status", "NORMAL")
    trap_blocked = (trap_status == "TRAP_BLOCKED" or vol_eval.get("trigger") == "DISTRIBUTION_CHURN_WARNING")
    dump_active = (trap_status in ("DUMP_ACTIVE", "HEAVY_SELLING") or vol_eval.get("trigger") in ("CRASH_LOWER_LOCK", "INSTITUTIONAL_LIQUIDATION"))
    bearish_structure = (structure in ("BEARISH_CHOCH", "BEARISH_BOS") or score <= -35)
    
    # Absolute danger condition: Never buy into traps, active dumps, or broken structures
    is_danger = trap_blocked or dump_active or bearish_structure
    
    near_resistance = (r1 > 0 and 0 <= (r1 - price) / price <= 0.012)
    near_support = (s1 > 0 and 0 <= (price - s1) / s1 <= 0.012)

    # -------------------------------------------------------------------------
    # 2. SUPPORT & RESISTANCE PROXIMITY CHECKS
    # -------------------------------------------------------------------------
    # Resistance supply alert: only if not already warned about churn trap or dump
    if near_resistance and not trap_blocked and not dump_active:
        alerts.append({
            "trigger": "APPROACHING_RESISTANCE",
            "badge": "⚠️ RESISTANCE SUPPLY ALERT",
            "details": f"Price (Rs. {price:.2f}) overhead supply resistance Rs. {r1:.2f} ke paas hai. Profit taking ya pullback alert."
        })

    # Support demand alert: strictly suppressed if stock is in trap, dump, or breakdown!
    if near_support and not is_danger:
        alerts.append({
            "trigger": "APPROACHING_SUPPORT",
            "badge": "🎯 SUPPORT POI ALERT",
            "details": f"Price (Rs. {price:.2f}) institutional demand support Rs. {s1:.2f} ke bilkul qareeb hai. High-probability bounce POI."
        })

    # -------------------------------------------------------------------------
    # 3. SMC STRUCTURAL SHIFTS
    # -------------------------------------------------------------------------
    if not is_danger and not near_resistance:
        if structure == "BULLISH_BOS" or (score >= 45 and action == "BUY"):
            alerts.append({
                "trigger": "BULLISH_TREND_START",
                "badge": "🟢 BULLISH TREND START",
                "details": f"Bullish structure breakout: Price broke structural swing high (Score: +{score}). Smart money markup active."
            })
        elif ote and ote.get("in_ote_zone") and smc.get("is_volume_dryup") and score >= 15:
            alerts.append({
                "trigger": "OTE_DISCOUNT_ACCUMULATION",
                "badge": "🟢 OTE DISCOUNT ACCUMULATION",
                "details": f"Price wholesale 62%-79% OTE discount zone mein hai ({ote.get('ote_range')}). Selling volume completely dry."
            })

    # Bearish breakdown: only if not already alerted as lower circuit or liquidation dump
    if bearish_structure and not dump_active:
        alerts.append({
            "trigger": "BEARISH_TREND_START",
            "badge": "🔴 BEARISH TREND START",
            "details": f"Bearish Breakdown: Structural support toot chuki hai (Score: {score}). Heavy institutional supply."
        })

    # -------------------------------------------------------------------------
    # 4. FRESH SMC LIQUIDITY SWEEPS (TURTLE SOUP)
    # -------------------------------------------------------------------------
    # A Turtle Soup setup is strictly a FRESH reclaim near the sweep level!
    # Suppress if danger/trap is active or if price has already expanded far away!
    if not is_danger and not near_resistance:
        sweeps = smc.get("liquidity_sweeps", [])
        for sw in sweeps:
            if sw.get("type") == "SSL_SWEEP":
                bars_ago = sw.get("bars_ago", 999)
                sw_level = float(sw.get("level", 0))
                dist_pct = (price - sw_level) / sw_level if sw_level > 0 else 999
                # Fresh: happened in the last 1 bar (bars_ago <= 1) and within 3.5% of reclaim level
                if bars_ago <= 1 and 0 <= dist_pct <= 0.035:
                    alerts.append({
                        "trigger": "TURTLE_SOUP_SSL_SWEEP",
                        "badge": "⚡ TURTLE SOUP SSL SWEEP",
                        "details": f"Smart Money ne retail sell stop-losses hunt kar ke price swing low Rs. {sw_level:.2f} ke upar reclaim kar li hai."
                    })
                break

    if not alerts:
        return []

    # -------------------------------------------------------------------------
    # 5. SELECT SINGLE HIGHEST-PRIORITY CONFLUENCE ALERT PER STOCK
    # -------------------------------------------------------------------------
    alerts.sort(key=lambda a: ALERT_PRIORITY.get(a["trigger"], 0), reverse=True)
    best_alert = alerts[0]

    # Confluence enhancement: merge helpful secondary notes into the single card
    if best_alert["trigger"] == "DISTRIBUTION_CHURN_WARNING" and near_resistance:
        if "overhead resistance" not in best_alert["details"]:
            best_alert["details"] += f" (Near Key Resistance Rs. {r1:.2f})"
    elif best_alert["trigger"] == "TURTLE_SOUP_SSL_SWEEP" and near_support:
        best_alert["details"] += f" (Confluence: Reclaimed at institutional demand S1 Rs. {s1:.2f})"
    elif best_alert["trigger"] == "VOLUME_ACCUMULATION_PULSE" and near_support:
        best_alert["details"] += f" (Confluence: Demand support S1 Rs. {s1:.2f})"

    # -------------------------------------------------------------------------
    # 6. COOLDOWN & DEDUPLICATION CHECK
    # -------------------------------------------------------------------------
    now_ts = time.time()
    key = f"{symbol}_{best_alert['trigger']}"
    last_trigger_time = _COOLDOWN.get(key, 0)
    last_symbol_time = _COOLDOWN.get(symbol, 0)
    
    is_critical_danger = ALERT_PRIORITY.get(best_alert["trigger"], 0) >= 90
    
    # Conditions to fire:
    # 1) Same trigger must respect 20-min cooldown
    # 2) Symbol must respect 5-min cooldown between any alerts, UNLESS it's a critical danger alert (CRASH/TRAP)
    trigger_cooldown_ok = (now_ts - last_trigger_time) >= COOLDOWN_SECONDS
    symbol_cooldown_ok = (now_ts - last_symbol_time) >= SYMBOL_COOLDOWN_SECONDS or is_critical_danger

    if trigger_cooldown_ok and symbol_cooldown_ok:
        _COOLDOWN[key] = now_ts
        _COOLDOWN[symbol] = now_ts
        best_alert.update({
            "symbol": symbol,
            "price": price,
            "score": score,
            "action": action,
            "buy_zone": r.get("buy_zone"),
            "stop_loss": r.get("stop_loss"),
            "target_1": r.get("target_1"),
            "target_2": r.get("target_2"),
            "rr": r.get("risk_reward")
        })
        return [best_alert]

    return []


def run_eagle_eye_cycle(universe: list = None) -> list:
    """
    Runs one complete sweep across monitored PSX stocks.
    """
    # Monitor top active volume stocks
    stocks = universe or symbols.get_symbols("CORE")
    new_alerts = []

    def _eval(sym):
        try:
            return check_stock_triggers(sym)
        except Exception:
            return []

    with ThreadPoolExecutor(max_workers=6) as ex:
        futures = [ex.submit(_eval, s) for s in stocks]
        for f in futures:
            alts = f.result()
            for a in alts:
                notifier.broadcast_alert(a)
                new_alerts.append(a)

    return new_alerts


def _monitor_loop(poll_interval: int = 75):
    global _RUNNING
    while _RUNNING:
        try:
            run_eagle_eye_cycle()
        except Exception as e:
            print(f"Eagle-Eye loop error: {e}")
        time.sleep(poll_interval)


def start_eagle_eye(poll_interval: int = 75):
    """Starts the real-time Eagle-Eye monitoring daemon."""
    global _RUNNING, _MONITOR_THREAD
    if _RUNNING:
        return
    _RUNNING = True
    _MONITOR_THREAD = threading.Thread(target=_monitor_loop, args=(poll_interval,), daemon=True)
    _MONITOR_THREAD.start()
    print("🦅 PSX Eagle-Eye Real-Time Sentinel Started in Background with Anti-Fakeout Shield!")


def stop_eagle_eye():
    global _RUNNING
    _RUNNING = False
