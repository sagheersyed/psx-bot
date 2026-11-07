"""Usage: python scripts/run_backtest.py OGDC SYS LUCK ...
Har stock par strategy ka walk-forward backtest chalata hai aur result journal DB mein save karta hai
(analyzer is se confidence calibrate karta hai)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from psx import data, journal  # noqa: E402
from psx.backtest import run_backtest, summarize, by_bucket  # noqa: E402

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    symbols = [s.upper() for s in sys.argv[1:]] or ["OGDC", "SYS", "LUCK", "ENGRO", "HUBC"]
    allt = []
    for s in symbols:
        df = data.fetch_history(s, "D", 1500)
        if df is None or len(df) < 200:
            print(f"{s}: data kam/nahi mila"); continue
        t = run_backtest(df)
        sm = summarize(t)
        journal.save_backtest(s, sm)
        allt += t
        print(f"{s}: {sm}")
    if allt:
        print("\n=== COMBINED ===\n", summarize(allt))
        for k, v in by_bucket(allt).items():
            print(f"  {k}: {v}")
