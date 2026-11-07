"""WhatsApp message formatter (pehle psx_analyzer.py mein missing tha -> bot crash karta tha)."""


def format_whatsapp_message(r: dict) -> str:
    if r.get("error"):
        return f"❌ {r['error']}"
    arrow = "🟢" if r["change"] >= 0 else "🔴"
    smc = r.get("smc", {})
    lines = [
        f"📊 *{r['symbol']}* — Rs. {r['current_price']}  {arrow} {r['change']:+.2f} ({r['change_pct']:+.2f}%)",
        "━━━━━━━━━━━━━━━━━━━━",
        f"🎯 *{r['verdict']}*",
        f"📈 Score: *{r['score']:+.0f}/100* | Confidence: *{r['confidence']}%*",
        f"🧭 {r['confluence_score']}",
        "",
        "*⏱ Multi-Timeframe*",
    ]
    for m in r["matrix"]:
        lines.append(f"• {m['tf']}: {m['badge']} (RSI {m['rsi']})")
    lines += [
        "",
        "*💰 Trade Plan*",
        f"🟢 Entry: {r['buy_zone']}",
        f"🛑 Stop: {'Rs. ' + str(r['stop_loss']) if r['stop_loss'] != '—' else '—'}",
        f"🚀 TP1: {r['target_1']} | TP2: {r['target_2']} | TP3: {r['target_3']}",
        f"⚖️ R:R {r['risk_reward']}",
        "",
        "*🐋 Smart Money*",
        f"{smc.get('smc_bias', '')}",
        f"Structure: {smc.get('structure', '')} | Flow: {r['accumulation_status']}",
        f"CMF20 {r['cmf']} | RSI {r['rsi']}",
        f"⚠️ {r['reversal_alert']}",
        "",
        "*📚 Valuation*",
        f"{r['valuation_status']}",
        f"P/E {r['pe_ratio'] or 'N/A'} | EPS {r['eps'] if r['eps'] is not None else 'N/A'} | BV {r['book_value'] or 'N/A'}",
        "",
        f"🧠 {r['prediction_narrative']}",
    ]
    j = r.get("journal") or {}
    if j.get("n"):
        lines.append(f"\n📒 Bot ka live record: {j['n']} closed signals, win {j['win_rate']}%, avg {j['avg_r']}R")
    lines.append("\n_Educational analysis hai, financial advice nahi. Apna risk khud manage karein._")
    return "\n".join(lines)
