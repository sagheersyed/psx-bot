"""Regime filter kaam kar raha hai ya nahi — 1 minute ka check.

Usage:
    python scripts/verify_regime.py                  # default stocks
    python scripts/verify_regime.py LUCK OGDC BUXL   # apne stocks

Har stock ke liye wohi signal DO dafa banta hai: regime ke BAGHAIR aur regime ke SAATH,
taake farq seedha nazar aaye. Aakhir mein "agar market bearish hoti" wala test bhi hai.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from psx import data, regime  # noqa: E402
from psx.signal import evaluate  # noqa: E402

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    syms = [s.upper() for s in sys.argv[1:]] or ["LUCK", "OGDC", "MCB", "SYS", "BUXL", "FIL"]

    mkt, src = regime.load_market_close()
    if mkt is None:
        sys.exit("Market data nahi mila.")
    m_reg = regime.trend_regime(mkt)
    print(f"Market source: {src}   |   Market regime abhi: {m_reg:+.2f}  "
          f"({'bullish' if m_reg > 0.3 else 'bearish' if m_reg < -0.3 else 'neutral'})\n")
    print(f"{'Stock':<7} {'Group':<13} {'R²':>5} {'Regime':>7} | {'Score bina':>10} {'Score saath':>11} "
          f"{'Farq':>6} | {'Action bina':<11} {'Action saath':<12}")
    print("-" * 100)

    rows = []
    for s in syms:
        df = data.fetch_history(s, "D", 1500)
        if df is None or len(df) < 200:
            print(f"{s:<7} data kam/nahi mila"); continue
        price, ldcp = float(df["close"].iloc[-1]), float(df["close"].iloc[-2])
        rf = regime.live_regime(s, df["close"])
        if rf is None:
            print(f"{s:<7} regime nahi bana"); continue
        a = evaluate(df, price, ldcp)
        b = evaluate(df, price, ldcp, regime=rf["value"])
        rows.append((s, df, price, ldcp, rf, a))
        print(f"{s:<7} {rf['class']:<13} {rf['market']['r2'] or 0:>5.2f} {rf['value']:>+7.2f} | "
              f"{a['score']:>+10.1f} {b['score']:>+11.1f} {b['score'] - a['score']:>+6.1f} | "
              f"{a['action']:<11} {b['action']:<12}")

    # Stress test: asal data, lekin market ko zabardasti bearish (-1) maan kar
    print("\nAgar market BEARISH (-1.0) hoti to:")
    print(f"{'Stock':<7} {'Group':<13} {'Regime':>7} | {'Score bina':>10} {'Score saath':>11} | {'Action saath':<12}")
    print("-" * 70)
    for s, df, price, ldcp, rf, a in rows:
        r2 = rf["market"]["r2"] or 0.0
        v = -1.0 * r2
        if rf["class"] == "ILLIQUID":
            v = min(v, -0.5)
        b = evaluate(df, price, ldcp, regime=v)
        print(f"{s:<7} {rf['class']:<13} {v:>+7.2f} | {a['score']:>+10.1f} {b['score']:>+11.1f} | {b['action']:<12}")

    print("\nKya dekhna hai: INDEX_LINKED stocks ka score market ke saath zyada hilna chahiye, "
          "INDEPENDENT ka taqreeban nahi, aur ILLIQUID ko bear market mein -0.5 tak penalty.")
