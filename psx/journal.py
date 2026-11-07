"""Prediction journal (SQLite): har signal save hota hai, baad mein asal result se match hota hai.
Yehi 'self-improving' loop hai — 1-2 mahine baad aap ko pata hoga ke bot ki haqiqi accuracy kya hai."""
import sqlite3
import json
from contextlib import closing
from datetime import date

import config
from . import data
from .backtest import simulate_trade

SCHEMA = """
CREATE TABLE IF NOT EXISTS signals(
  id INTEGER PRIMARY KEY AUTOINCREMENT, day TEXT, symbol TEXT, action TEXT, mode TEXT,
  score REAL, confidence INTEGER, price REAL, entry_low REAL, entry_high REAL, stop REAL, t1 REAL, t2 REAL,
  status TEXT DEFAULT 'OPEN', result TEXT, r REAL, closed_day TEXT, UNIQUE(day, symbol));
CREATE TABLE IF NOT EXISTS backtests(symbol TEXT PRIMARY KEY, run_day TEXT, summary TEXT);
"""


def _conn():
    c = sqlite3.connect(config.DB_PATH)
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    return c


def log_signal(symbol: str, sig: dict):
    if sig["action"] not in ("BUY", "WATCH"):
        return
    lv = sig["levels"]
    with closing(_conn()) as c, c:
        c.execute("INSERT OR IGNORE INTO signals(day,symbol,action,mode,score,confidence,price,entry_low,entry_high,stop,t1,t2)"
                  " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                  (str(date.today()), symbol, sig["action"], sig["mode"], sig["score"], sig["confidence"], sig["price"],
                   lv["entry_low"], lv["entry_high"], lv["stop"], lv["t1"], lv["t2"]))


def evaluate_open() -> int:
    """Open signals ko asal candles se resolve karo. Daily ek baar chalayein."""
    done = 0
    with closing(_conn()) as c, c:
        for row in c.execute("SELECT * FROM signals WHERE status='OPEN'").fetchall():
            df = data.fetch_history(row["symbol"], "D", 120)
            if df is None:
                continue
            fut = df[df.index > row["day"]]
            if fut.empty:
                continue
            fb = 5 if row["mode"] == "pullback" else 3
            res = simulate_trade(fut, row["entry_high"], row["stop"], row["t1"], fb)
            if res["result"] in ("PENDING",):
                continue
            c.execute("UPDATE signals SET status='CLOSED', result=?, r=?, closed_day=? WHERE id=?",
                      (res["result"], res["r"], str(fut.index[min(res["bars"], len(fut)) - 1].date()), row["id"]))
            done += 1
    return done


def live_stats(min_conf: int = 0) -> dict:
    with closing(_conn()) as c:
        rows = c.execute("SELECT result, r FROM signals WHERE status='CLOSED' AND result!='NO_FILL' AND confidence>=?",
                         (min_conf,)).fetchall()
        open_n = c.execute("SELECT COUNT(*) FROM signals WHERE status='OPEN'").fetchone()[0]
    n = len(rows)
    if not n:
        return {"n": 0, "open": open_n, "win_rate": None, "avg_r": None}
    rs = [r["r"] for r in rows]
    return {"n": n, "open": open_n, "win_rate": round(100 * sum(x > 0 for x in rs) / n, 1), "avg_r": round(sum(rs) / n, 2)}


def save_backtest(symbol: str, summary: dict):
    with closing(_conn()) as c, c:
        c.execute("INSERT OR REPLACE INTO backtests VALUES(?,?,?)", (symbol, str(date.today()), json.dumps(summary)))


def get_backtest(symbol: str) -> dict | None:
    with closing(_conn()) as c:
        row = c.execute("SELECT summary FROM backtests WHERE symbol=?", (symbol,)).fetchone()
    return json.loads(row["summary"]) if row else None
