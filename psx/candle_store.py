"""
psx/candle_store.py: Smart Persistent Storage for Daily PSX Candles.
- Stores historical daily candles permanently in SQLite (data/candles.db).
- Differentiates finalized candles (past days) vs intraday forming candles (today during market hours).
- Zero network calls when market is closed and data is already finalized.
- Incremental updates during market hours or post-close, fetching only missing/recent candles.
- Graceful offline fallback to cached SQLite data if network/SCSTrade blips.
"""

import sqlite3
import threading
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import pandas as pd

import config

_db_lock = threading.Lock()
_mem_cache: dict = {}


def _get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(str(config.CANDLES_DB_PATH), timeout=30.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def init_db():
    """Initializes candles SQLite table and index."""
    with _db_lock:
        with _get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS daily_candles (
                    symbol TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    open REAL NOT NULL,
                    high REAL NOT NULL,
                    low REAL NOT NULL,
                    close REAL NOT NULL,
                    volume REAL NOT NULL,
                    is_final INTEGER DEFAULT 1,
                    updated_at INTEGER NOT NULL,
                    PRIMARY KEY (symbol, timestamp)
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_daily_sym_time 
                ON daily_candles(symbol, timestamp)
            """)
            conn.commit()


def now_pkt() -> datetime:
    return datetime.now(ZoneInfo(config.TZ))


def get_market_status(ts: datetime | None = None) -> tuple[str, str, str]:
    """
    Evaluates current PSX market session status.
    Returns:
      status: 'WEEKEND', 'PRE_MARKET', 'OPEN', 'POST_CLOSE'
      today_str: 'YYYY-MM-DD'
      expected_last_trading_day: 'YYYY-MM-DD'
    """
    ts = ts or now_pkt()
    weekday = ts.weekday()  # Mon=0 ... Fri=4, Sat=5, Sun=6
    today_str = ts.strftime("%Y-%m-%d")
    hm = (ts.hour, ts.minute)

    if weekday == 5:  # Saturday -> Last trading day was Friday (1 day back)
        last_trading = ts - timedelta(days=1)
        return "WEEKEND", today_str, last_trading.strftime("%Y-%m-%d")
    elif weekday == 6:  # Sunday -> Last trading day was Friday (2 days back)
        last_trading = ts - timedelta(days=2)
        return "WEEKEND", today_str, last_trading.strftime("%Y-%m-%d")

    # Mon - Fri
    if hm < (9, 0):  # Pre-market before 9:00 AM
        days_back = 3 if weekday == 0 else 1
        last_trading = ts - timedelta(days=days_back)
        return "PRE_MARKET", today_str, last_trading.strftime("%Y-%m-%d")
    elif hm >= (16, 0):  # Post-close after 4:00 PM (16:00)
        return "POST_CLOSE", today_str, today_str
    else:  # Market session active (09:00 to 16:00)
        return "OPEN", today_str, today_str


def load_candles_from_db(symbol: str, days: int = 1500) -> pd.DataFrame | None:
    """Reads stored candles for symbol from SQLite."""
    try:
        with _db_lock:
            with _get_connection() as conn:
                df = pd.read_sql_query(
                    """
                    SELECT timestamp, open, high, low, close, volume, is_final, updated_at
                    FROM daily_candles
                    WHERE symbol = ?
                    ORDER BY timestamp ASC
                    """,
                    conn,
                    params=(symbol,)
                )
        if df.empty:
            return None

        df["dt"] = pd.to_datetime(df["timestamp"])
        df.set_index("dt", inplace=True)
        df.index.name = "timestamp"

        # Apply days filter if requested
        if days and len(df) > 0:
            cutoff = now_pkt().date() - timedelta(days=days)
            df_filtered = df[df.index.date >= cutoff]
            if len(df_filtered) >= 20:
                df = df_filtered

        return df
    except Exception:
        return None


def save_candles_to_db(symbol: str, df: pd.DataFrame, default_is_final: int = 1):
    """
    Saves or updates daily candles in SQLite.
    Preserves is_final=1 for historical dates.
    """
    if df is None or df.empty:
        return

    now_ts = int(time.time())
    today_str = now_pkt().strftime("%Y-%m-%d")
    status, _, _ = get_market_status()

    records = []
    for idx_val, row in df.iterrows():
        t_str = idx_val.strftime("%Y-%m-%d") if hasattr(idx_val, "strftime") else str(idx_val)[:10]

        # Determine is_final
        if t_str < today_str:
            is_final = 1
        elif status == "OPEN":
            is_final = 0  # Market active today, candle not yet final
        else:
            is_final = 1  # Post-close or weekend, finalized

        records.append((
            symbol,
            t_str,
            float(row["open"]),
            float(row["high"]),
            float(row["low"]),
            float(row["close"]),
            float(row["volume"]),
            is_final,
            now_ts
        ))

    with _db_lock:
        with _get_connection() as conn:
            conn.executemany("""
                INSERT INTO daily_candles 
                (symbol, timestamp, open, high, low, close, volume, is_final, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, timestamp) DO UPDATE SET
                    open = excluded.open,
                    high = excluded.high,
                    low = excluded.low,
                    close = excluded.close,
                    volume = excluded.volume,
                    is_final = excluded.is_final,
                    updated_at = excluded.updated_at
            """, records)
            conn.commit()


def get_daily_candles_smart(symbol: str, days: int = 1500, fetch_raw_func=None) -> pd.DataFrame | None:
    """
    Master intelligent daily candle fetcher:
    1. Checks SQLite storage.
    2. If fresh and market is closed -> 0 network calls, instant return.
    3. If incremental update needed -> fetches only recent window, updates DB.
    4. If not in DB -> fetches 1500+ days once, stores in DB.
    5. Falls back cleanly to SQLite data if network/SCSTrade is unavailable.
    """
    symbol = symbol.upper().strip()
    status, today_str, exp_last_trading = get_market_status()

    # Step 1: Load what we currently have in SQLite
    db_df = load_candles_from_db(symbol, days=None)  # load full history

    now_sec = time.time()
    needs_fetch = False
    fetch_days = 1500  # default full fetch if empty

    if db_df is None or len(db_df) < 30:
        # Stock not in DB or has too few candles -> Must do full fetch
        needs_fetch = True
        fetch_days = max(days, 1500)
    else:
        last_row = db_df.iloc[-1]
        last_date_str = db_df.index[-1].strftime("%Y-%m-%d")
        last_is_final = int(last_row.get("is_final", 1))
        last_updated_at = float(last_row.get("updated_at", 0))

        if status == "WEEKEND":
            # Weekend: Market closed.
            # If we already have up to expected last trading day (Friday) and it's final:
            if last_is_final == 1 and last_date_str >= exp_last_trading:
                needs_fetch = False
            else:
                needs_fetch = True
                fetch_days = 10  # only need recent bars to catch Friday's close

        elif status == "PRE_MARKET":
            # Mon-Fri before 09:00:
            if last_is_final == 1 and last_date_str >= exp_last_trading:
                needs_fetch = False
            else:
                needs_fetch = True
                fetch_days = 10

        elif status == "POST_CLOSE":
            # Mon-Fri after 16:00:
            # If today's candle is already stored AND marked final:
            if last_date_str == today_str and last_is_final == 1:
                needs_fetch = False
            else:
                # Today's closing candle needs to be fetched once and stored as final!
                needs_fetch = True
                fetch_days = 7

        elif status == "OPEN":
            # Market is open right now (09:00 - 16:00 Mon-Fri)
            # Intraday rate-limiting: only fetch if last update was > 45 seconds ago
            if now_sec - last_updated_at > config.TTL_INTRADAY:
                needs_fetch = True
                fetch_days = 5  # only need recent days to append/update today's forming candle
            else:
                needs_fetch = False

    # Step 2: Fetch from network if required
    if needs_fetch and fetch_raw_func:
        try:
            raw_df = fetch_raw_func(symbol, "D", days=fetch_days)
            if raw_df is not None and len(raw_df) > 0:
                save_candles_to_db(symbol, raw_df)
                # Reload updated dataframe from DB
                db_df = load_candles_from_db(symbol, days=None)
        except Exception:
            # In case of network error, db_df (if exists) serves as graceful offline fallback
            pass

    if db_df is None or db_df.empty:
        return None

    # Step 3: Return clean OHLCV DataFrame matching expected format
    res_df = db_df[["open", "high", "low", "close", "volume"]].copy()
    if days and len(res_df) > 0:
        cutoff = now_pkt().date() - timedelta(days=days)
        filtered = res_df[res_df.index.date >= cutoff]
        if len(filtered) >= 10:
            res_df = filtered

    return res_df
