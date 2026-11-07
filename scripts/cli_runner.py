"""Node bot is script ko call karta hai: python scripts/cli_runner.py OGDC"""
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from psx.analyzer import analyze_stock  # noqa: E402
from psx.formatter import format_whatsapp_message  # noqa: E402
from psx import journal  # noqa: E402
from psx.screener import scan_market  # noqa: E402

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    arg = sys.argv[1] if len(sys.argv) > 1 else "OGDC"
    cmd = arg.lower().strip()

    if cmd in ("--stats", "stats"):
        s = journal.live_stats()
        text = ("📒 Abhi tak koi closed signal nahi." if not s["n"] else
                f"📒 *Bot Record*\nClosed: {s['n']} | Open: {s['open']}\nWin rate: {s['win_rate']}% | Avg: {s['avg_r']}R")
        out = {"text": text, "chart_path": "", "error": None}

    elif cmd in ("--scan", "scan", "top"):
        report = scan_market()
        lines = [
            "🎯 *PSX AUTONOMOUS INSTITUTIONAL SCANNER*",
            f"Regime: {report.get('market_regime')}",
            f"Breadth: 🟢 {report.get('bull_pct')}% Bullish | 🔴 {report.get('bear_pct')}% Bearish",
            "━━━━━━━━━━━━━━━━━━━━",
            "🟢 *TOP INSTITUTIONAL OPPORTUNITIES:*"
        ]
        opps = report.get("top_opportunities", [])
        if opps:
            for o in opps[:3]:
                lines.append(f"• *{o['symbol']}* (Rs. {o['price']}) — Score: *+{o['score']}* | Conf: {o['confidence']}%")
                lines.append(f"  Entry: {o['buy_zone']} | Target: {o['target_1']}")
        else:
            lines.append("• Koi high-confluence setup abhi nahi mila.")

        traps = report.get("danger_traps", [])
        if traps:
            lines.append("\n🚨 *HIGH RISK DANGER TRAPS (AVOID):*")
            for t in traps[:3]:
                lines.append(f"• *{t['symbol']}* (Rs. {t['price']}) — {t['verdict']}")

        lines.append("\n_Kisi bhi stock ka mukammal chart dekhne ke liye ticker bhejein (e.g. OGDC)._")
        out = {"text": "\n".join(lines), "chart_path": "", "error": None}

    else:
        data = analyze_stock(arg)
        out = {"text": format_whatsapp_message(data), "chart_path": data.get("chart_path", ""), "error": data.get("error")}

    print("---JSON_OUTPUT_START---")
    print(json.dumps(out, ensure_ascii=False))
    print("---JSON_OUTPUT_END---")
