import sys, os
sys.path.insert(0, '.')
sys.stdout.reconfigure(encoding='utf-8')
from psx.analyzer import analyze_stock

for sym in ['EFERT', 'FFC', 'FCCL', 'OGDC', 'MCB']:
    r = analyze_stock(sym)
    print(f"{sym}: verdict={r['verdict']} | action={r['action']} | buy_zone={r['buy_zone']}")
    print(f"       factors={r['factors']} | score={r['score']} | conf={r['confidence']}")
