import pytest
import pandas as pd
from datetime import datetime
from psx import candle_store, data, seasonal_backtest

def test_candle_store_initialization():
    candle_store.init_db()
    status, today_str, exp_last_trading = candle_store.get_market_status()
    assert status in ("WEEKEND", "PRE_MARKET", "OPEN", "POST_CLOSE")
    assert len(today_str) == 10
    assert len(exp_last_trading) == 10

def test_candle_store_get_daily_candles_smart():
    # Test with AMBL
    df = data.fetch_history("AMBL", "D", days=1500)
    assert df is not None
    assert len(df) > 30
    assert "close" in df.columns
    assert isinstance(df.index, pd.DatetimeIndex)

    # Subsequent call should load from SQLite
    df_db = candle_store.load_candles_from_db("AMBL")
    assert df_db is not None
    assert len(df_db) >= len(df)

def test_seasonal_backtest_with_candle_store():
    res = seasonal_backtest.backtest_stock_seasonality("AMBL")
    assert res["has_data"] is True
    assert res["symbol"] == "AMBL"
    assert "current_month" in res
    assert res["current_month"]["win_rate"] > 0
    assert "heatmap" in res
    assert len(res["years"]) > 0
