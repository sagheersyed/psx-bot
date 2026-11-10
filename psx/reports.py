"""
psx/reports.py: Automated Institutional Daily Reports Engine
Generates:
  1. Post-Market Institutional Debrief (EOD - 4:00 PM PKT)
  2. Pre-Market Strategic Game Plan (Morning - 9:00 AM PKT)
Dispatches formatted summaries to Telegram, Email, and Web Dashboard.
"""
from datetime import datetime
from zoneinfo import ZoneInfo
import threading
import time

import config
from . import data, screener, low_float_analyzer, sector_rotation, notifier

_REPORT_CACHE = {
    "eod": None,
    "eod_time": None,
    "eod_ts": 0,
    "premarket": None,
    "premarket_time": None,
    "premarket_ts": 0
}
_REPORT_LOCK = threading.Lock()


def generate_post_market_report(broadcast: bool = False, force_refresh: bool = False) -> dict:
    """
    Generates the comprehensive Post-Market Institutional Debrief.
    """
    now_ts = time.time()
    with _REPORT_LOCK:
        if not force_refresh and not broadcast and _REPORT_CACHE["eod"] and (now_ts - _REPORT_CACHE.get("eod_ts", 0)) < 300:
            return _REPORT_CACHE["eod"]

    now_dt = datetime.now(ZoneInfo(config.TZ))
    date_str = now_dt.strftime("%d-%b-%Y")
    time_str = now_dt.strftime("%H:%M:%S")

    # 1. Gather Sector Rotation & Market Flows
    sectors = sector_rotation.get_sector_rotation(force_refresh=False)
    leading_sectors = [s for s in sectors if "INFLOW" in s["flow_code"]][:3]
    lagging_sectors = [s for s in sectors if "OUTFLOW" in s["flow_code"]][:2]

    # 2. Gather Screener & Volume Leaders
    scr = screener.scan_market(force_refresh=False)
    top_buys = scr.get("top_opportunities", [])[:4]
    danger_traps = scr.get("danger_traps", [])[:4]
    regime = scr.get("market_regime", "SELECTIVE_ROTATION")
    regime_desc = scr.get("regime_desc", "Mixed market breadth")
    bull_pct = scr.get("bull_pct", 50.0)
    bear_pct = scr.get("bear_pct", 50.0)

    # 3. Gather Low-Float Syndicate Cornering
    lf_data = low_float_analyzer.analyze_low_float_stocks(force_refresh=False)
    lf_stocks = lf_data.get("stocks", []) if isinstance(lf_data, dict) else (lf_data if isinstance(lf_data, list) else [])
    cornered_stocks = [s for s in lf_stocks if (s.get("float_turnover_pct", 0) >= 3.0 or s.get("phase_code") in ("UPPER_LOCK", "BREAKOUT", "ACCUMULATION")) and s.get("phase_code") not in ("LOWER_LOCK", "DISTRIBUTION") and s.get("change_pct", 0) > -2.5][:4]

    report = {
        "report_type": "POST_MARKET_DEBRIEF",
        "title": f"PSX Post-Market Institutional Debrief ({date_str})",
        "generated_at": f"{date_str} {time_str} PKT",
        "market_summary": {
            "breadth": regime_desc,
            "bullish_pct": bull_pct,
            "bearish_pct": bear_pct,
            "state": regime
        },
        "sector_flows": {
            "leading": [{"sector": s["sector"], "avg_chg": s["avg_change_pct"], "turnover_m": s["turnover_m"], "leader": s["alpha_leader"]["symbol"]} for s in leading_sectors],
            "lagging": [{"sector": s["sector"], "avg_chg": s["avg_change_pct"], "turnover_m": s["turnover_m"]} for s in lagging_sectors]
        },
        "top_institutional_buys": top_buys,
        "danger_traps_avoided": danger_traps,
        "cornered_float_watch": cornered_stocks,
        "strategic_takeaway": (
            "Smart money rotation confirms selective accumulation in leading sectors. "
            "Do not chase stocks at 52-week highs with rejection wicks; focus execution on 15M/5M OTE discount pullbacks."
        )
    }

    with _REPORT_LOCK:
        _REPORT_CACHE["eod"] = report
        _REPORT_CACHE["eod_time"] = time_str
        _REPORT_CACHE["eod_ts"] = now_ts

    if broadcast:
        _broadcast_report(report)

    return report


def generate_pre_market_report(broadcast: bool = False, force_refresh: bool = False) -> dict:
    """
    Generates the Strategic Pre-Market Institutional Opening Briefing.
    """
    now_ts = time.time()
    with _REPORT_LOCK:
        if not force_refresh and not broadcast and _REPORT_CACHE["premarket"] and (now_ts - _REPORT_CACHE.get("premarket_ts", 0)) < 300:
            return _REPORT_CACHE["premarket"]

    now_dt = datetime.now(ZoneInfo(config.TZ))
    date_str = now_dt.strftime("%d-%b-%Y")
    time_str = now_dt.strftime("%H:%M:%S")

    # 1. Fetch Top Actionable Setups
    scr = screener.scan_market(force_refresh=False)
    top_candidates = scr.get("top_opportunities", [])[:3]

    # 2. Fetch Low-Float Cornered Radar
    lf_data = low_float_analyzer.analyze_low_float_stocks(force_refresh=False)
    lf_stocks = lf_data.get("stocks", []) if isinstance(lf_data, dict) else (lf_data if isinstance(lf_data, list) else [])
    catalyst_scrip = [s for s in lf_stocks if s.get("phase_code") in ("ACCUMULATION", "BREAKOUT", "UPPER_LOCK")][:3]

    # 3. Leading Sectors to Focus Today
    sectors = sector_rotation.get_sector_rotation(force_refresh=False)
    focus_sectors = [s["sector"] for s in sectors[:3]]

    report = {
        "report_type": "PRE_MARKET_BRIEFING",
        "title": f"PSX Pre-Market Tactical Briefing ({date_str})",
        "generated_at": f"{date_str} {time_str} PKT",
        "opening_strategy": (
            "Pre-Open 9:15 AM Discipline: Never place market buy orders on gap-up opens near resistance. "
            "Wait for the first 15-minute price discovery candle (9:30 AM) before entering high-confidence discount POIs."
        ),
        "focus_sectors": focus_sectors,
        "prime_watchlist": top_candidates,
        "cornered_scrip_watch": catalyst_scrip,
        "golden_rules": [
            "Stop Loss is mandatory on every trade — no exceptions.",
            "If Upper Circuit is locked, chasing is strictly prohibited.",
            "Take 50% profit at TP1 and move Stop Loss to Breakeven."
        ]
    }

    with _REPORT_LOCK:
        _REPORT_CACHE["premarket"] = report
        _REPORT_CACHE["premarket_time"] = time_str
        _REPORT_CACHE["premarket_ts"] = now_ts

    if broadcast:
        _broadcast_report(report)

    return report


def _broadcast_report(rep: dict):
    """Dispatches formatted briefing to Telegram and Email."""
    title = rep["title"]
    gen_time = rep["generated_at"]
    
    # Telegram Formatting
    tg_lines = [f"<b>{title}</b>", f"<i>⏱ {gen_time}</i>", "━━━━━━━━━━━━━━━━━━━━━━"]
    
    if rep["report_type"] == "POST_MARKET_DEBRIEF":
        tg_lines.append(f"📊 <b>Market Breadth:</b> {rep['market_summary']['breadth']}")
        
        tg_lines.append("\n🏆 <b>Leading Institutional Sectors:</b>")
        for s in rep["sector_flows"]["leading"]:
            tg_lines.append(f"• <b>{s['sector']}</b> ({s['avg_chg']:+0.2f}% | Rs. {s['turnover_m']}M) → Leader: #{s['leader']}")
            
        tg_lines.append("\n🚀 <b>Top Verified Institutional Setups:</b>")
        for b in rep["top_institutional_buys"][:3]:
            tg_lines.append(f"• <b>#{b['symbol']}</b> (Rs. {b['price']:.2f}) · Score +{b['score']:.0f} · Conf {b['confidence']}%")
            
        tg_lines.append("\n🚨 <b>Danger Traps Spotted & Blocked:</b>")
        for t in rep["danger_traps_avoided"][:3]:
            tg_lines.append(f"• <b>#{t['symbol']}</b> (Rs. {t['price']:.2f}) · {t['action']}")
            
        tg_lines.append(f"\n💡 <b>Takeaway:</b> {rep['strategic_takeaway']}")
        
    else:  # PRE_MARKET_BRIEFING
        tg_lines.append(f"🎯 <b>Opening Strategy:</b>\n{rep['opening_strategy']}\n")
        tg_lines.append(f"🔥 <b>Focus Sectors:</b> {', '.join(rep['focus_sectors'])}\n")
        
        tg_lines.append("🚀 <b>Top Prime Candidates for Today:</b>")
        for b in rep["prime_watchlist"][:3]:
            tg_lines.append(f"• <b>#{b['symbol']}</b> (Rs. {b['price']:.2f}) | {b['verdict']}")
            
        tg_lines.append("\n⚡ <b>Cornered Float Watch:</b>")
        for c in rep["cornered_scrip_watch"][:3]:
            tg_lines.append(f"• <b>#{c['symbol']}</b> · Float Turnover: {c.get('float_turnover_pct', 0)}% · Phase: {c.get('syndicate_phase', '—')}")

    tg_lines.append("\n━━━━━━━━━━━━━━━━━━━━━━\n<i>Automated PSX AI Intelligence Engine</i>")
    tg_text = "\n".join(tg_lines)

    notifier.send_telegram_alert(tg_text)

    # Email HTML Dispatch
    email_html = f"""
    <div style="font-family: Arial, sans-serif; background-color: #0b0e14; color: #e2e8f0; padding: 24px; border-radius: 12px; max-width: 650px;">
        <h2 style="color: #00c087; margin-top: 0; border-bottom: 1px solid #1e293b; padding-bottom: 12px;">{title}</h2>
        <p style="font-size: 12px; color: #94a3b8;">Generated: {gen_time}</p>
        <div style="background-color: #11151f; padding: 16px; border-radius: 8px; border-left: 4px solid #00c087; margin: 16px 0;">
            <p style="margin: 0; line-height: 1.6; font-size: 14px;">{rep.get('strategic_takeaway') or rep.get('opening_strategy')}</p>
        </div>
        <p style="font-size: 12px; color: #64748b;">Automated PSX Institutional Executive Debrief</p>
    </div>
    """
    notifier.send_email_alert(title, email_html)


def get_latest_reports() -> dict:
    """Returns cached reports for the UI."""
    return _REPORT_CACHE
