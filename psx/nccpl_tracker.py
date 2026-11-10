"""
psx/nccpl_tracker.py: NCCPL Daily EOD Activity & Institutional Syndicate Flow Tracker
=================================================================================
Ingests official NCCPL FIPI (Foreign Investors) & LIPI (Local Investors) clearing data,
computes Net USD & Net PKR flows per investor category, aggregates Top 5 Accumulated vs.
Distributed sectors per participant, and cross-references with PSX Low-Float & Volume Surge
metrics to flag Institutional Accumulation Triggers vs. Retail Exit Traps.
"""
from __future__ import annotations

import json
import re
import sqlite3
import ssl
import threading
import time
import urllib.request
from contextlib import closing
from datetime import datetime
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import config
from .cache_engine import cache

# Thread-safe in-memory cache
_NCCPL_LOCK = threading.Lock()
_CACHE = {"data": None, "ts": 0.0, "date": None}
NCCPL_CACHE_TTL = 300  # 5 minutes

# Official NCCPL Portal URL + Structured Clearing Feed
NCCPL_OFFICIAL_URL = "https://www.nccpl.com.pk/en/market-information/fipi-lipi/fipi-normal"
SCS_FIPI_URL = "https://scstrade.com/FIPILIPI.aspx"

# Tracked Institutional & Retail Investor Categories
TRACKED_CATEGORIES = [
    "MUTUAL FUNDS",
    "FOREIGN CORPORATES",
    "FOREIGN INDIVIDUALS",
    "OVERSEAS PAKISTANI",
    "BANKS / DFI",
    "INSURANCE COMPANIES",
    "BROKER PROPRIETARY TRADING",
    "INDIVIDUALS",
    "COMPANIES",
    "NBFC",
    "OTHER ORGANIZATION",
]

# Clean display labels & classification
CATEGORY_META = {
    "MUTUAL FUNDS": {"label": "Local Mutual Funds", "group": "INSTITUTIONAL", "smart_money": True},
    "FOREIGN CORPORATES": {"label": "Foreign Corporates (FIPI)", "group": "FOREIGN", "smart_money": True},
    "FOREIGN INDIVIDUALS": {"label": "Foreign Individuals (FIPI)", "group": "FOREIGN", "smart_money": True},
    "OVERSEAS PAKISTANI": {"label": "Overseas Pakistanis (FIPI)", "group": "FOREIGN", "smart_money": False},
    "BANKS / DFI": {"label": "Local Banks / DFIs", "group": "INSTITUTIONAL", "smart_money": True},
    "INSURANCE COMPANIES": {"label": "Insurance Companies", "group": "INSTITUTIONAL", "smart_money": True},
    "BROKER PROPRIETARY TRADING": {"label": "Broker Proprietary Desk", "group": "PROPRIETARY", "smart_money": False},
    "INDIVIDUALS": {"label": "Local Individuals (Retail)", "group": "RETAIL", "smart_money": False},
    "COMPANIES": {"label": "Local Corporates / Companies", "group": "CORPORATE", "smart_money": False},
    "NBFC": {"label": "NBFCs", "group": "INSTITUTIONAL", "smart_money": True},
    "OTHER ORGANIZATION": {"label": "Other Organizations", "group": "OTHER", "smart_money": False},
}

# Mapping between NCCPL sector names and internal PSX sector taxonomy
NCCPL_TO_PSX_SECTOR = {
    "Cement": "Cement",
    "Commercial Banks": "Commercial Banks",
    "Fertilizer": "Fertilizer",
    "Oil and Gas Exploration Companies": "Oil & Gas Exploration (E&P)",
    "Oil and Gas Marketing Companies": "Oil & Gas Marketing (OMCs)",
    "Power Generation and Distribution": "Power Generation",
    "Technology and Communication": "Technology & Communication",
    "Textile Composite": "Textile Composite",
    "Food and Personal Care Products": "Food & Personal Care",
    "Debt Market": "Debt Market",
    "All other Sectors": "All Other Sectors",
}

# Reverse map from Low-Float / Sector Rotation sectors to NCCPL clean sector name
PSX_SECTOR_TO_NCCPL = {
    "Cement": "Cement",
    "Commercial Banks": "Commercial Banks",
    "Fertilizer": "Fertilizer",
    "Oil & Gas Exploration (E&P)": "Oil and Gas Exploration Companies",
    "Oil & Gas Marketing (OMCs)": "Oil and Gas Marketing Companies",
    "Power Generation": "Power Generation and Distribution",
    "Technology & Communication": "Technology and Communication",
    "Textile Composite": "Textile Composite",
    "Textile Spinning": "Textile Composite",
    "Modarabas": "All other Sectors",
    "Modarabas & Financials": "All other Sectors",
    "Sugar & Allied": "Food and Personal Care Products",
    "Sugar & Allied (High-Beta)": "Food and Personal Care Products",
    "Refinery": "All other Sectors",
    "Automobile Assembler": "All other Sectors",
    "Pharmaceuticals & Chemicals": "All other Sectors",
    "Chemicals": "All other Sectors",
    "Leather & Tanneries": "All other Sectors",
    "Engineering & Steel": "All other Sectors",
    "Insurance": "All other Sectors",
    "Food & Personal Care": "Food and Personal Care Products",
    "Miscellaneous": "All other Sectors",
}

NCCPL_SCHEMA = """
CREATE TABLE IF NOT EXISTS nccpl_eod_flows (
    report_date TEXT PRIMARY KEY,
    fetched_at TEXT,
    is_delayed INTEGER DEFAULT 0,
    fipi_net_usd_m REAL,
    lipi_net_usd_m REAL,
    payload TEXT
);
CREATE TABLE IF NOT EXISTS nccpl_eod_runs (
    run_day TEXT PRIMARY KEY,
    status TEXT,
    report_date TEXT,
    executed_at TEXT
);
"""


def _db_conn():
    c = sqlite3.connect(config.DB_PATH)
    c.row_factory = sqlite3.Row
    c.executescript(NCCPL_SCHEMA)
    return c


def init_nccpl_db():
    with closing(_db_conn()):
        pass


def save_nccpl_snapshot(report: dict):
    """Persists daily NCCPL EOD flow snapshot into SQLite."""
    if not report or report.get("error"):
        return
    rdate = report.get("report_date_iso") or report.get("report_date")
    if not rdate:
        return
    with closing(_db_conn()) as c, c:
        c.execute(
            """INSERT OR REPLACE INTO nccpl_eod_flows
               (report_date, fetched_at, is_delayed, fipi_net_usd_m, lipi_net_usd_m, payload)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                rdate,
                report.get("fetched_at", ""),
                1 if report.get("is_delayed") else 0,
                float(report.get("summary", {}).get("fipi_net_usd_m", 0.0)),
                float(report.get("summary", {}).get("lipi_net_usd_m", 0.0)),
                json.dumps(report),
            ),
        )


def get_nccpl_history(limit: int = 10) -> List[dict]:
    """Returns recent saved NCCPL EOD flow summaries for trend analysis."""
    init_nccpl_db()
    with closing(_db_conn()) as c:
        rows = c.execute(
            "SELECT report_date, fetched_at, is_delayed, fipi_net_usd_m, lipi_net_usd_m FROM nccpl_eod_flows ORDER BY report_date DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def _ssl_context():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _probe_official_nccpl_portal() -> dict:
    """Checks direct NCCPL portal availability (logs WAF/403 gracefully)."""
    headers = {"User-Agent": config.HEADERS.get("User-Agent", "Mozilla/5.0")}
    try:
        req = urllib.request.Request(NCCPL_OFFICIAL_URL, headers=headers)
        with urllib.request.urlopen(req, timeout=5, context=_ssl_context()) as resp:
            return {"reachable": True, "status": resp.status}
    except Exception as e:
        return {"reachable": False, "status": str(e)}


def _scs_post(endpoint: str, date_str: str) -> list:
    """Calls structured NCCPL FIPI/LIPI clearing endpoint for given MM/DD/YYYY date."""
    headers = {
        "User-Agent": config.HEADERS.get("User-Agent", "Mozilla/5.0"),
        "Content-Type": "application/json; charset=utf-8",
    }
    payload = json.dumps({
        "date1": date_str,
        "date2": date_str,
        "_search": False,
        "nd": int(time.time() * 1000),
        "rows": 500,
        "page": 1,
        "sidx": "",
        "sord": "asc",
    }).encode("utf-8")
    req = urllib.request.Request(f"{SCS_FIPI_URL}/{endpoint}", data=payload, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=12, context=_ssl_context()) as resp:
        data = json.loads(resp.read().decode("utf-8", errors="ignore"))
        return data.get("d") or []


def _get_latest_published_date() -> Optional[str]:
    """Fetches SCSTrade FIPILIPI portal HTML to detect the latest published NCCPL report date (MM/DD/YYYY)."""
    headers = {"User-Agent": config.HEADERS.get("User-Agent", "Mozilla/5.0")}
    req = urllib.request.Request(SCS_FIPI_URL, headers=headers)
    html = urllib.request.urlopen(req, timeout=12, context=_ssl_context()).read().decode("utf-8", errors="ignore")
    m = re.search(r'id=["\']date1["\'][^>]*value=["\']([^"\']+)["\']', html)
    return m.group(1).strip() if m else None


def _clean_sector_name(raw_name: str) -> str:
    return re.sub(r"\s*\(mn\$\)\s*$", "", str(raw_name or "").strip(), flags=re.IGNORECASE).strip()


def _to_iso_date(mmddyyyy: str) -> str:
    try:
        return datetime.strptime(mmddyyyy, "%m/%d/%Y").strftime("%Y-%m-%d")
    except Exception:
        return mmddyyyy


def aggregate_nccpl_data(
    mainsum: list,
    mainsumdetails: list,
    lipi_rows: list,
    fipi_rows: list,
    investor_sector_rows: list,
    report_date_str: str,
    is_delayed: bool = False,
    delay_note: str = "",
) -> dict:
    """
    Pure transformation & aggregation function (testable offline without network).
    Computes Gross Buy, Gross Sell, Net Value (USD & PKR) per category,
    and Top 5 Accumulated vs. Distributed sectors per participant.
    """
    # 1. Aggregate PKR totals per category from LIPI & FIPI market breakdown (REG, FUT, NDM, GEM)
    pkr_by_cat: Dict[str, Dict[str, float]] = {}
    for row in (lipi_rows or []) + (fipi_rows or []):
        cat = str(row.get("FLType") or "").upper().strip()
        if not cat:
            continue
        bucket = pkr_by_cat.setdefault(cat, {"buy_pkr": 0.0, "sell_pkr": 0.0, "net_pkr": 0.0, "buy_vol": 0.0, "sell_vol": 0.0})
        buy_v = float(row.get("FLBuyValue") or 0.0)
        sell_v = float(row.get("FLSellValue") or 0.0)
        net_v = row.get("NetValue")
        net_v = float(net_v) if net_v is not None else (buy_v + sell_v)  # sell_v is negative in NCCPL feed
        bucket["buy_pkr"] += buy_v
        bucket["sell_pkr"] += sell_v
        bucket["net_pkr"] += net_v
        bucket["buy_vol"] += float(row.get("FLBuyVolume") or 0.0)
        bucket["sell_vol"] += float(row.get("FLSellVolume") or 0.0)

    # Pre-compute Equity vs Debt Market Net Flow (USD Mn) per participant from investor_sector_rows
    eq_net_by_part: Dict[str, float] = {}
    debt_net_by_part: Dict[str, float] = {}
    for row in investor_sector_rows or []:
        part = str(row.get("FLTypeNew") or "").upper().strip()
        raw_sec = _clean_sector_name(row.get("FLSectorName") or "")
        if not part or not raw_sec:
            continue
        buy_v = float(row.get("FLBuyValue") or 0.0)
        sell_v = float(row.get("FLSellValue") or 0.0)
        val_usd = row.get("FLNetValueUSD")
        val_usd = float(val_usd) if val_usd is not None else (buy_v - abs(sell_v))
        if raw_sec.lower() == "debt market":
            debt_net_by_part[part] = round(debt_net_by_part.get(part, 0.0) + val_usd, 3)
        else:
            eq_net_by_part[part] = round(eq_net_by_part.get(part, 0.0) + val_usd, 3)

    # 2. Aggregate USD totals per category from mainsumdetails
    categories_out: List[dict] = []
    seen_cats = set()
    for row in mainsumdetails or []:
        cat = str(row.get("FLType") or "").upper().strip()
        if not cat:
            continue
        seen_cats.add(cat)
        buy_usd = float(row.get("FLBuyValue") or 0.0)
        sell_usd = float(row.get("FLSellValue") or 0.0)
        net_usd = row.get("FLNetValueUSD")
        net_usd = float(net_usd) if net_usd is not None else (buy_usd + sell_usd)
        net_usd = round(buy_usd - abs(sell_usd), 3) if row.get("FLNetValueUSD") is None else round(net_usd, 3)

        pkr_info = pkr_by_cat.get(cat, {})
        buy_pkr_m = round(pkr_info.get("buy_pkr", 0.0) / 1_000_000.0, 2)
        sell_pkr_m = round(pkr_info.get("sell_pkr", 0.0) / 1_000_000.0, 2)
        net_pkr_m = round(buy_pkr_m - abs(sell_pkr_m), 2) if pkr_info else round(net_usd * 278.0, 2)

        # Separate Equity Flow vs Debt Market Flow (crucial when Mutual Funds/Banks settle T-bills/Repos)
        debt_usd = debt_net_by_part.get(cat, 0.0)
        eq_usd = eq_net_by_part[cat] if cat in eq_net_by_part else round(net_usd - debt_usd, 3)
        eq_pkr_m = round(eq_usd * (abs(net_pkr_m) / abs(net_usd)), 2) if abs(net_usd) > 0.01 and abs(net_pkr_m) > 1 else round(eq_usd * 278.0, 2)

        meta = CATEGORY_META.get(cat, {"label": cat.title(), "group": "OTHER", "smart_money": False})
        categories_out.append({
            "category": cat,
            "label": meta["label"],
            "group": meta["group"],
            "smart_money": meta["smart_money"],
            "buy_usd_m": round(buy_usd, 3),
            "sell_usd_m": round(abs(sell_usd), 3),
            "net_usd_m": net_usd,
            "equity_net_usd_m": round(eq_usd, 3),
            "debt_net_usd_m": round(debt_usd, 3),
            "buy_pkr_m": buy_pkr_m,
            "sell_pkr_m": round(abs(sell_pkr_m), 2),
            "net_pkr_m": net_pkr_m,
            "equity_net_pkr_m": eq_pkr_m,
            "bias": "ACCUMULATING" if eq_usd > 0.05 else ("DISTRIBUTING" if eq_usd < -0.05 else "NEUTRAL"),
        })

    # Add any category present in PKR feed but omitted in mainsumdetails
    for cat, pkr_info in pkr_by_cat.items():
        if cat not in seen_cats:
            buy_pkr_m = round(pkr_info["buy_pkr"] / 1_000_000.0, 2)
            sell_pkr_m = round(abs(pkr_info["sell_pkr"]) / 1_000_000.0, 2)
            net_pkr_m = round(buy_pkr_m - sell_pkr_m, 2)
            meta = CATEGORY_META.get(cat, {"label": cat.title(), "group": "OTHER", "smart_money": False})
            categories_out.append({
                "category": cat,
                "label": meta["label"],
                "group": meta["group"],
                "smart_money": meta["smart_money"],
                "buy_usd_m": round(buy_pkr_m / 278.0, 3),
                "sell_usd_m": round(sell_pkr_m / 278.0, 3),
                "net_usd_m": round(net_pkr_m / 278.0, 3),
                "equity_net_usd_m": round(net_pkr_m / 278.0, 3),
                "debt_net_usd_m": 0.0,
                "equity_net_pkr_m": net_pkr_m,
                "buy_pkr_m": buy_pkr_m,
                "sell_pkr_m": sell_pkr_m,
                "net_pkr_m": net_pkr_m,
                "bias": "ACCUMULATING" if net_pkr_m > 10 else ("DISTRIBUTING" if net_pkr_m < -10 else "NEUTRAL"),
            })

    categories_out.sort(key=lambda x: abs(x.get("equity_net_usd_m", x["net_usd_m"])), reverse=True)

    # 3. FIPI vs LIPI Top-Level Summary
    fipi_net_usd = 0.0
    lipi_net_usd = 0.0
    for r in mainsum or []:
        t = str(r.get("FLType") or "").upper().strip()
        val = float(r.get("FLNetValueUSD") or 0.0)
        if t == "FIPI":
            fipi_net_usd = round(val, 3)
        elif t == "LIPI":
            lipi_net_usd = round(val, 3)

    # 4. Participant x Sector Matrix + Top 5 Accumulated vs Top 5 Distributed per participant
    participant_sectors: Dict[str, Dict[str, float]] = {}
    sector_matrix: Dict[str, Dict[str, float]] = {}

    for row in investor_sector_rows or []:
        part = str(row.get("FLTypeNew") or "").upper().strip()
        raw_sec = _clean_sector_name(row.get("FLSectorName") or "")
        if not part or not raw_sec or raw_sec.lower() == "debt market":
            continue
        psx_sec = NCCPL_TO_PSX_SECTOR.get(raw_sec, raw_sec)
        buy_v = float(row.get("FLBuyValue") or 0.0)
        sell_v = float(row.get("FLSellValue") or 0.0)
        net_usd = row.get("FLNetValueUSD")
        net_usd = float(net_usd) if net_usd is not None else (buy_v - abs(sell_v))

        participant_sectors.setdefault(part, {})
        participant_sectors[part][raw_sec] = round(participant_sectors[part].get(raw_sec, 0.0) + net_usd, 4)

        sec_bucket = sector_matrix.setdefault(raw_sec, {
            "nccpl_sector": raw_sec,
            "psx_sector": psx_sec,
            "fipi_net_usd_m": 0.0,
            "mutual_funds_net_usd_m": 0.0,
            "banks_net_usd_m": 0.0,
            "insurance_net_usd_m": 0.0,
            "individuals_net_usd_m": 0.0,
            "brokers_net_usd_m": 0.0,
            "companies_net_usd_m": 0.0,
            "smart_money_net_usd_m": 0.0,
        })
        if part == "FIPI":
            sec_bucket["fipi_net_usd_m"] = round(sec_bucket["fipi_net_usd_m"] + net_usd, 4)
            sec_bucket["smart_money_net_usd_m"] = round(sec_bucket["smart_money_net_usd_m"] + net_usd, 4)
        elif part == "MUTUAL FUNDS":
            sec_bucket["mutual_funds_net_usd_m"] = round(sec_bucket["mutual_funds_net_usd_m"] + net_usd, 4)
            sec_bucket["smart_money_net_usd_m"] = round(sec_bucket["smart_money_net_usd_m"] + net_usd, 4)
        elif part == "BANKS / DFI":
            sec_bucket["banks_net_usd_m"] = round(sec_bucket["banks_net_usd_m"] + net_usd, 4)
            sec_bucket["smart_money_net_usd_m"] = round(sec_bucket["smart_money_net_usd_m"] + net_usd, 4)
        elif part == "INSURANCE COMPANIES":
            sec_bucket["insurance_net_usd_m"] = round(sec_bucket["insurance_net_usd_m"] + net_usd, 4)
            sec_bucket["smart_money_net_usd_m"] = round(sec_bucket["smart_money_net_usd_m"] + net_usd, 4)
        elif part == "INDIVIDUALS":
            sec_bucket["individuals_net_usd_m"] = round(sec_bucket["individuals_net_usd_m"] + net_usd, 4)
        elif part == "BROKER PROPRIETARY TRADING":
            sec_bucket["brokers_net_usd_m"] = round(sec_bucket["brokers_net_usd_m"] + net_usd, 4)
        elif part == "COMPANIES":
            sec_bucket["companies_net_usd_m"] = round(sec_bucket["companies_net_usd_m"] + net_usd, 4)

    # Top 5 Accumulated vs Distributed sectors per participant
    sector_rankings_by_participant = {}
    for part, sec_dict in participant_sectors.items():
        items = [{"sector": k, "psx_sector": NCCPL_TO_PSX_SECTOR.get(k, k), "net_usd_m": round(v, 3)} for k, v in sec_dict.items()]
        acc = sorted([x for x in items if x["net_usd_m"] > 0], key=lambda x: x["net_usd_m"], reverse=True)[:5]
        dist = sorted([x for x in items if x["net_usd_m"] < 0], key=lambda x: x["net_usd_m"])[:5]
        sector_rankings_by_participant[part] = {
            "top_accumulated": acc,
            "top_distributed": dist,
        }

    # Also compute Institutional Smart Money overall Top 5 Accumulated vs Distributed sectors
    smart_items = [
        {"sector": v["nccpl_sector"], "psx_sector": v["psx_sector"], "net_usd_m": round(v["smart_money_net_usd_m"], 3)}
        for v in sector_matrix.values()
    ]
    sector_rankings_by_participant["SMART_MONEY_COMBINED"] = {
        "top_accumulated": sorted([x for x in smart_items if x["net_usd_m"] > 0], key=lambda x: x["net_usd_m"], reverse=True)[:5],
        "top_distributed": sorted([x for x in smart_items if x["net_usd_m"] < 0], key=lambda x: x["net_usd_m"])[:5],
    }

    sectors_list = sorted(sector_matrix.values(), key=lambda x: x["smart_money_net_usd_m"], reverse=True)

    return {
        "report_date": report_date_str,
        "report_date_iso": _to_iso_date(report_date_str),
        "fetched_at": datetime.now(ZoneInfo(config.TZ)).strftime("%Y-%m-%d %H:%M:%S PKT"),
        "is_delayed": is_delayed,
        "delay_note": delay_note,
        "summary": {
            "fipi_net_usd_m": fipi_net_usd,
            "lipi_net_usd_m": lipi_net_usd,
            "fipi_bias": "NET BUYER" if fipi_net_usd > 0 else ("NET SELLER" if fipi_net_usd < 0 else "FLAT"),
            "mutual_funds_net_usd_m": next((c["net_usd_m"] for c in categories_out if c["category"] == "MUTUAL FUNDS"), 0.0),
            "mutual_funds_equity_net_usd_m": next((c.get("equity_net_usd_m", c["net_usd_m"]) for c in categories_out if c["category"] == "MUTUAL FUNDS"), 0.0),
            "individuals_net_usd_m": next((c.get("equity_net_usd_m", c["net_usd_m"]) for c in categories_out if c["category"] == "INDIVIDUALS"), 0.0),
            "banks_net_usd_m": next((c["net_usd_m"] for c in categories_out if c["category"] == "BANKS / DFI"), 0.0),
            "banks_equity_net_usd_m": next((c.get("equity_net_usd_m", c["net_usd_m"]) for c in categories_out if c["category"] == "BANKS / DFI"), 0.0),
            "brokers_net_usd_m": next((c.get("equity_net_usd_m", c["net_usd_m"]) for c in categories_out if c["category"] == "BROKER PROPRIETARY TRADING"), 0.0),
        },
        "categories": categories_out,
        "sectors": sectors_list,
        "sector_rankings_by_participant": sector_rankings_by_participant,
    }


def cross_reference_syndicate_flows(
    nccpl_report: dict,
    low_float_stocks: list | None = None,
    sector_rotations: list | None = None,
) -> dict:
    """
    Cross-references NCCPL Sector Institutional Flows (Mutual Funds + Foreigners)
    against PSX Low-Float Turnover & Volume Surge metrics.
    Flags:
      - INSTITUTIONAL_ACCUMULATION_TRIGGER: Mutual Funds/Foreigners net buyers in sector + high float turnover/RVOL
      - INSTITUTIONAL_EXIT_TRAP: Retail buying while Mutual Funds/Foreigners selling or distribution detected
    """
    sectors_by_nccpl = {s["nccpl_sector"]: s for s in nccpl_report.get("sectors", [])}

    if low_float_stocks is None:
        try:
            from . import low_float_analyzer
            lf_res = low_float_analyzer.analyze_low_float_stocks(force_refresh=False)
            low_float_stocks = lf_res.get("stocks", []) if isinstance(lf_res, dict) else []
        except Exception:
            low_float_stocks = []

    if sector_rotations is None:
        try:
            from . import sector_rotation
            sector_rotations = sector_rotation.get_sector_rotation(force_refresh=False)
        except Exception:
            sector_rotations = []

    accumulation_triggers = []
    exit_traps = []

    for s in low_float_stocks:
        sym = s.get("symbol")
        sec_raw = s.get("sector", "Miscellaneous")
        nccpl_sec_key = PSX_SECTOR_TO_NCCPL.get(sec_raw, "All other Sectors")
        sec_flow = sectors_by_nccpl.get(nccpl_sec_key) or sectors_by_nccpl.get("All other Sectors") or {}

        mf_net = float(sec_flow.get("mutual_funds_net_usd_m", 0.0))
        fipi_net = float(sec_flow.get("fipi_net_usd_m", 0.0))
        retail_net = float(sec_flow.get("individuals_net_usd_m", 0.0))
        inst_core_net = round(mf_net + fipi_net, 3)

        ft = float(s.get("float_turnover_pct", 0.0))
        rvol = float(s.get("vol_surge_x", 0.0))
        chg = float(s.get("change_pct", 0.0))
        phase = s.get("phase_code", "DORMANT")

        # 1. Institutional Accumulation Trigger:
        # Mutual Funds or Foreigners bought net in this sector + stock shows real float turnover/volume surge + not crashing
        if (mf_net > 0 or fipi_net > 0 or inst_core_net > 0.03) and (ft >= 1.5 or rvol >= 1.4) and chg > -2.0 and phase not in ("LOWER_LOCK", "DISTRIBUTION"):
            buyers = []
            if mf_net > 0:
                buyers.append(f"Mutual Funds (+${mf_net:.2f}M)")
            if fipi_net > 0:
                buyers.append(f"Foreigners (+${fipi_net:.2f}M)")
            accumulation_triggers.append({
                "symbol": sym,
                "price": s.get("price", 0.0),
                "change_pct": chg,
                "sector": sec_raw,
                "nccpl_sector": nccpl_sec_key,
                "float_turnover_pct": ft,
                "vol_surge_x": rvol,
                "syndicate_phase": s.get("syndicate_phase"),
                "phase_code": phase,
                "mf_net_usd_m": mf_net,
                "fipi_net_usd_m": fipi_net,
                "trigger_badge": "🔥 INSTITUTIONAL ACCUMULATION TRIGGER",
                "reason": f"{' & '.join(buyers)} net buyers in {nccpl_sec_key} while {sym} absorbed {ft}% float ({rvol}x RVOL).",
            })
        elif (retail_net > 0.05 and inst_core_net < -0.05 and (ft >= 1.5 or rvol >= 1.5)) or phase in ("DISTRIBUTION", "LOWER_LOCK"):
            exit_traps.append({
                "symbol": sym,
                "price": s.get("price", 0.0),
                "change_pct": chg,
                "sector": sec_raw,
                "nccpl_sector": nccpl_sec_key,
                "float_turnover_pct": ft,
                "vol_surge_x": rvol,
                "phase_code": phase,
                "mf_net_usd_m": mf_net,
                "fipi_net_usd_m": fipi_net,
                "retail_net_usd_m": retail_net,
                "trigger_badge": "⚠️ RETAIL ABSORBING INSTITUTIONAL EXIT" if inst_core_net < 0 else "⚠️ SYNDICATE DUMP / LOWER LOCK",
                "reason": f"Caution: {sym} in {phase} ({chg:+.2f}%). Smart Money sector net ${inst_core_net:+.2f}M vs Retail ${retail_net:+.2f}M.",
            })

    # Also cross-check leading sector rotation leaders with NCCPL sector flows
    sector_confluence = []
    for sr in sector_rotations:
        sr_name = sr.get("sector", "")
        n_key = PSX_SECTOR_TO_NCCPL.get(sr_name, "All other Sectors")
        sf = sectors_by_nccpl.get(n_key, {})
        mf_net = float(sf.get("mutual_funds_net_usd_m", 0.0))
        fipi_net = float(sf.get("fipi_net_usd_m", 0.0))
        smart_net = float(sf.get("smart_money_net_usd_m", 0.0))
        leader = sr.get("alpha_leader") or {}
        if leader.get("symbol"):
            sector_confluence.append({
                "psx_sector": sr_name,
                "nccpl_sector": n_key,
                "avg_change_pct": sr.get("avg_change_pct", 0.0),
                "turnover_m": sr.get("turnover_m", 0.0),
                "leader_symbol": leader.get("symbol"),
                "leader_chg_pct": leader.get("change_pct", 0.0),
                "mf_net_usd_m": round(mf_net, 3),
                "fipi_net_usd_m": round(fipi_net, 3),
                "smart_money_net_usd_m": round(smart_net, 3),
                "aligned": (sr.get("avg_change_pct", 0.0) > 0 and (mf_net > 0 or fipi_net > 0)),
            })

    accumulation_triggers.sort(key=lambda x: (x["mf_net_usd_m"] + x["fipi_net_usd_m"], x["float_turnover_pct"]), reverse=True)
    exit_traps.sort(key=lambda x: x["change_pct"])

    return {
        "accumulation_triggers": accumulation_triggers[:10],
        "exit_traps": exit_traps[:8],
        "sector_confluence": sector_confluence,
    }


def fetch_nccpl_flows(target_date: Optional[str] = None, force_refresh: bool = False) -> dict:
    """
    Fetches, transforms, cross-references, and persists NCCPL Daily EOD FIPI/LIPI flows.
    target_date format: MM/DD/YYYY (optional). Defaults to today PKT, with automatic
    fallback to latest published closing report if today's report is delayed.
    """
    now_ts = time.time()
    with _NCCPL_LOCK:
        if not force_refresh and not target_date and _CACHE["data"] and (now_ts - _CACHE["ts"] < NCCPL_CACHE_TTL):
            return _CACHE["data"]

    init_nccpl_db()
    now_pkt = datetime.now(ZoneInfo(config.TZ))
    today_mmddyyyy = now_pkt.strftime("%m/%d/%Y")
    req_date = target_date or today_mmddyyyy

    portal_status = _probe_official_nccpl_portal()

    # Try requested date first; if empty/delayed, fall back to latest published date
    is_delayed = False
    delay_note = ""
    active_date = req_date

    try:
        mainsum = _scs_post("loadmainsum", active_date)
        has_values = bool(mainsum and any(r.get("FLNetValueUSD") is not None for r in mainsum))

        if not has_values:
            latest_pub = _get_latest_published_date()
            if latest_pub and latest_pub != active_date:
                active_date = latest_pub
                mainsum = _scs_post("loadmainsum", active_date)
                has_values = bool(mainsum and any(r.get("FLNetValueUSD") is not None for r in mainsum))
                if not target_date:
                    is_delayed = True
                    delay_note = (
                        f"Today's NCCPL EOD report ({today_mmddyyyy}) is not yet published (usually released after 6:30 PM PKT); "
                        f"displaying latest verified closing report ({active_date})."
                    )

        if not has_values:
            return {
                "error": f"NCCPL FIPI/LIPI data unavailable for {req_date}. Report publication may be delayed.",
                "official_portal": portal_status,
                "history": get_nccpl_history(10),
            }

        mainsumdetails = _scs_post("loadmainsumdetails", active_date)
        lipi_rows = _scs_post("loadlipi", active_date)
        fipi_rows = _scs_post("loadfipi", active_date)
        inv_rows = _scs_post("loadfipiInvestor", active_date)

        report = aggregate_nccpl_data(
            mainsum=mainsum,
            mainsumdetails=mainsumdetails,
            lipi_rows=lipi_rows,
            fipi_rows=fipi_rows,
            investor_sector_rows=inv_rows,
            report_date_str=active_date,
            is_delayed=is_delayed,
            delay_note=delay_note,
        )
        report["official_portal_check"] = portal_status
        report["cross_reference"] = cross_reference_syndicate_flows(report)
        save_nccpl_snapshot(report)
        report["history"] = get_nccpl_history(10)

        if not target_date:
            with _NCCPL_LOCK:
                _CACHE["data"] = report
                _CACHE["ts"] = now_ts
                _CACHE["date"] = active_date
            cache.set_json("psx:nccpl:flows", report, ttl=NCCPL_CACHE_TTL)

        return report

    except Exception as e:
        # Graceful fallback to last saved SQLite snapshot if upstream temporarily unreachable
        with closing(_db_conn()) as c:
            row = c.execute("SELECT payload FROM nccpl_eod_flows ORDER BY report_date DESC LIMIT 1").fetchone()
        if row:
            cached_rep = json.loads(row["payload"])
            cached_rep["is_delayed"] = True
            cached_rep["delay_note"] = f"Live NCCPL fetch encountered error ({e}); serving last verified EOD snapshot."
            cached_rep["history"] = get_nccpl_history(10)
            return cached_rep
        return {"error": f"Failed to fetch NCCPL EOD flows: {e}"}


def maybe_run_eod_nccpl_job(force: bool = False) -> dict:
    """
    Daily EOD Scheduler Hook (PSX Trading Days at 6:30 PM PKT / 18:30 PKT).
    Ensures automatic once-per-day EOD ingestion, DB persistence, and Telegram/Alert broadcast.
    """
    now_pkt = datetime.now(ZoneInfo(config.TZ))
    today_iso = now_pkt.strftime("%Y-%m-%d")

    if not force:
        if now_pkt.weekday() >= 5:  # Sat/Sun closed
            return {"status": "SKIPPED_WEEKEND"}
        if (now_pkt.hour, now_pkt.minute) < (18, 30):
            return {"status": "BEFORE_1830_PKT"}

    init_nccpl_db()
    with closing(_db_conn()) as c:
        ran = c.execute("SELECT status FROM nccpl_eod_runs WHERE run_day=?", (today_iso,)).fetchone()
        if not force and ran and ran["status"] == "PUBLISHED_OK":
            return {"status": "ALREADY_RAN_TODAY"}

    report = fetch_nccpl_flows(force_refresh=True)
    if report.get("error"):
        return {"status": "ERROR", "detail": report["error"]}

    # Mark run status
    is_today_published = (report.get("report_date_iso") == today_iso) and not report.get("is_delayed")
    run_status = "PUBLISHED_OK" if is_today_published else "DELAYED_FALLBACK"
    with closing(_db_conn()) as c, c:
        c.execute(
            "INSERT OR REPLACE INTO nccpl_eod_runs(run_day, status, report_date, executed_at) VALUES(?,?,?,?)",
            (today_iso, run_status, report.get("report_date_iso"), now_pkt.strftime("%Y-%m-%d %H:%M:%S PKT")),
        )

    # Broadcast concise EOD Institutional Flow Summary if fresh today's report arrived
    if is_today_published or force:
        try:
            from . import notifier
            sm = report.get("summary", {})
            mf_top = report.get("sector_rankings_by_participant", {}).get("MUTUAL FUNDS", {}).get("top_accumulated", [])[:3]
            mf_str = ", ".join(f"{x['sector']} (+${x['net_usd_m']}M)" for x in mf_top) or "None"
            trig = report.get("cross_reference", {}).get("accumulation_triggers", [])[:3]
            trig_str = ", ".join(f"#{x['symbol']} ({x['float_turnover_pct']}%)" for x in trig) or "None"
            msg = (
                f"🏦 <b>NCCPL EOD Institutional Flow ({report.get('report_date')})</b>\n"
                f"• <b>FIPI Net:</b> ${sm.get('fipi_net_usd_m', 0):+0.2f}M\n"
                f"• <b>Mutual Funds Net:</b> ${sm.get('mutual_funds_net_usd_m', 0):+0.2f}M\n"
                f"• <b>Banks/DFI Net:</b> ${sm.get('banks_net_usd_m', 0):+0.2f}M\n"
                f"• <b>Retail (Individuals) Net:</b> ${sm.get('individuals_net_usd_m', 0):+0.2f}M\n"
                f"🔥 <b>MF Top Accumulated Sectors:</b> {mf_str}\n"
                f"⚡ <b>Accumulation Triggers:</b> {trig_str}"
            )
            notifier.send_telegram_alert(msg)
        except Exception:
            pass

    return {"status": run_status, "report_date": report.get("report_date_iso"), "summary": report.get("summary")}
