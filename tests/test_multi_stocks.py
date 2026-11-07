import sys, os
sys.path.insert(0, '.')
sys.stdout.reconfigure(encoding='utf-8')
from psx.analyzer import analyze_stock

for sym in ['OGDC', 'MCB', 'SINDM']:
    r = analyze_stock(sym)
    print(f"[{sym:<5}] P:{r['current_price']:<7.2f} | BuyZone:{r['buy_zone'][:30]} | SL:{r['stop_loss']} | TP1:{r['target_1']} TP2:{r['target_2']} TP3:{r['target_3']} | RR:{r['risk_reward']}")
    print(f"       Supports: S1:{r.get('support_1')} S2:{r.get('support_2')} S3:{r.get('support_3')} | Resistances: R1:{r.get('resistance_1')} R2:{r.get('resistance_2')} R3:{r.get('resistance_3')}")
    print(f"       Fundamentals: PE:{r['pe_ratio']} | EPS:{r['eps']} | Book:{r['book_value']} | PB:{r['pb_ratio']} | Yield:{r['dividend_yield']}%")
    print(f"       Matrix TFs ({len(r['matrix'])}): {[m['tf'] for m in r['matrix']]}")
