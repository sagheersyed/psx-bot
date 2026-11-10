"""Offline tests (synthetic data). Chalayein: python -m pytest -q tests/test_regime.py"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

from psx import regime as rg
from psx import scoring

IDX = pd.bdate_range("2023-01-02", periods=500)


def _series(rets, start=100.0):
    return pd.Series(start * np.exp(np.cumsum(rets)), index=IDX)


def _market(drift=0.0, seed=0):
    rng = np.random.default_rng(seed)
    return rng.normal(drift, 0.012, len(IDX))


def test_linked_stock_is_index_linked():
    m = _market(seed=1)
    noise = np.random.default_rng(2).normal(0, 0.006, len(IDX))
    st = rg.beta_stats(_series(1.2 * m + noise), _series(m))
    assert rg.classify(st) == "INDEX_LINKED"
    assert 0.9 < st["weekly_beta"] < 1.5 and st["r2"] > 0.5


def test_independent_stock():
    m = _market(seed=3)
    own = np.random.default_rng(4).normal(0, 0.015, len(IDX))
    st = rg.beta_stats(_series(own), _series(m))
    assert rg.classify(st) == "INDEPENDENT" and st["r2"] < 0.1


def test_illiquid_detected_even_if_it_follows_market_with_lag():
    m = _market(seed=5)
    lagged = np.r_[0, m[:-1]]                       # ek din baad react karta hai
    trades = np.random.default_rng(6).random(len(IDX)) > 0.4
    rets = np.where(trades, lagged, 0.0)            # ~40% din koi trade nahi
    st = rg.beta_stats(_series(rets), _series(m))
    assert rg.classify(st) == "ILLIQUID"
    assert st["dimson_beta"] > st["weekly_beta"] * 0.5   # Dimson lag ko pakarta hai


def test_regime_factor_scales_with_r2():
    m = _market(drift=-0.002, seed=7)              # girti hui market
    mkt = _series(m)
    linked = _series(1.0 * m + np.random.default_rng(8).normal(0, 0.004, len(IDX)))
    indep = _series(np.random.default_rng(9).normal(0.001, 0.015, len(IDX)))
    rf_l, rf_i = rg.regime_factor(linked, mkt), rg.regime_factor(indep, mkt)
    assert rf_l["market_regime"] < 0
    assert rf_l["value"] < -0.4                     # index-linked par poora asar
    assert abs(rf_i["value"]) < 0.1                 # azad stock par taqreeban kuch nahi


def test_independent_stock_score_unchanged():
    f = {"trend": 0.5, "momentum": 0.2, "flow": 0.1, "structure": 0.6, "location": 0.0}
    assert scoring.total_score(f) == scoring.total_score({**f, "regime": 0.0})
    assert scoring.total_score({**f, "regime": -1.0}) == round(scoring.total_score(f) - 15, 1)


def test_no_lookahead():
    m = _market(seed=10)
    mkt, st = _series(m), _series(m + np.random.default_rng(11).normal(0, 0.005, len(IDX)))
    cut = IDX[300]
    a = rg.regime_factor(st[st.index <= cut], mkt[mkt.index <= cut])
    b = rg.regime_factor(st[st.index <= cut], mkt)   # market mein future data — asar nahi hona chahiye
    assert a["value"] == b["value"] and a["market"] == b["market"]
