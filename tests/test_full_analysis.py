import sys, os
sys.path.insert(0, '.')
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from psx.analyzer import analyze_stock

res = analyze_stock('EFERT')
print('=== EFERT FULL INSTITUTIONAL ANALYSIS ===')
print('Price:', res['current_price'])
print('Buy Zone:', res['buy_zone'])
print('Stop Loss:', res['stop_loss'])
print('Targets:', f"TP1: {res['target_1']} | TP2: {res['target_2']} | TP3: {res['target_3']}")
print('R:R:', res['risk_reward'])
print('Supports:', f"S1: {res.get('support_1')} | S2: {res.get('support_2')} | S3: {res.get('support_3')}")
print('Resistances:', f"R1: {res.get('resistance_1')} | R2: {res.get('resistance_2')} | R3: {res.get('resistance_3')}")
print('Fundamentals:', f"P/E: {res['pe_ratio']} | EPS: {res['eps']} | Book: {res['book_value']} | P/B: {res['pb_ratio']} | DivYield: {res['dividend_yield']}")
print('Matrix Rows:', len(res['matrix']))
for m in res['matrix']:
    print(f"  [{m['tf']:4}] {m['badge']:<25} Close:{m['close']:<7.2f} EMA:{m['ema9']}/{m['ema20']} RSI:{m['rsi']}")
