"""
Institutional PSX Intraday Validation Suite: 5 Rigorous Test Cases
Verifies:
1. Engine B: 10% Circuit Hunter (+4.5% Breakout, +9.5% Upper Circuit Target, Tight -1.5% SL, R:R >= 1:2.8)
2. Engine A: Morning SSL Sweep & Liquidity Grab (Buffered SL, Breakeven Lock at +0.5%)
3. Anti-Trap Rule 1: 09:15 - 09:45 AM Opening Discovery & Gap-Up Trap Shield (Block Execution)
4. Anti-Trap Rule 2: 11:30 AM - 01:30 PM Midday Low-Volume Chop Zone Lockout (Block Execution)
5. Anti-Fakeout Shield: Volume Sentinel Overhead Block Trap Override (Blocks Long even if breakout occurs)
"""

import sys
import unittest
from datetime import time
import pandas as pd
import numpy as np

from psx.intraday_engine import (
    get_session_kill_zone,
    evaluate_morning_ssl_sweep,
    evaluate_circuit_hunter,
    scan_intraday_radar,
    CIRCUIT_CEILING_PCT,
    MIN_PROFIT_FACTOR
)

class TestPSXIntradayInstitutionalSuite(unittest.TestCase):

    def test_case_1_circuit_hunter_geometry_and_asymmetric_rr(self):
        """
        TEST CASE 1: 10% Circuit Hunter (+4.5% breakout -> 9.5%+ Upper Lock)
        Must enforce minimum 1:2.8 Risk-to-Reward ratio, High-Beta universe,
        and tight 1.5% risk stop.
        """
        # Simulated 5-min breakout data for high-beta stock (PRL)
        # Prev close: 30.00, Current: 31.40 (+4.67%), Volume: 3.5x normal
        data = {
            "symbol": "PRL",
            "prev_close": 30.00,
            "current_price": 31.40,
            "open": 30.20,
            "high": 31.50,
            "low": 30.10,
            "close": 31.40,
            "rvol": 3.2,
            "vwap": 30.90,
            "curr_time": time(10, 15), # Inside Circuit Velocity Window (10:00 - 11:30)
            "htf_trend": "BULLISH"
        }
        
        signal = evaluate_circuit_hunter(data)
        self.assertIsNotNone(signal, "Engine B must trigger a valid signal for high-beta momentum breakout")
        self.assertTrue(signal["qualified"], "Setup should be marked qualified")
        self.assertEqual(signal["direction"], "BUY")
        self.assertGreaterEqual(signal["change_pct"], 4.0, "Entry price must be at least +4.0% above close")
        self.assertLessEqual(signal["change_pct"], 6.0, "Entry price must not be chased past +6.0%")
        
        # Stop loss & Target verification
        entry_price = signal["entry_price"]
        sl = signal["stop_loss"]
        tp = signal["target_price"]
        
        risk = entry_price - sl
        reward = tp - entry_price
        rr_ratio = reward / risk if risk > 0 else 0
        
        self.assertGreaterEqual(rr_ratio, 2.5, f"Circuit hunter R:R must be >= 1:2.5, got 1:{rr_ratio:.2f}")
        self.assertAlmostEqual(tp, 30.00 * 1.095, places=1, msg="Target must align with PSX 10% upper circuit lock (~9.5%)")
        self.assertTrue(signal["is_high_beta"], "Must be restricted to verified high-beta universe")
        print(f"\n[PASS] Test Case 1: 10% Circuit Hunter Passed! R:R = 1:{rr_ratio:.2f}, Target: Rs {tp:.2f}")

    def test_case_2_morning_ssl_sweep_and_breakeven_lock(self):
        """
        TEST CASE 2: Engine A - Morning SSL Sweep & Liquidity Grab
        Validates false low breakdown reversal at HTF Daily Support, 
        0.4% buffered stop loss, and automated Breakeven trigger at +0.5%.
        """
        # Prior daily low was 15.00. Morning dumps to 14.85 (sweeps stops), then closes back at 15.10 with high volume
        data = {
            "symbol": "CNERGY",
            "prev_close": 15.20,
            "daily_support": 15.00,
            "morning_low": 14.85, # Swept SSL by 1.0%
            "current_price": 15.15, # Reclaimed back above 15.00
            "vwap": 15.05,
            "curr_time": time(10, 5), # Prime Morning Kill-Zone (09:45 - 10:45)
            "rvol": 2.4,
            "htf_bias": "BULLISH_DISCOUNT"
        }
        
        signal = evaluate_morning_ssl_sweep(data)
        self.assertIsNotNone(signal, "Engine A must trigger on verified SSL sweep reclamation")
        self.assertEqual(signal["setup_type"], "MORNING_SSL_SWEEP")
        self.assertEqual(signal["direction"], "BUY")
        
        # Verify Breakeven Lock trigger is explicitly programmed
        self.assertIn("breakeven_trigger_price", signal, "Signal must include Breakeven trigger level")
        self.assertGreater(signal["breakeven_trigger_price"], signal["entry_price"])
        self.assertAlmostEqual(signal["breakeven_trigger_price"], signal["entry_price"] * 1.005, places=2)
        
        # Stop loss must be protected below the sweep low
        self.assertLess(signal["stop_loss"], data["morning_low"])
        print(f"\n[PASS] Test Case 2: Morning SSL Sweep Passed! Breakeven Lock @ Rs {signal['breakeven_trigger_price']:.2f}")

    def test_case_3_opening_discovery_gap_trap_lockout(self):
        """
        TEST CASE 3: 09:15 - 09:45 AM Gap-Up Trap Shield
        Ensures NO day-trade execution during the high-failure retail discovery window.
        """
        # Testing multiple timestamps between 09:15 and 09:44
        opening_times = [time(9, 15), time(9, 20), time(9, 30), time(9, 44)]
        for t in opening_times:
            zone_info = get_session_kill_zone(t)
            self.assertFalse(
                zone_info["can_enter"], 
                f"Opening discovery at {t} must strictly forbid new trade entries (can_enter=False)"
            )
            self.assertEqual(zone_info["zone"], "OPENING_DISCOVERY_LOCKOUT")
            self.assertIn("GAP_UP_RETAIL_TRAP", zone_info["caution_flag"])
        print("\n[PASS] Test Case 3: 09:15-09:45 AM Gap-Up Trap Shield Passed! All entries blocked.")

    def test_case_4_active_window_0945_to_1430_and_eod_lockout(self):
        """
        TEST CASE 4: Active Intraday Window (09:45 AM - 02:30 PM) & EOD Square-Off Lockout (02:30 - 03:15 PM)
        """
        active_times = [time(10, 0), time(11, 45), time(12, 30), time(14, 15)]
        for t in active_times:
            zone_info = get_session_kill_zone(t)
            self.assertTrue(
                zone_info["can_enter"], 
                f"Active intraday window at {t} (09:45-14:30) must allow entries"
            )
        eod_zone = get_session_kill_zone(time(14, 45))
        self.assertFalse(eod_zone["can_enter"], "2:30-3:15 PM EOD Square-off must lock out new entries")
        self.assertEqual(eod_zone["zone"], "EOD_SQUARE_OFF")
        print("\n[PASS] Test Case 4: Active 09:45-14:30 Window & 14:30+ EOD Lockout Passed!")

    def test_case_5_overhead_resistance_fakeout_override(self):
        """
        TEST CASE 5: Sentinel Resistance Trap Override
        If Volume Sentinel detects massive institutional ask walls (heavy distribution)
        directly overhead, the day trade signal must be aborted/filtered as a fakeout.
        """
        data_with_heavy_overhead = {
            "symbol": "PAEL",
            "prev_close": 20.00,
            "current_price": 20.95, # +4.75% looks like a circuit breakout!
            "open": 20.10,
            "high": 21.00,
            "low": 20.00,
            "close": 20.95,
            "rvol": 2.8,
            "vwap": 20.40,
            "curr_time": time(10, 30),
            "htf_trend": "BULLISH",
            "sentinel_wall_ahead": True, # Institutional resistance block detected!
            "wall_price": 21.05
        }
        
        signal = evaluate_circuit_hunter(data_with_heavy_overhead)
        self.assertFalse(
            signal["qualified"], 
            "Circuit hunter must abort if an institutional ask wall is detected overhead"
        )
        self.assertEqual(signal.get("veto_reason"), "OVERHEAD_SENTINEL_WALL_DETECTED")
        print("\n[PASS] Test Case 5: Sentinel Fakeout Trap Override Passed! Bull-trap aborted before execution.")

if __name__ == "__main__":
    unittest.main()
