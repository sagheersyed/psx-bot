import urllib.request, json

url = 'http://127.0.0.1:5000/api/low_float'
req = urllib.request.urlopen(url, timeout=20)
data = json.loads(req.read().decode('utf-8'))
print('Status:', req.status)
print('Total tracked:', data.get('total_tracked'))
print('Upper locks:', data.get('upper_lock_count'))
print('Active Season:', data.get('active_season_count'))
print('Breakouts:', data.get('volume_breakout_count'))
print('Accumulation:', data.get('game_forming_count'))
for s in data.get('stocks', [])[:6]:
    print(f"[{s['symbol']:<5}] Rs.{s['price']:<7.2f} ({s['change_pct']:>+5.2f}%) | Turn:{s['float_turnover_pct']:>5.2f}% | Vol:{s['volume']:>7,} | Phase:{s['syndicate_phase']}")
