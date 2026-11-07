"""analyze_stock ka end-to-end test (network ke baghair, mock data)."""
import sys, json
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
from psx import data, analyzer
from psx.formatter import format_whatsapp_message
from tests.test_engine import make_df


def _fake_history(symbol, res="D", days=400):
    n = {"D": 400, "60": 200, "30": 200, "15": 200, "5": 200, "1": 100}[res]
    df = make_df(n=n, seed=hash(res) % 50)
    if res != "D":
        df.index = pd.date_range("2026-10-01 09:15", periods=n, freq="15min")
    return df


def test_pipeline():
    data.fetch_history = _fake_history
    data.fetch_quote = lambda s: {"current_price": None, "ldcp": None, "pe_ratio": 6.1, "eps": 12.5}
    data.fetch_fundamentals = lambda s: {"book_value": 150.0, "trailing_pe": None, "dividend_yield": 5.0}
    r = analyzer.analyze_stock("TEST", log=False)
    json.dumps(r)                       # JSON-safe hona zaroori hai (Flask jsonify)
    for k in ("verdict", "buy_zone", "stop_loss", "target_1", "matrix", "smc", "confluence_score", "prediction_narrative"):
        assert k in r, k
    msg = format_whatsapp_message(r)
    print(msg)
    assert "TEST" in msg


if __name__ == "__main__":
    test_pipeline(); print("\nPASS test_pipeline")
