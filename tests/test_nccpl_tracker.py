"""Offline & Integration tests for NCCPL Daily EOD FIPI/LIPI & Syndicate Flow Tracker."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from psx import nccpl_tracker


def _sample_feeds():
    mainsum = [
        {"FLType": "FIPI", "FLNetValueUSD": -1.2},
        {"FLType": "LIPI", "FLNetValueUSD": 1.2},
    ]
    mainsumdetails = [
        {"FLType": "MUTUAL FUNDS", "FLBuyValue": 15.0, "FLSellValue": -5.0, "FLNetValueUSD": 10.0},
        {"FLType": "BANKS / DFI", "FLBuyValue": 2.0, "FLSellValue": -11.0, "FLNetValueUSD": -9.0},
        {"FLType": "FOREIGN CORPORATES", "FLBuyValue": 1.0, "FLSellValue": -2.2, "FLNetValueUSD": -1.2},
        {"FLType": "INDIVIDUALS", "FLBuyValue": 20.0, "FLSellValue": -19.5, "FLNetValueUSD": 0.5},
        {"FLType": "INSURANCE COMPANIES", "FLBuyValue": 1.5, "FLSellValue": -1.0, "FLNetValueUSD": 0.5},
        {"FLType": "BROKER PROPRIETARY TRADING", "FLBuyValue": 4.0, "FLSellValue": -4.8, "FLNetValueUSD": -0.8},
    ]
    lipi_rows = [
        {"FLType": "MUTUAL FUNDS", "FLMarket": "REG", "FLBuyValue": 3_000_000_000, "FLSellValue": -1_000_000_000, "NetValue": 2_000_000_000},
        {"FLType": "MUTUAL FUNDS", "FLMarket": "FUT", "FLBuyValue": 1_170_000_000, "FLSellValue": -390_000_000, "NetValue": 780_000_000},
        {"FLType": "BANKS / DFI", "FLMarket": "REG", "FLBuyValue": 556_000_000, "FLSellValue": -3_058_000_000, "NetValue": -2_502_000_000},
        {"FLType": "INDIVIDUALS", "FLMarket": "REG", "FLBuyValue": 5_560_000_000, "FLSellValue": -5_421_000_000, "NetValue": 139_000_000},
    ]
    fipi_rows = [
        {"FLType": "FOREIGN CORPORATES", "FLMarket": "REG", "FLBuyValue": 278_000_000, "FLSellValue": -611_600_000, "NetValue": -333_600_000},
    ]
    investor_sector_rows = [
        {"FLSectorName": "Cement (mn$)", "FLTypeNew": "MUTUAL FUNDS", "FLNetValueUSD": 4.5},
        {"FLSectorName": "Fertilizer (mn$)", "FLTypeNew": "MUTUAL FUNDS", "FLNetValueUSD": 3.2},
        {"FLSectorName": "Commercial Banks (mn$)", "FLTypeNew": "MUTUAL FUNDS", "FLNetValueUSD": 2.1},
        {"FLSectorName": "Textile Composite (mn$)", "FLTypeNew": "MUTUAL FUNDS", "FLNetValueUSD": 0.9},
        {"FLSectorName": "Power Generation and Distribution (mn$)", "FLTypeNew": "MUTUAL FUNDS", "FLNetValueUSD": 0.4},
        {"FLSectorName": "All other Sectors (mn$)", "FLTypeNew": "MUTUAL FUNDS", "FLNetValueUSD": 0.2},
        {"FLSectorName": "Oil and Gas Exploration Companies (mn$)", "FLTypeNew": "MUTUAL FUNDS", "FLNetValueUSD": -1.8},
        {"FLSectorName": "Technology and Communication (mn$)", "FLTypeNew": "MUTUAL FUNDS", "FLNetValueUSD": -0.7},
        {"FLSectorName": "Textile Composite (mn$)", "FLTypeNew": "FIPI", "FLNetValueUSD": 0.3},
        {"FLSectorName": "Technology and Communication (mn$)", "FLTypeNew": "FIPI", "FLNetValueUSD": -1.5},
        {"FLSectorName": "Technology and Communication (mn$)", "FLTypeNew": "INDIVIDUALS", "FLNetValueUSD": 1.2},
    ]
    return mainsum, mainsumdetails, lipi_rows, fipi_rows, investor_sector_rows


def test_aggregation_usd_pkr_and_sector_top5():
    ms, msd, lipi, fipi, inv = _sample_feeds()
    rep = nccpl_tracker.aggregate_nccpl_data(ms, msd, lipi, fipi, inv, "11/10/2026")
    assert rep["report_date_iso"] == "2026-11-10"
    assert rep["summary"]["fipi_net_usd_m"] == -1.2
    assert rep["summary"]["mutual_funds_net_usd_m"] == 10.0

    mf = next(c for c in rep["categories"] if c["category"] == "MUTUAL FUNDS")
    assert mf["net_usd_m"] == 10.0
    assert mf["net_pkr_m"] == 2780.0
    assert mf["bias"] == "ACCUMULATING"

    mf_rank = rep["sector_rankings_by_participant"]["MUTUAL FUNDS"]
    assert len(mf_rank["top_accumulated"]) == 5
    assert mf_rank["top_accumulated"][0]["sector"] == "Cement"
    assert mf_rank["top_distributed"][0]["sector"] == "Oil and Gas Exploration Companies"
    json.dumps(rep)


def test_cross_reference_accumulation_and_trap():
    ms, msd, lipi, fipi, inv = _sample_feeds()
    rep = nccpl_tracker.aggregate_nccpl_data(ms, msd, lipi, fipi, inv, "11/10/2026")

    fake_lf = [
        {
            "symbol": "STML",
            "price": 60.0,
            "change_pct": 9.5,
            "sector": "Textile Composite",
            "float_turnover_pct": 5.0,
            "vol_surge_x": 3.5,
            "syndicate_phase": "🚀 UPPER CIRCUIT LOCK",
            "phase_code": "UPPER_LOCK",
        },
        {
            "symbol": "JATM",
            "price": 78.76,
            "change_pct": -10.0,
            "sector": "Textile Spinning",
            "float_turnover_pct": 9.8,
            "vol_surge_x": 1.2,
            "syndicate_phase": "🚨 LOWER CIRCUIT LOCK",
            "phase_code": "LOWER_LOCK",
        },
    ]
    xref = nccpl_tracker.cross_reference_syndicate_flows(rep, low_float_stocks=fake_lf, sector_rotations=[])
    acc_syms = [x["symbol"] for x in xref["accumulation_triggers"]]
    trap_syms = [x["symbol"] for x in xref["exit_traps"]]
    assert "STML" in acc_syms
    assert "JATM" in trap_syms and "JATM" not in acc_syms


def test_delayed_report_fallback(monkeypatch):
    ms, msd, lipi, fipi, inv = _sample_feeds()
    monkeypatch.setattr(nccpl_tracker, "_probe_official_nccpl_portal", lambda: {"reachable": False, "status": "403"})
    monkeypatch.setattr(nccpl_tracker, "_get_latest_published_date", lambda: "11/06/2026")
    monkeypatch.setattr(nccpl_tracker, "cross_reference_syndicate_flows", lambda r: {"accumulation_triggers": [], "exit_traps": [], "sector_confluence": []})

    def fake_post(ep, dt):
        if dt != "11/06/2026":
            return [{"FLType": "FIPI", "FLNetValueUSD": None}] if ep == "loadmainsum" else []
        return {"loadmainsum": ms, "loadmainsumdetails": msd, "loadlipi": lipi, "loadfipi": fipi, "loadfipiInvestor": inv}[ep]

    monkeypatch.setattr(nccpl_tracker, "_scs_post", fake_post)
    monkeypatch.setattr(nccpl_tracker, "save_nccpl_snapshot", lambda r: None)

    rep = nccpl_tracker.fetch_nccpl_flows(force_refresh=True)
    assert rep["report_date"] == "11/06/2026"
    assert rep["is_delayed"] is True
    assert "11/06/2026" in rep["delay_note"]
