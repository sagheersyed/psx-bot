import sys, os
sys.path.insert(0, '.')
sys.stdout.reconfigure(encoding='utf-8')
from psx.screener import scan_market
from psx.analyzer import analyze_stock

data = scan_market()
print(f"Total Scanned: {data['total_scanned']}")
print(f"Market Regime: {data['market_regime']} ({data['bull_pct']}% Bullish / {data['bear_pct']}% Bearish)")
print(f"Top Institutional Opportunities ({len(data['top_opportunities'])} Found):")
for o in data['top_opportunities']:
    print(f"  [BUY] {o['symbol']:<6} Rs.{o['price']:<7.2f} (+{o['score']} pts, conf {o['confidence']}%) | {o['verdict']}")

print(f"\nDanger Traps Detected ({len(data['danger_traps'])} Found):")
for t in data['danger_traps']:
    print(f"  [AVOID] {t['symbol']:<6} Rs.{t['price']:<7.2f} | {t['verdict']}")

print("\n--- SAMPLE ACCURACY CHECK (Backtesting Win Rates) ---")
from psx import journal
stats = journal.live_stats()
print(f"Journal Live Stats: {stats}")
