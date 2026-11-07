"""Indicators — sirf pandas/numpy (extra library ki zaroorat nahi)."""
import numpy as np
import pandas as pd


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False, min_periods=1).mean()


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    d = close.diff()
    up, dn = d.clip(lower=0), -d.clip(upper=0)
    au = up.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    ad = dn.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    out = 100 - 100 / (1 + au / ad.replace(0, np.nan))
    out[(ad == 0) & (au > 0)] = 100.0
    return out.fillna(50.0)


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    pc = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(), (df["low"] - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False, min_periods=1).mean()


def cmf(df: pd.DataFrame, n: int = 20) -> pd.Series:
    rng = (df["high"] - df["low"]).replace(0, np.nan)
    mfm = (((df["close"] - df["low"]) - (df["high"] - df["close"])) / rng).fillna(0.0)
    vol_sum = df["volume"].rolling(n, min_periods=2).sum().replace(0, np.nan)
    return ((mfm * df["volume"]).rolling(n, min_periods=2).sum() / vol_sum).fillna(0.0)


def obv(df: pd.DataFrame) -> pd.Series:
    return (np.sign(df["close"].diff().fillna(0)) * df["volume"]).cumsum()


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    c = d["close"]
    for n in (9, 20, 50, 200):
        d[f"ema{n}"] = ema(c, n)
    d["rsi"] = rsi(c)
    d["atr"] = atr(d)
    d["cmf20"] = cmf(d, 20)
    d["cmf5"] = cmf(d, 5)
    d["obv"] = obv(d)
    d["obv_ema"] = ema(d["obv"], 20)
    macd = ema(c, 12) - ema(c, 26)
    d["macd_hist"] = macd - ema(macd, 9)
    return d
