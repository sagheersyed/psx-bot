"""
psx/sector_rotation.py: PSX Institutional Sector Flow & Rotation Engine
Scans and aggregates real-time capital flows across all major PSX sectors.
Tracks where smart money is aggressively accumulating vs. where it is exiting.
"""
import time
import threading
from concurrent.futures import ThreadPoolExecutor

import config
from . import data

# Comprehensive PSX Sector Taxonomy
SECTOR_MAP = {
    "Fertilizer": ["FFC", "EFERT", "ENGROH", "FATIMA"],
    "Oil & Gas Exploration (E&P)": ["OGDC", "PPL", "MARI", "POL"],
    "Cement": ["LUCK", "DGKC", "MLCF", "FCCL", "CHCC", "PIOC", "KOHC", "ACPL"],
    "Commercial Banks": ["HBL", "MCB", "UBL", "MEBL", "BAHL", "BAFL", "BOP", "FABL"],
    "Technology & Communication": ["SYS", "TRG", "AVN", "NETSOL", "AIRLINK", "WTL"],
    "Oil & Gas Marketing (OMCs)": ["PSO", "SNGP", "SSGC", "WAFI", "APL"],
    "Refinery": ["ATRL", "CNERGY", "PRL", "NRL"],
    "Power Generation": ["HUBC", "KAPCO", "KEL", "NCPL", "NPL"],
    "Automobile Assembler": ["INDU", "HCAR", "MTL", "AGTL"],
    "Pharmaceuticals & Chemicals": ["SEARL", "GLAXO", "ABOT", "AGP", "EPCL", "LOTCHEM"],
    "Engineering & Steel": ["MUGHAL", "ISL", "INIL", "ASTL"],
    "Textile Composite": ["NML", "ILP", "GATM", "KTML", "CRTM"],
    "Sugar & Allied (High-Beta)": ["BAFS", "ALNRS", "MIRKS", "JSML", "SHSML", "TICL"],
    "Modarabas & Financials": ["SINDM", "KOSM", "FTSM", "ARM", "FHAM", "BFMOD", "BIPL", "JSBL"]
}

_SECTOR_CACHE = {"timestamp": 0, "data": []}
_SECTOR_LOCK = threading.Lock()
SECTOR_TTL = 180  # 3 minutes cache


def _analyze_single_stock(sym: str) -> dict | None:
    try:
        df = data.fetch_history(sym, "D", 25)
        if df is None or len(df) < 5:
            return None
        last = df.iloc[-1]
        prev = df.iloc[-2]
        close = float(last["close"])
        prev_close = float(prev["close"])
        vol = float(last["volume"])
        chg_pct = round((close - prev_close) / prev_close * 100, 2) if prev_close > 0 else 0.0
        turnover_pkr = round(close * vol, 2)
        
        # 20-day average volume for RVOL
        avg_vol = float(df["volume"].iloc[-21:-1].mean()) if len(df) >= 21 else vol
        rvol = round(vol / avg_vol, 2) if avg_vol > 0 else 1.0
        
        return {
            "symbol": sym,
            "close": close,
            "change_pct": chg_pct,
            "volume": int(vol),
            "turnover_pkr": turnover_pkr,
            "rvol": rvol
        }
    except Exception:
        return None


def get_sector_rotation(force_refresh: bool = False) -> list[dict]:
    """
    Computes real-time capital flow, turnover, advancers/decliners,
    and institutional bias for each PSX sector.
    """
    now = time.time()
    with _SECTOR_LOCK:
        if not force_refresh and (now - _SECTOR_CACHE["timestamp"]) < SECTOR_TTL and _SECTOR_CACHE["data"]:
            return _SECTOR_CACHE["data"]

    # Gather all unique symbols across sectors
    all_symbols = set()
    for sym_list in SECTOR_MAP.values():
        all_symbols.update(sym_list)

    # Fetch stock performance in parallel
    stock_results = {}
    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = {ex.submit(_analyze_single_stock, s): s for s in all_symbols}
        for f in futures:
            sym = futures[f]
            res = f.result()
            if res:
                stock_results[sym] = res

    # Aggregate sector-level metrics
    sectors_out = []
    total_market_turnover = sum(s["turnover_pkr"] for s in stock_results.values()) or 1.0

    for sec_name, sym_list in SECTOR_MAP.items():
        matched = [stock_results[s] for s in sym_list if s in stock_results]
        if not matched:
            continue

        n_stocks = len(matched)
        sec_turnover = sum(s["turnover_pkr"] for s in matched)
        sec_volume = sum(s["volume"] for s in matched)
        avg_chg = round(sum(s["change_pct"] for s in matched) / n_stocks, 2)
        advancers = sum(1 for s in matched if s["change_pct"] > 0)
        decliners = sum(1 for s in matched if s["change_pct"] < 0)
        unchanged = n_stocks - advancers - decliners

        market_share_pct = round((sec_turnover / total_market_turnover) * 100, 1)

        # Identify sector alpha leader
        leader = max(matched, key=lambda x: x["change_pct"])

        # Determine Institutional Flow Status
        if avg_chg >= 0.75 and advancers > decliners and market_share_pct >= 8.0:
            flow_status = "🔥 AGGRESSIVE INFLOW (Leading Sector)"
            flow_code = "INFLOW_HIGH"
            badge_color = "emerald"
        elif avg_chg >= 0.20 and advancers >= decliners:
            flow_status = "🟢 SELECTIVE ACCUMULATION (Inflow)"
            flow_code = "INFLOW_MOD"
            badge_color = "teal"
        elif avg_chg <= -0.75 and decliners > advancers:
            flow_status = "🚨 INSTITUTIONAL OUTFLOW (Bleeding Sector)"
            flow_code = "OUTFLOW_HIGH"
            badge_color = "red"
        elif avg_chg <= -0.20:
            flow_status = "🔴 DISTRIBUTION / PROFIT TAKING"
            flow_code = "OUTFLOW_MOD"
            badge_color = "rose"
        else:
            flow_status = "🟡 CONSOLIDATION / NEUTRAL ROTATION"
            flow_code = "NEUTRAL"
            badge_color = "amber"

        sectors_out.append({
            "sector": sec_name,
            "stock_count": n_stocks,
            "avg_change_pct": avg_chg,
            "advancers": advancers,
            "decliners": decliners,
            "unchanged": unchanged,
            "breadth_ratio": f"{advancers}/{n_stocks} Bullish",
            "turnover_pkr": sec_turnover,
            "turnover_m": round(sec_turnover / 1_000_000, 1),
            "volume": sec_volume,
            "market_share_pct": market_share_pct,
            "flow_status": flow_status,
            "flow_code": flow_code,
            "badge_color": badge_color,
            "alpha_leader": {
                "symbol": leader["symbol"],
                "change_pct": leader["change_pct"],
                "close": leader["close"],
                "rvol": leader["rvol"]
            },
            "stocks": matched
        })

    # Sort sectors by highest turnover & inflow
    sectors_out.sort(key=lambda x: (x["avg_change_pct"], x["turnover_pkr"]), reverse=True)

    with _SECTOR_LOCK:
        _SECTOR_CACHE["timestamp"] = now
        _SECTOR_CACHE["data"] = sectors_out

    return sectors_out
