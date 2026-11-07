"""
tests/test_sentinel_confluence.py: Comprehensive validation of Eagle-Eye Sentinel Confluence & Anti-Trap Shielding.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import unittest
from unittest.mock import patch
import pandas as pd
import numpy as np

from psx.smc import detect_sweeps, analyze_smc
from psx.eagle_eye import check_stock_triggers, ALERT_PRIORITY, _COOLDOWN


class TestSentinelConfluence(unittest.TestCase):
    def setUp(self):
        _COOLDOWN.clear()

    def test_detect_sweeps_contains_bars_ago(self):
        # Create a 20 bar dataframe
        idx = pd.bdate_range("2025-01-01", periods=20)
        df = pd.DataFrame({
            "open": [100.0] * 20,
            "high": [105.0] * 20,
            "low": [95.0] * 20,
            "close": [100.0] * 20,
            "volume": [100000.0] * 20
        }, index=idx)
        # Swing low at bar 5 with price 90.0
        sls = [{"index": 5, "time": str(idx[5]), "price": 90.0}]
        shs = [{"index": 6, "time": str(idx[6]), "price": 110.0}]
        
        # Make bar 18 sweep swing low 90.0 (low 88, close 92)
        df.loc[idx[18], "low"] = 88.0
        df.loc[idx[18], "close"] = 92.0
        
        sweeps = detect_sweeps(df, shs, sls, lookback=5)
        self.assertTrue(len(sweeps) >= 1)
        sw = sweeps[-1]
        self.assertEqual(sw["type"], "SSL_SWEEP")
        self.assertIn("bars_ago", sw)
        # Bar 18 out of 20 (index 0..19): bars_ago should be 19 - 18 = 1
        self.assertEqual(sw["bars_ago"], 1)

    @patch("psx.analyzer.analyze_stock")
    @patch("psx.data.fetch_history")
    @patch("psx.volume_sentinel.evaluate_volume_and_price")
    def test_churn_trap_suppresses_bullish_and_support_signals(self, mock_vol, mock_hist, mock_analyze):
        """Simulate DGKC/SNGP scenario: Churn trap at resistance must suppress Turtle Soup and Support POI."""
        mock_analyze.return_value = {
            "current_price": 200.41,
            "score": 10,
            "action": "WAIT",
            "support_1": 198.50,  # near support
            "resistance_1": 203.40,
            "smc": {
                "structure": "RANGE_BOUND",
                "liquidity_sweeps": [
                    {"type": "SSL_SWEEP", "level": 178.50, "bars_ago": 6}  # old sweep
                ]
            }
        }
        mock_hist.return_value = pd.DataFrame({"close": [200.0]*20})
        mock_vol.return_value = {
            "has_signal": True,
            "trigger": "DISTRIBUTION_CHURN_WARNING",
            "badge": "⚠️ VOLUME REJECTION / CHURN TRAP",
            "details": "Elevated volume hit overhead resistance Rs. 203.40.",
            "metrics": {"rvol": 1.65, "turnover_m": 706.89},
            "anti_fakeout_status": "TRAP_BLOCKED"
        }

        alerts = check_stock_triggers("DGKC")
        self.assertEqual(len(alerts), 1)
        alert = alerts[0]
        self.assertEqual(alert["trigger"], "DISTRIBUTION_CHURN_WARNING")
        self.assertEqual(alert["anti_fakeout_status"], "TRAP_BLOCKED")
        # Ensure no contradictory TURTLE_SOUP or SUPPORT POI was generated
        self.assertNotIn("TURTLE_SOUP", alert["trigger"])
        self.assertNotIn("SUPPORT", alert["trigger"])

    @patch("psx.analyzer.analyze_stock")
    @patch("psx.data.fetch_history")
    @patch("psx.volume_sentinel.evaluate_volume_and_price")
    def test_bearish_breakdown_suppresses_turtle_soup(self, mock_vol, mock_hist, mock_analyze):
        """Simulate SSGC scenario: Bearish breakdown must suppress bullish Turtle Soup."""
        mock_analyze.return_value = {
            "current_price": 22.60,
            "score": -43.5,
            "action": "AVOID",
            "support_1": 22.50,
            "resistance_1": 25.00,
            "smc": {
                "structure": "BEARISH_BOS",
                "liquidity_sweeps": [
                    {"type": "SSL_SWEEP", "level": 22.30, "bars_ago": 0}
                ]
            }
        }
        mock_hist.return_value = pd.DataFrame({"close": [22.60]*20})
        mock_vol.return_value = {"has_signal": False, "anti_fakeout_status": "NORMAL"}

        alerts = check_stock_triggers("SSGC")
        self.assertEqual(len(alerts), 1)
        alert = alerts[0]
        self.assertEqual(alert["trigger"], "BEARISH_TREND_START")
        self.assertIn("Bearish Breakdown", alert["details"])

    @patch("psx.analyzer.analyze_stock")
    @patch("psx.data.fetch_history")
    @patch("psx.volume_sentinel.evaluate_volume_and_price")
    def test_stale_turtle_soup_is_suppressed(self, mock_vol, mock_hist, mock_analyze):
        """Turtle soup that occurred 5 bars ago or price expanded far away is ignored."""
        mock_analyze.return_value = {
            "current_price": 100.04,
            "score": 20,
            "action": "WAIT",
            "support_1": 95.0,
            "resistance_1": 110.0,
            "smc": {
                "structure": "RANGE_BOUND",
                "liquidity_sweeps": [
                    # Level is 87.55 (14% away), and occurred 4 bars ago
                    {"type": "SSL_SWEEP", "level": 87.55, "bars_ago": 4}
                ]
            }
        }
        mock_hist.return_value = pd.DataFrame({"close": [100.0]*20})
        mock_vol.return_value = {"has_signal": False, "anti_fakeout_status": "NORMAL"}

        alerts = check_stock_triggers("MLCF")
        # Should not produce any alert because sweep is stale and no other threshold met
        self.assertEqual(len(alerts), 0)

    @patch("psx.analyzer.analyze_stock")
    @patch("psx.data.fetch_history")
    @patch("psx.volume_sentinel.evaluate_volume_and_price")
    def test_fresh_valid_turtle_soup_triggers(self, mock_vol, mock_hist, mock_analyze):
        """Fresh Turtle Soup (current candle, within 1.5% of reclaim level) triggers cleanly."""
        mock_analyze.return_value = {
            "current_price": 90.50,
            "score": 25,
            "action": "BUY",
            "support_1": 90.0,
            "resistance_1": 98.0,
            "smc": {
                "structure": "RANGE_BOUND",
                "liquidity_sweeps": [
                    {"type": "SSL_SWEEP", "level": 89.50, "bars_ago": 0}  # Reclaimed today!
                ]
            }
        }
        mock_hist.return_value = pd.DataFrame({"close": [90.0]*20})
        mock_vol.return_value = {"has_signal": False, "anti_fakeout_status": "NORMAL"}

        alerts = check_stock_triggers("POL")
        self.assertEqual(len(alerts), 1)
        alert = alerts[0]
        self.assertEqual(alert["trigger"], "TURTLE_SOUP_SSL_SWEEP")
        self.assertIn("Smart Money ne retail sell stop-losses hunt kar ke", alert["details"])


if __name__ == "__main__":
    unittest.main()
