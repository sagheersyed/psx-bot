"""Beta-aware regime filter ka asar: baseline vs regime, stock group ke hisaab se.

Usage:
    python scripts/regime_backtest.py                 # candles.db ke saare stocks (offline)
    python scripts/regime_backtest.py OGDC LUCK BUXL  # sirf ye
    python scripts/regime_backtest.py --cost 0.5      # round-trip cost % (default 0.4)

Data sirf data/candles.db se aata hai (koi network nahi). Market = asal KSE100 agar DB mein ho,
warna large-cap equal-weight proxy. Har trade ka group (INDEX_LINKED / INDEPENDENT / ILLIQUID)
signal ke DIN tak ke data se tay hota hai.
"""
import argparse
import sqlite3
import sys
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import config  # noqa: E402
from psx import regime as rg  # noqa: E402
from psx.backtest import run_backtest, summarize  # noqa: E402

GROUPS = ("INDEX_LINKED", "INDEPENDENT", "ILLIQUID", "UNKNOWN")


def load_db() -> dict[str, pd.DataFrame]:
    con = sqlite3.connect(config.CANDLES_DB_PATH)
    df = pd.read_sql("SELECT symbol, timestamp, open, high, low, close, volume FROM daily_candles",
                     con, parse_dates=["timestamp"])
    con.close()
    return {s: g.set_index("timestamp").sort_index()[["open", "high", "low", "close", "volume"]]
            for s, g in df.groupby("symbol")}


def market_series(all_df):
    for sym in rg.INDEX_SYMBOLS:
        if sym in all_df and len(all_df[sym]) >= 200:
            return all_df[sym]["close"], sym
    closes = {s: all_df[s]["close"] for s in rg.PROXY_MEMBERS if s in all_df}
    return rg.equal_weight_index(closes), "PROXY_EW_LARGECAP"


def sector_series(sym, all_df):
    _, members = rg.sector_of(sym)
    closes = {s: all_df[s]["close"] for s in members if s != sym and s in all_df}
    return rg.equal_weight_index(closes) if closes else None


def _job(args):
    sym, df, mkt, sec, cost = args
    base = run_backtest(df, market_close=mkt, sector_close=sec, cost_pct=cost, apply_regime=False)
    reg = run_backtest(df, market_close=mkt, sector_close=sec, cost_pct=cost, apply_regime=True)
    for t in base + reg:
        t["sym"] = sym
    return base, reg


def line(name, trades):
    if not trades:
        return f"  {name:<14} {'-':>6}"
    s = summarize(trades, "r_net")
    return (f"  {name:<14} {s['n']:>6} {s['win_rate']:>7}% {s['avg_r']:>+8.3f} "
            f"{(s['profit_factor'] or 0):>6.2f} {np.median([t['r_net'] for t in trades]):>+8.3f}")


def report(title, base, reg, keyfn, keys):
    print(f"\n=== {title} ===")
    print(f"  {'':<14} {'trades':>6} {'win':>8} {'avgR':>8} {'PF':>6} {'medR':>8}")
    for k in keys:
        b = [t for t in base if keyfn(t) == k]
        r = [t for t in reg if keyfn(t) == k]
        if not b and not r:
            continue
        print(f" [{k}]")
        print(line("baseline", b))
        print(line("regime", r))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("symbols", nargs="*")
    ap.add_argument("--cost", type=float, default=0.4, help="round-trip cost %% (brokerage+fees+CVT)")
    ap.add_argument("--min-bars", type=int, default=400)
    a = ap.parse_args()

    all_df = load_db()
    mkt, src = market_series(all_df)
    if mkt is None:
        sys.exit("Market series nahi ban saki — candles.db mein large-cap data chahiye.")
    syms = [s.upper() for s in a.symbols] or sorted(all_df)
    syms = [s for s in syms if s in all_df and s not in rg.INDEX_SYMBOLS and len(all_df[s]) >= a.min_bars]
    print(f"Market: {src} | stocks: {len(syms)} | cost: {a.cost}% round-trip")

    jobs = [(s, all_df[s], mkt, sector_series(s, all_df), a.cost) for s in syms]
    base, reg = [], []
    with ProcessPoolExecutor() as ex:
        for b, r in ex.map(_job, jobs):
            base += b
            reg += r

    report("OVERALL (net of costs)", base, reg, lambda t: "ALL", ["ALL"])
    report("BY GROUP (group = signal ke din ka classification)", base, reg,
           lambda t: t["regime_class"] or "UNKNOWN", GROUPS)
    report("BY YEAR", base, reg, lambda t: t["date"][:4], sorted({t["date"][:4] for t in base + reg}))

    # market regime ke hisaab se: filter bear market mein index-linked ko roke, bull mein nahi
    def mk(t):
        v = t.get("regime_value")
        if t["regime_class"] != "INDEX_LINKED" or v is None:
            return "other"
        return "linked, mkt+" if v > 0.15 else "linked, mkt-" if v < -0.15 else "linked, mkt~0"
    report("INDEX_LINKED by market regime", base, reg, mk, ["linked, mkt+", "linked, mkt~0", "linked, mkt-"])

    per = defaultdict(list)
    for t in base:
        per[t["sym"]].append(t["r_net"])
    top = sorted(((s, sum(v)) for s, v in per.items()), key=lambda x: -abs(x[1]))[:5]
    print("\nSab se zyada asar daalne wale stocks (baseline, total R):",
          ", ".join(f"{s} {v:+.1f}" for s, v in top))
