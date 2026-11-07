import sys, os
sys.path.insert(0, os.path.abspath("."))
sys.stdout.reconfigure(encoding='utf-8')
from psx.low_float_analyzer import analyze_low_float_stocks

res = analyze_low_float_stocks()
print(f"Total: {res['total_tracked']}, Active Season: {res['active_season_count']}, Game Forming: {res['game_forming_count']}, Upper Lock: {res['upper_lock_count']}")
print("-" * 105)
for s in res['stocks']:
    if s['phase_code'] in ['UPPER_LOCK', 'BREAKOUT', 'ACCUMULATION'] or s['float_turnover_pct'] > 1.0:
        print(f"[{s['symbol']:<5}] Rs.{s['price']:<7.2f} ({s['change_pct']:>+6.2f}%) | Vol:{s['volume']:>8,} ({s['vol_surge_x']:>4.1f}x) | FloatTurn:{s['float_turnover_pct']:>5.2f}% | {s['syndicate_phase']} | {s['season_badge']}")
