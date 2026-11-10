"""Beta-aware market regime.

Maqsad: KSE-100 ka bull/bear filter har stock par utna hi lage jitna index us stock ko asal mein chalata hai.

  * Weekly beta / correlation  -> daily ke muqable illiquid stocks ka "naqli low beta" kam dikhata hai
  * Dimson beta (daily, lag+lead) -> der se react karne wale stocks ka asal beta
  * Zero-move days %           -> stock trade hi nahi hota to beta par bharosa nahi
  * R^2 weighting              -> index stock ka kitna hissa explain karta hai, filter ka utna hi asar
  * Sector fallback            -> jo stock index se alag chalta hai, us par uske sector ka regime

Saare core functions pure hain (pandas Series in, numbers out), is liye live aur backtest dono
inhein bina network ke "as-of" date tak ke data par chala sakte hain (look-ahead nahi).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .indicators import ema

# ---------------------------------------------------------------- settings
LOOKBACK_WEEKS = 52          # beta/corr window
MIN_WEEKS = 26               # is se kam history -> stats unreliable
ZERO_MOVE_ILLIQUID = 15.0    # % din jin mein close nahi hila -> ILLIQUID
R2_LINKED = 0.25             # R^2 >= is -> INDEX_LINKED
INDEX_SYMBOLS = ("KSE100",)  # SCSTrade par index ka symbol (pehla jo data de)

# market proxy agar asal KSE-100 data na mile (bade, liquid stocks; equal-weight)
PROXY_MEMBERS = ["OGDC", "PPL", "POL", "MARI", "LUCK", "SYS", "TRG", "HUBC", "FFC", "EFERT",
                 "MCB", "UBL", "HBL", "MEBL", "BAHL", "PSO", "DGKC", "MLCF", "FCCL", "ENGROH"]


# ---------------------------------------------------------------- helpers
def _clip(x, a=-1.0, b=1.0):
    return float(max(a, min(b, x)))


def _sgn(x):
    return 1.0 if x > 0 else -1.0 if x < 0 else 0.0


def equal_weight_index(closes: dict[str, pd.Series], exclude: str | None = None) -> pd.Series | None:
    """Daily closes ka equal-weight index (base 100). `exclude` = jis stock ka analysis ho raha hai."""
    cols = {s: c for s, c in closes.items() if s != exclude and c is not None and len(c) > 30}
    if len(cols) < 2:
        return None
    px = pd.DataFrame(cols).sort_index()
    rets = px.pct_change(fill_method=None)
    rets = rets.where(rets.abs() < 0.25)          # data errors / corporate actions ka asar kam
    idx_ret = rets.mean(axis=1, skipna=True).fillna(0.0)
    return 100 * (1 + idx_ret).cumprod()


def _weekly(close: pd.Series) -> pd.Series:
    return close.resample("W-FRI").last().dropna()


def dimson_beta(stock_ret: pd.Series, mkt_ret: pd.Series) -> float | None:
    """Daily returns par Dimson (1979) beta: stock_t ~ m_{t-1} + m_t + m_{t+1}, betas ka jor."""
    df = pd.DataFrame({"s": stock_ret, "m": mkt_ret}).dropna()
    if len(df) < 60:
        return None
    X = pd.concat([df["m"].shift(1), df["m"], df["m"].shift(-1)], axis=1).dropna()
    y = df["s"].loc[X.index]
    X = np.column_stack([np.ones(len(X)), X.values])
    try:
        coef = np.linalg.lstsq(X, y.values, rcond=None)[0]
    except np.linalg.LinAlgError:
        return None
    return float(coef[1:].sum())


# ---------------------------------------------------------------- core stats
def beta_stats(stock_close: pd.Series, bench_close: pd.Series,
               lookback_weeks: int = LOOKBACK_WEEKS) -> dict:
    """Stock vs benchmark (market ya sector) — dono series as-of date tak kati hui honi chahiyein."""
    out = {"weekly_beta": None, "weekly_corr": None, "r2": 0.0, "dimson_beta": None,
           "zero_move_pct": None, "weeks": 0, "reliable": False}
    if stock_close is None or bench_close is None or len(stock_close) < 30:
        return out

    start = stock_close.index[-1] - pd.Timedelta(weeks=lookback_weeks)
    s_d = stock_close[stock_close.index > start]
    b_d = bench_close[(bench_close.index > start) & (bench_close.index <= stock_close.index[-1])]

    s_ret_d = s_d.pct_change(fill_method=None).dropna()
    out["zero_move_pct"] = round(float((s_ret_d == 0).mean() * 100), 1) if len(s_ret_d) else None

    w = pd.DataFrame({"s": _weekly(s_d).pct_change(fill_method=None),
                      "b": _weekly(b_d).pct_change(fill_method=None)}).dropna()
    out["weeks"] = len(w)
    if len(w) >= 8 and w["b"].var() > 0:
        beta = float(np.cov(w["s"], w["b"])[0, 1] / w["b"].var())
        corr = float(w["s"].corr(w["b"]))
        out.update(weekly_beta=round(beta, 2), weekly_corr=round(corr, 2),
                   r2=round(max(0.0, corr) ** 2, 3))   # ulta correlation = filter ka asar nahi
    db = dimson_beta(s_ret_d, b_d.pct_change(fill_method=None))
    out["dimson_beta"] = round(db, 2) if db is not None else None
    out["reliable"] = out["weeks"] >= MIN_WEEKS
    return out


def classify(stats: dict) -> str:
    """INDEX_LINKED | INDEPENDENT | ILLIQUID | UNKNOWN"""
    if not stats.get("reliable"):
        return "UNKNOWN"
    if stats.get("zero_move_pct") is not None and stats["zero_move_pct"] >= ZERO_MOVE_ILLIQUID:
        return "ILLIQUID"               # beta kam dikhta hai kyunke trade hi nahi hota — azad nahi
    if stats["r2"] >= R2_LINKED:
        return "INDEX_LINKED"
    return "INDEPENDENT"


def trend_regime(close: pd.Series) -> float | None:
    """Index/sector ka regime [-1, +1]: price vs EMA200, EMA50 vs EMA200, EMA50 ki dhalaan."""
    if close is None or len(close) < 60:
        return None
    long_n = 200 if len(close) >= 200 else 100
    e_long, e50 = ema(close, long_n), ema(close, 50)
    c = float(close.iloc[-1])
    slope = (float(e50.iloc[-1]) - float(e50.iloc[-11])) / float(e50.iloc[-11]) if len(e50) > 11 else 0.0
    return round(0.45 * _sgn(c - e_long.iloc[-1]) + 0.30 * _sgn(e50.iloc[-1] - e_long.iloc[-1])
                 + 0.25 * _clip(slope / 0.03), 3)


def relative_strength(stock_close: pd.Series, bench_close: pd.Series, days: int = 126) -> float | None:
    """~6 mahine mein stock benchmark se kitna aage/peeche (fraction). Sirf report ke liye."""
    if stock_close is None or bench_close is None or len(stock_close) <= days:
        return None
    b = bench_close[bench_close.index <= stock_close.index[-1]]
    if len(b) <= days:
        return None
    return round(float(stock_close.iloc[-1] / stock_close.iloc[-days - 1]
                       - b.iloc[-1] / b.iloc[-days - 1]), 3)


def regime_factor(stock_close: pd.Series, market_close: pd.Series | None,
                  sector_close: pd.Series | None = None) -> dict:
    """Scoring ke liye 'regime' factor [-1, +1] + explanation.

    factor = R2_mkt * market_regime + (1 - R2_mkt) * R2_sector * sector_regime
    ILLIQUID stocks: market regime poore wazan (R^2 = 1) se — unka asal risk hum andaza nahi laga sakte,
    is liye conservative hissa unhein bhi milta hai jab market giri hui ho (sirf manfi taraf).
    """
    m_stats = beta_stats(stock_close, market_close) if market_close is not None else {"r2": 0.0, "reliable": False}
    s_stats = beta_stats(stock_close, sector_close) if sector_close is not None else {"r2": 0.0, "reliable": False}
    cls = classify(m_stats)
    m_reg = trend_regime(market_close[market_close.index <= stock_close.index[-1]]) if market_close is not None else None
    s_reg = trend_regime(sector_close[sector_close.index <= stock_close.index[-1]]) if sector_close is not None else None

    r2m = m_stats["r2"] if m_stats.get("reliable") else 0.0
    r2s = s_stats["r2"] if s_stats.get("reliable") else 0.0
    value = 0.0
    if m_reg is not None:
        value += r2m * m_reg
    if s_reg is not None:
        value += (1 - r2m) * r2s * s_reg
    if cls == "ILLIQUID" and m_reg is not None and m_reg < 0:
        value = min(value, 0.5 * m_reg)            # bear market mein illiquid ko azad na samjho

    return {
        "value": round(_clip(value), 3), "class": cls,
        "market_regime": m_reg, "sector_regime": s_reg,
        "market": {k: m_stats.get(k) for k in ("weekly_beta", "weekly_corr", "r2", "dimson_beta",
                                               "zero_move_pct", "weeks")},
        "sector_r2": s_stats.get("r2"),
        "rs_vs_market": relative_strength(stock_close, market_close) if market_close is not None else None,
    }


def describe(rf: dict) -> str:
    names = {"INDEX_LINKED": "Index-linked", "INDEPENDENT": "Index se azad",
             "ILLIQUID": "Illiquid (beta unreliable)", "UNKNOWN": "Data kam"}
    m = rf.get("market") or {}
    reg = rf.get("market_regime")
    mkt = "bullish" if reg is not None and reg > 0.3 else "bearish" if reg is not None and reg < -0.3 else "neutral"
    parts = [f"{names.get(rf['class'], rf['class'])}"]
    if m.get("weekly_beta") is not None:
        parts.append(f"beta {m['weekly_beta']}, R² {m['r2']}")
    parts.append(f"market {mkt}")
    if rf.get("sector_regime") is not None:
        parts.append(f"sector regime {rf['sector_regime']:+.2f}")
    return "Regime: " + ", ".join(parts) + f" → asar {rf['value']:+.2f}"


# ---------------------------------------------------------------- live data (network/DB)
def sector_of(symbol: str) -> tuple[str | None, list[str]]:
    from .sector_rotation import SECTOR_MAP
    for name, members in SECTOR_MAP.items():
        if symbol in members:
            return name, members
    return None, []


def load_market_close(days: int = 1500) -> tuple[pd.Series | None, str]:
    """Asal KSE-100 (SCSTrade) — na mile to large-cap equal-weight proxy. (series, source)"""
    from . import data
    for sym in INDEX_SYMBOLS:
        try:
            df = data.fetch_history(sym, "D", days)
            if df is not None and len(df) >= 200:
                return df["close"], sym
        except Exception:
            pass
    closes = {}
    for s in PROXY_MEMBERS:
        try:
            df = data.fetch_history(s, "D", days)
            if df is not None:
                closes[s] = df["close"]
        except Exception:
            pass
    return equal_weight_index(closes), "PROXY_EW_LARGECAP"


def live_regime(symbol: str, stock_close: pd.Series) -> dict | None:
    """Analyzer ke liye. Kabhi exception nahi phenkta — masla ho to None (factor skip)."""
    try:
        from . import data
        mkt, src = load_market_close()
        _, members = sector_of(symbol)
        sector_closes = {}
        for s in members:
            if s == symbol:
                continue
            df = data.fetch_history(s, "D", 1500)
            if df is not None:
                sector_closes[s] = df["close"]
        sec = equal_weight_index(sector_closes) if sector_closes else None
        rf = regime_factor(stock_close, mkt, sec)
        rf["market_source"] = src
        return rf
    except Exception as e:
        print("regime error:", e)
        return None
