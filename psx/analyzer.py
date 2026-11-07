"""Orchestrator: data -> signal -> dashboard/WhatsApp ke liye result dict."""
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd

import config
from . import data, mtf, journal, scoring
from .signal import evaluate
from .charts import generate_candlestick_chart


def _clean(o):
    """numpy/pandas types ko JSON-safe banao."""
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items() if k not in ("df", "d", "all_obs")}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating, float)):
        return None if (o != o) else float(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, pd.Timestamp):
        return str(o)
    return o


def _valuation(pb):
    if not pb:
        return "Valuation data available nahi"
    if pb < 0.9:
        return f"Deeply Undervalued (Below Book Value, {pb}x P/B)"
    if pb <= 1.5:
        return f"Fairly Valued ({pb}x P/B)"
    return f"Premium Valuation ({pb}x P/B)"


def analyze_stock(symbol: str, chart_tf: str = "1D", log: bool = True, fast_mode: bool = False) -> dict:
    symbol = symbol.upper().strip()
    tfs = mtf.run_all(symbol, selected_tfs=["1W", "1D", "60M", "15M"] if fast_mode else None)
    daily = tfs.get("1D")
    if not daily or daily["df"] is None or len(daily["df"]) < 30:
        return {"error": f"'{symbol}' ka daily data nahi mil saka. Ticker check karein (e.g. OGDC, SYS, LUCK, ENGRO)."}

    now = data.now_pkt()
    session_open = data.is_session_open(now)
    quote, fund = {}, {}

    if not fast_mode:
        with ThreadPoolExecutor(max_workers=2) as ex:
            qf, ff = ex.submit(data.fetch_quote, symbol), ex.submit(data.fetch_fundamentals, symbol)
            quote, fund = qf.result() or {}, ff.result() or {}
    elif session_open:
        quote = data.fetch_quote(symbol) or {}

    df = daily["df"]
    now = data.now_pkt()
    session_open = data.is_session_open(now)
    partial = session_open and df.index[-1].date() == now.date()
    df_done = df.iloc[:-1] if partial else df          # adhoori candle indicators kharab karti hai
    live_price = quote.get("current_price")
    price = float(live_price) if (live_price and session_open) else float(df["close"].iloc[-1])
    ldcp = float(df_done["close"].iloc[-1]) if partial else None

    align, bull, bear = mtf.weighted_alignment(tfs)
    micro_bear = any(tfs.get(t) and tfs[t]["status"] == "BEARISH" for t in ("15M", "5M"))
    bv = fund.get("book_value")
    pb = round(price / bv, 2) if (bv and bv > 0) else None
    pe = quote.get("pe_ratio") or fund.get("trailing_pe")
    eps = quote.get("eps") or fund.get("eps")
    if pe and pe > 0 and (not eps or eps == 0):
        eps = round(price / pe, 2)
    elif eps and eps > 0 and (not pe or pe == 0):
        pe = round(price / eps, 2)
    div_yield = fund.get("dividend_yield")

    sig = evaluate(df_done, price, ldcp, align, pb, eps, micro_bear)
    smc, g, lv, d = sig["smc"], sig["gates"], sig["levels"], sig["d"]
    last = d.iloc[-1]

    # backtest se calibration: agar is stock par strategy historically kamzor hai to confidence ghatao
    bt = journal.get_backtest(symbol)
    bt_line = ""
    if bt and bt.get("n", 0) >= 8:
        bt_line = f" Backtest ({bt['n']} trades): win {bt['win_rate']}%, avg {bt['avg_r']}R."
        if bt["expectancy"] is not None and bt["expectancy"] < 0:
            sig["confidence"] = int(sig["confidence"] * 0.8)
            bt_line += " ⚠️ Is stock par strategy historically kamzor rahi."
            if sig["action"] == "BUY" and sig["confidence"] < config.MIN_CONFIDENCE:
                sig.update(verdict="🟡 LOW-CONFIDENCE SETUP (Wait)", mode="none", action="WAIT")

    # Multi-layer Support (S1, S2, S3) and Resistance (R1, R2, R3)
    atr = lv.get("atr") or float(d["atr"].iloc[-1]) or (price * 0.02)
    sup_val = lv["support"] or (price - 1.5 * atr)
    s1 = round(sup_val, 2)
    s2 = round(max(sup_val - 1.2 * atr, price * 0.85), 2)
    s3 = round(max(sup_val - 2.5 * atr, price * 0.75), 2)

    res_val = lv.get("resistance") or lv["t1"] or (price + 1.5 * atr)
    r1 = round(res_val, 2)
    r2 = round(lv["t2"] or (res_val + 1.5 * atr), 2)
    r3 = round(lv["t3"] or (res_val + 3.0 * atr), 2)

    # -------------------------------------------------------------------------
    # Anti-Fakeout Trap Integration: Sync Cockpit Verdict with Volume Sentinel!
    # -------------------------------------------------------------------------
    from . import volume_sentinel
    vol_eval = volume_sentinel.evaluate_volume_and_price(
        df=df, price=price, ldcp=ldcp, s1=s1, r1=r1,
        rsi_val=float(last["rsi"]), cmf_val=float(last["cmf20"]),
        obv_up=(last["obv"] > last["obv_ema"])
    )

    actionable = sig["mode"] != "none"

    if g["crash"] or vol_eval.get("anti_fakeout_status") == "DUMP_ACTIVE":
        sig["verdict"] = "🚨 LOWER CIRCUIT / VIOLENT CRASH (Do Not Buy)"
        sig["action"] = "AVOID"
        sig["mode"] = "none"
        actionable = False
        buy_zone = "🚨 LOWER CIRCUIT / NO ENTRY (Heavy dumping)"
    elif g["upper_lock"] or vol_eval.get("anti_fakeout_status") == "LOCKED_CEILING":
        sig["verdict"] = "🟡 UPPER CIRCUIT LOCK (Chase strictly prohibited)"
        sig["action"] = "WAIT"
        sig["mode"] = "none"
        actionable = False
        buy_zone = f"🔒 UPPER LOCK (Pre-Open 9:15 AM Limit: Rs. {price:.2f})"
    elif vol_eval.get("anti_fakeout_status") == "TRAP_BLOCKED":
        sig["verdict"] = "⚠️ TRAP SHIELD: VOLUME REJECTION AT RESISTANCE (Wait for Dip)"
        sig["action"] = "WAIT"
        sig["mode"] = "none"
        actionable = False
        buy_zone = f"⏳ PULLBACK POI: Rs. {s1} - {price:.2f} (Dip ka intezar karein - Resistance par buy trap hai)"
    elif actionable:
        buy_zone = f"🟢 ACTIVE BUY ZONE: Rs. {lv['entry_low']} - {lv['entry_high']}"
    else:
        buy_zone = f"⏳ PULLBACK POI: Rs. {lv['entry_low']} - {lv['entry_high']} (Dip ka intezar karein)"

    # ALWAYS provide complete, exact Stop Loss and Targets (TP1, TP2, TP3)
    stop = lv["stop"]
    t1 = lv["t1"]
    t2 = lv["t2"]
    t3 = lv["t3"]
    rr = f"1:{lv['rr']}"

    cmf20, cmf5 = round(float(last["cmf20"]), 3), round(float(last["cmf5"]), 3)
    obv_up = last["obv"] > last["obv_ema"]
    if g["crash"]:
        accum = "🚨 SEVERE DUMPING / LIQUIDATION"
    elif cmf20 > 0.05 and obv_up:
        accum = "🟢 ACCUMULATION (CMF + OBV positive)"
    elif cmf20 < -0.05 and not obv_up:
        accum = "🔴 DISTRIBUTION (CMF + OBV negative)"
    else:
        accum = "NEUTRAL / INDECISION"

    sweeps = smc["liquidity_sweeps"]
    if g["crash"] or vol_eval.get("anti_fakeout_status") == "DUMP_ACTIVE":
        reversal = "🚨 LOWER CIRCUIT / VIOLENT CRASH"
    elif vol_eval.get("anti_fakeout_status") == "TRAP_BLOCKED":
        reversal = "⚠️ TRAP SHIELD: VOLUME REJECTION AT RESISTANCE"
    elif sweeps:
        s = sweeps[-1]
        bars = s.get("bars_ago", 0)
        level_dist = abs(price - s["level"]) / s["level"] if s["level"] > 0 else 1.0
        if bars <= 2 and level_dist <= 0.04:
            reversal = (f"🟢 SSL sweep reclaimed @ Rs. {s['level']} (possible reversal)" if s["bias"] == "BULLISH"
                        else f"🔴 BSL sweep @ Rs. {s['level']} (possible bull-trap)")
        elif s["bias"] == "BULLISH":
            reversal = f"Prior SSL sweep @ Rs. {s['level']} (reclaimed)"
        else:
            reversal = f"Prior BSL sweep @ Rs. {s['level']} (tested)"
    elif smc["is_climax_volume"] and sig["score"] < 0:
        reversal = "⚠️ Climax volume on weakness"
    else:
        reversal = "NORMAL"

    warnings = []
    if g["low_liquidity"]:
        warnings.append(f"LOW LIQUIDITY (avg vol {g['avg_volume']:,})")
    if len(df_done) < 100:
        warnings.append(f"sirf {len(df_done)} daily bars — confidence kam")
    if not live_price and session_open:
        warnings.append("live quote nahi mili, last candle price use hui")

    narrative = (f"Score {sig['score']:+.0f}/100 · Confidence {sig['confidence']}% (setup quality, guarantee nahi). "
                 f"Mukhya factors: {scoring.explain(sig['factors'])}. {smc['smc_summary']}{bt_line}")
    if sig["note"]:
        narrative += f" Note: {sig['note']}."
    if warnings:
        narrative += " ⚠️ " + "; ".join(warnings)

    ema50, ema200 = round(float(last["ema50"]), 2), round(float(last["ema200"]), 2)
    chart_path = ""
    tf_for_chart = chart_tf or "1D"
    if chart_tf:
        tf_for_chart = chart_tf if tfs.get(chart_tf) and tfs[chart_tf]["df"] is not None else "1D"
        chart_path = generate_candlestick_chart(symbol, tfs[tf_for_chart]["df"], tf_for_chart,
                                                s1, r1, stop, smc_data=smc)

    if log and sig["action"] in ("BUY", "WATCH"):
        try:
            journal.log_signal(symbol, sig)
        except Exception as e:
            print("journal error:", e)

    n_tf = sum(1 for t in tfs.values() if t and t["status"] != "NO_DATA")
    result = {
        "symbol": symbol, "current_price": round(price, 2), "change": round(price - (ldcp or float(d["close"].iloc[-2])), 2),
        "change_pct": g["change_pct"], "book_value": bv, "pb_ratio": pb, "pe_ratio": pe, "eps": eps,
        "dividend_yield": div_yield, "valuation_status": _valuation(pb),
        "accumulation_status": accum, "cmf": cmf20, "cmf_5": cmf5, "rsi": round(float(last["rsi"]), 1),
        "trend_summary": f"EMA9 {last['ema9']:.2f} | EMA20 {last['ema20']:.2f} | EMA50 {ema50}" + (f" | EMA200 {ema200}" if len(d) >= 200 else ""),
        "reversal_alert": reversal, "buy_zone": buy_zone, "stop_loss": stop,
        "target_1": t1, "target_2": t2, "target_3": t3, "risk_reward": rr,
        "support_1": s1, "support_2": s2, "support_3": s3,
        "resistance_1": r1, "resistance_2": r2, "resistance_3": r3,
        "verdict": sig["verdict"], "action": sig["action"], "score": sig["score"], "confidence": sig["confidence"],
        "factors": {k: round(v, 2) for k, v in sig["factors"].items()},
        "confluence_score": f"{bull}/{n_tf} Bullish | Score {sig['score']:+.0f} | Conf {sig['confidence']}%",
        "prediction_narrative": narrative,
        "matrix": [{k: v for k, v in tfs[t["name"]].items() if k not in ("df", "weight", "score")}
                   for t in config.TIMEFRAMES if tfs.get(t["name"])],
        "smc": smc, "warnings": warnings, "session_open": session_open,
        "journal": journal.live_stats(), "chart_path": chart_path, "chart_tf": tf_for_chart,
    }
    return _clean(result)
