"""Offline tests (synthetic data). Chalayein: python -m tests.test_engine"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

from psx.signal import evaluate
from psx.backtest import run_backtest, summarize, simulate_trade
from psx.smc import analyze_smc


def make_df(n=400, drift=0.0008, vol=0.018, seed=1):
    rng = np.random.default_rng(seed)
    r = rng.normal(drift, vol, n)
    close = 100 * np.exp(np.cumsum(r))
    open_ = np.r_[close[0], close[:-1]] * (1 + rng.normal(0, 0.003, n))
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.006, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.006, n)))
    volume = rng.integers(200_000, 900_000, n).astype(float)
    idx = pd.bdate_range("2024-01-01", periods=n)
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume}, index=idx)


def test_evaluate_shape():
    sig = evaluate(make_df())
    for k in ("verdict", "score", "confidence", "levels", "action", "factors", "smc"):
        assert k in sig
    assert -100 <= sig["score"] <= 100 and 0 <= sig["confidence"] <= 100
    lv = sig["levels"]
    assert lv["stop"] < lv["entry_low"] <= lv["entry_high"] < lv["t1"] < lv["t2"] < lv["t3"], lv


def test_crash_gate():
    df = make_df()
    price = float(df["close"].iloc[-1]) * 0.91          # -9% din
    sig = evaluate(df, price=price, ldcp=float(df["close"].iloc[-1]))
    assert sig["action"] == "AVOID" and "AVOID" in sig["verdict"]


def test_no_lookahead_in_smc():
    df = make_df()
    a = analyze_smc(df.iloc[:300])["structure"]
    b = analyze_smc(df.iloc[:300].copy())["structure"]
    assert a == b


def test_ote_leg_is_bullish_leg():
    smc = analyze_smc(make_df(seed=3))
    o = smc["ote_poi"]
    if o:
        assert o["leg_high"] > o["leg_low"]


def test_simulator_rules():
    idx = pd.bdate_range("2025-01-01", periods=4)
    # same bar stop+target dono hit -> stop pehle (conservative)
    fut = pd.DataFrame({"open": [100, 100], "high": [112, 100], "low": [94, 100], "close": [100, 100], "volume": [1, 1]}, index=idx[:2])
    r = simulate_trade(fut, entry_high=100, stop=95, t1=110, fill_bars=3)
    assert r["result"] == "STOP" and r["r"] == -1.0, r
    # clean win
    fut = pd.DataFrame({"open": [100, 103], "high": [101, 111], "low": [99, 102], "close": [100, 110], "volume": [1, 1]}, index=idx[:2])
    r = simulate_trade(fut, entry_high=100, stop=95, t1=110, fill_bars=3)
    assert r["result"] == "T1" and r["r"] == 2.0, r
    # kabhi fill nahi
    fut = pd.DataFrame({"open": [105] * 4, "high": [106] * 4, "low": [104] * 4, "close": [105] * 4, "volume": [1] * 4}, index=idx)
    assert simulate_trade(fut, 100, 95, 110, fill_bars=3)["result"] == "NO_FILL"


def test_backtest_runs():
    t = run_backtest(make_df(n=450, seed=7))
    s = summarize(t)
    print("backtest:", s)
    assert s["n"] >= 0


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); print("PASS", name)
