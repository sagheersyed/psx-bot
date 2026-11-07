"""Central configuration — saari settings ek jagah."""
import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

DATA_DIR = BASE_DIR / "data"
CHARTS_DIR = DATA_DIR / "charts"
DB_PATH = DATA_DIR / "journal.db"
for _p in (DATA_DIR, CHARTS_DIR):
    _p.mkdir(parents=True, exist_ok=True)

TZ = "Asia/Karachi"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

CIRCUIT_PCT = float(os.getenv("PSX_CIRCUIT_PCT", "7.5"))
MIN_AVG_VOLUME = float(os.getenv("MIN_AVG_VOLUME", "50000"))

# PSX market hours (Mon-Fri, PKT). Friday ka break approx hai.
SESSION_OPEN = (9, 15)
SESSION_CLOSE = (15, 30)

# weight = is timeframe ki importance. HTF macro trend sab se zyada heavy, 1M sirf entry timing.
TIMEFRAMES = [
    {"name": "1Y",  "res": "Y",  "days": 1500, "weight": 0.10, "label": "Yearly (Macro Structural Trend)"},
    {"name": "1MO", "res": "MO", "days": 1500, "weight": 0.15, "label": "Monthly (Institutional Cycle)"},
    {"name": "1W",  "res": "W",  "days": 1000, "weight": 0.20, "label": "Weekly (HTF Order Flow & POI)"},
    {"name": "1D",  "res": "D",  "days": 400,  "weight": 0.22, "label": "Daily (Swing Market Structure)"},
    {"name": "60M", "res": "60", "days": 30,   "weight": 0.12, "label": "1-Hour (Swing Trend)"},
    {"name": "30M", "res": "30", "days": 14,   "weight": 0.08, "label": "30-Min (Wave Momentum)"},
    {"name": "15M", "res": "15", "days": 8,    "weight": 0.06, "label": "15-Min (Setup / Key Level)"},
    {"name": "5M",  "res": "5",  "days": 5,    "weight": 0.04, "label": "5-Min (Entry Timing)"},
    {"name": "1M",  "res": "1",  "days": 4,    "weight": 0.03, "label": "1-Min (Tape & Execution)"},
]

# cache TTL (seconds)
TTL_DAILY = 300
TTL_INTRADAY = 45
TTL_FUNDAMENTALS = 6 * 3600

# Signal rules
SCORE_STRONG_BUY = 50
SCORE_BUY = 25
MIN_RR = 1.3
MIN_CONFIDENCE = 40
HOLD_DAYS = 15  # journal/backtest: trade kitne din tak zinda
