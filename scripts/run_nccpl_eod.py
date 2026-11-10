"""Usage: python scripts/run_nccpl_eod.py [--force]
Fetches latest NCCPL Daily EOD FIPI/LIPI clearing flows, computes Net USD & PKR per category,
ranks Top 5 accumulated/distributed sectors, and cross-references with Low-Float & Volume Surge metrics."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from psx.nccpl_tracker import fetch_nccpl_flows, maybe_run_eod_nccpl_job  # noqa: E402

if __name__ == "__main__":
    force = "--force" in sys.argv
    if "--scheduler" in sys.argv:
        res = maybe_run_eod_nccpl_job(force=force)
        print("NCCPL Scheduler Result:", res)
    else:
        rep = fetch_nccpl_flows(force_refresh=True)
        if rep.get("error"):
            print("ERROR:", rep["error"])
            sys.exit(1)
        sm = rep["summary"]
        print(f"=== NCCPL EOD FLOW REPORT ({rep['report_date']}) ===")
        if rep.get("is_delayed"):
            print("NOTE:", rep["delay_note"])
        print(f"FIPI Net: ${sm['fipi_net_usd_m']:+.3f}M | LIPI Net: ${sm['lipi_net_usd_m']:+.3f}M | Mutual Funds (Eq): ${sm.get('mutual_funds_equity_net_usd_m', sm['mutual_funds_net_usd_m']):+.3f}M | Retail: ${sm['individuals_net_usd_m']:+.3f}M")
        print("\nTop Categories (Equities Net Flow):")
        for c in rep["categories"]:
            eq_u = c.get("equity_net_usd_m", c["net_usd_m"])
            eq_p = c.get("equity_net_pkr_m", c["net_pkr_m"])
            debt_s = f" (Debt: ${c.get('debt_net_usd_m', 0):+.1f}M)" if abs(c.get("debt_net_usd_m", 0)) > 0.1 else ""
            print(f"  {c['category']:<28} | Eq USD: ${eq_u:>+8.3f}M | Eq PKR: Rs.{eq_p:>+9.2f}M | {c['bias']}{debt_s}")
        print("\nMutual Funds Top Accumulated Sectors:")
        for s in rep["sector_rankings_by_participant"].get("MUTUAL FUNDS", {}).get("top_accumulated", []):
            print(f"  + {s['sector']:<38} +${s['net_usd_m']:.3f}M")
        print("\nInstitutional Accumulation Triggers (Cross-Referenced with Float Turnover):")
        for a in rep["cross_reference"]["accumulation_triggers"][:6]:
            print(f"  🔥 {a['symbol']:<6} | FloatTurn: {a['float_turnover_pct']:>5.2f}% | RVOL: {a['vol_surge_x']}x | {a['reason']}")
