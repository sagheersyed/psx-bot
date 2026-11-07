"""Data layer: SCSTrade candles, PSX DPS quote, fundamentals — cache + retry ke saath."""
import json
import time
import threading
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

import config

try:
    from . import candle_store
    candle_store.init_db()
except Exception:
    pass

_cache: dict = {}
_lock = threading.Lock()


def _cached(key, ttl, producer):
    now = time.time()
    with _lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < ttl:
            return hit[1]
    value = producer()
    if value is not None:  # failed fetch ko cache nahi karte
        with _lock:
            _cache[key] = (now, value)
    return value


def _http_get(url: str, timeout: int = 12, retries: int = 2) -> str | None:
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=config.HEADERS)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", errors="ignore")
        except Exception:
            if attempt < retries:
                time.sleep(0.6 * (attempt + 1))
    return None


def now_pkt() -> datetime:
    return datetime.now(ZoneInfo(config.TZ))


def is_session_open(ts: datetime | None = None) -> bool:
    ts = ts or now_pkt()
    if ts.weekday() >= 5:
        return False
    hm = (ts.hour, ts.minute)
    return config.SESSION_OPEN <= hm <= config.SESSION_CLOSE


def _clean_candles(df: pd.DataFrame) -> pd.DataFrame:
    df = df[~df.index.duplicated(keep="last")].sort_index()
    df = df.dropna(subset=["open", "high", "low", "close"])
    df = df[(df["close"] > 0) & (df["high"] >= df["low"])]
    return df


def _fetch_scs_http(symbol: str, resolution: str, days: int) -> pd.DataFrame | None:
    now = int(time.time())
    url = (f"https://chart.scstrade.com/history?symbol={symbol}"
           f"&resolution={resolution}&from={now - days * 86400}&to={now}")
    body = _http_get(url)
    if not body:
        return None
    try:
        data = json.loads(body)
        if data.get("s") != "ok" or not data.get("t"):
            return None
        idx = (pd.to_datetime(data["t"], unit="s", utc=True)
               .tz_convert(config.TZ).tz_localize(None))   # UTC -> Karachi time
        df = pd.DataFrame({
            "open": data["o"], "high": data["h"], "low": data["l"],
            "close": data["c"], "volume": data["v"],
        }, index=idx).astype(float)
        if resolution == "D":
            df.index = df.index.normalize()
        df.index.name = "timestamp"
        df = _clean_candles(df)
        if resolution == "1":  # 1M: sirf aakhri trading session rakho
            last_day = df.index[-1].normalize()
            df = df[df.index.normalize() == last_day]
        return df if len(df) else None
    except Exception:
        return None


def _fetch_history_raw(symbol: str, resolution: str, days: int) -> pd.DataFrame | None:
    # If daily, use the persistent intelligent candle store
    if resolution == "D":
        from . import candle_store
        return candle_store.get_daily_candles_smart(symbol, days=days, fetch_raw_func=_fetch_scs_http)

    # If weekly, monthly, or yearly, fetch daily candles and resample with institutional precision
    if resolution in ("W", "MO", "M", "Y"):
        df_d = _fetch_history_raw(symbol, "D", days=max(days, 1200))
        if df_d is None or len(df_d) == 0:
            return None
        try:
            rule = "W-FRI" if resolution == "W" else ("ME" if resolution in ("MO", "M") else "YE")
            resampled = df_d.resample(rule).agg({
                "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"
            }).dropna()
            return _clean_candles(resampled) if len(resampled) else None
        except Exception:
            return None

    # Intraday resolutions ("1", "5", "15", "30", "60")
    return _fetch_scs_http(symbol, resolution, days)


def fetch_history(symbol: str, resolution: str = "D", days: int = 400) -> pd.DataFrame | None:
    symbol = symbol.upper().strip()
    ttl = config.TTL_DAILY if resolution in ("D", "W", "MO", "M", "Y") else config.TTL_INTRADAY
    df = _cached(("hist", symbol, resolution, days), ttl,
                 lambda: _fetch_history_raw(symbol, resolution, days))
    return None if df is None else df.copy()


def fetch_quote(symbol: str) -> dict:
    """Live quote + P/E + EPS + LDCP + 52-Week Range PSX Data Portal se."""
    symbol = symbol.upper().strip()

    def produce():
        from bs4 import BeautifulSoup
        html = _http_get(f"https://dps.psx.com.pk/company/{symbol}", timeout=10, retries=1)
        if not html:
            return None
        info = {"current_price": None, "ldcp": None, "pe_ratio": None, "eps": None, "market_cap": None, "shares": None}
        soup = BeautifulSoup(html, "html.parser")

        def num(txt):
            try:
                return float(txt.replace("Rs.", "").replace(",", "").replace("(", "-").replace(")", "").strip())
            except Exception:
                return None

        pd_ = soup.find("div", class_="quote__price")
        if pd_:
            info["current_price"] = num(pd_.get_text())

        # Scrape stats items (support both stats_item and stats__item)
        for div in soup.find_all("div", class_=lambda c: c and ("stats_item" in c or "stats__item" in c)):
            t = div.find("div", class_=lambda c: c and ("stats_label" in c or "stats_title" in c or "stats__title" in c))
            v = div.find("div", class_=lambda c: c and ("stats_value" in c or "stats__value" in c))
            if t and v:
                key = t.get_text().strip().lower()
                val_txt = v.get_text().strip()
                if "ldcp" in key:
                    info["ldcp"] = num(val_txt)
                elif "p/e" in key:
                    info["pe_ratio"] = num(val_txt)
                elif "market cap" in key:
                    info["market_cap"] = num(val_txt)
                elif "shares" in key and "free" not in key:
                    info["shares"] = num(val_txt)

        # Scrape EPS from financials table
        for tr in soup.find_all("tr"):
            row = [td.get_text(strip=True) for td in tr.find_all(["th", "td"])]
            if row and row[0].upper() == "EPS" and len(row) > 1:
                val = num(row[1])
                if val is not None:
                    info["eps"] = val
                    break

        return info

    return _cached(("quote", symbol), config.TTL_INTRADAY, produce) or \
        {"current_price": None, "ldcp": None, "pe_ratio": None, "eps": None}


def fetch_fundamentals(symbol: str) -> dict:
    """Book value / trailing P/E / dividend yield."""
    symbol = symbol.upper().strip()

    def produce():
        out = {"book_value": None, "trailing_pe": None, "dividend_yield": None, "eps": None}
        try:
            import yfinance as yf
            info = yf.Ticker(f"{symbol}.KA").info or {}
            out["book_value"] = info.get("bookValue")
            out["trailing_pe"] = info.get("trailingPE") or info.get("forwardPE")
            out["eps"] = info.get("trailingEps") or info.get("epsTrailingTwelveMonths")
            dy = info.get("dividendYield") or info.get("trailingAnnualDividendYield")
            if dy is not None:
                out["dividend_yield"] = round(dy * 100, 2) if dy < 1.0 else round(dy, 2)
        except Exception:
            pass
        return out

    return _cached(("fund", symbol), config.TTL_FUNDAMENTALS, produce)
