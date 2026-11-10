"""
psx/screener.py: Autonomous Smart Market Screener & Institutional Research Engine
Scans top PSX volume leaders & KSE-100 constituents in parallel.
Ranks them into Top Opportunities, Watchlist Setups, and Danger Traps.
"""
from concurrent.futures import ThreadPoolExecutor
import time
from . import analyzer

# Top PSX liquid symbols across E&P, Tech, Cement, Fertilizer, Power, Refinery, Banking
SCREENER_SYMBOLS = [
    "OGDC", "PPL", "MARI", "SYS", "LUCK", "ENGROH", "FFC", "HUBC", 
    "HBL", "MCB", "UBL", "TRG", "CNERGY", "PRL", "WTL", "SINDM", 
    "MACFL", "PAEL", "ATRL", "PSO", "DGKC", "FCCL", "EFERT", "SEARL"
]

_CACHE = {"data": None, "ts": 0}
CACHE_TTL = 180  # Cache scan results for 3 minutes to avoid API spam


def scan_market(symbols: list = None, force_refresh: bool = False) -> dict:
    """
    Autonomous market-wide scan returning:
      - Top Institutional Buy Setups (OTE discount, SSL sweeps, Bullish BOS)
      - High Risk Danger Traps (Lower circuits, Bearish CHoCH, Panic distribution)
      - Market Breadth & Sentiment Regime
    """
    now = time.time()
    if not force_refresh and _CACHE["data"] and (now - _CACHE["ts"]) < CACHE_TTL:
        return _CACHE["data"]

    targets = symbols or SCREENER_SYMBOLS
    results = []

    def _eval(sym):
        try:
            r = analyzer.analyze_stock(sym, chart_tf=None, log=False, fast_mode=True)
            if r and not r.get("error"):
                return r
            if r and r.get("error"):
                print(f"[SCREENER] {sym} returned error: {r.get('error')}")
        except Exception as e:
            import traceback
            print(f"[SCREENER] {sym} exception: {e}")
            traceback.print_exc()
        return None

    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = [ex.submit(_eval, s) for s in targets]
        for f in futures:
            res = f.result()
            if res:
                results.append(res)

    if not results:
        return {"error": "Market scan complete nahi ho saka, live feed check karein."}

    # Partitioning into Opportunities, Watchlist, and Traps
    opportunities = []
    watchlist = []
    danger_traps = []

    bullish_count = 0
    bearish_count = 0
    positive_flow_count = 0

    for r in results:
        score = r.get("score", 0)
        action = r.get("action", "WAIT")
        verdict = r.get("verdict", "")
        gates = r.get("gates", {})
        price = r.get("current_price", 0)
        change_pct = r.get("change_pct", 0)
        sym = r.get("symbol")
        smc = r.get("smc", {})
        ote = smc.get("ote_poi")

        # Market breadth stats
        if score > 15:
            bullish_count += 1
        elif score < -15:
            bearish_count += 1
        if r.get("cmf", 0) > 0:
            positive_flow_count += 1

        summary_item = {
            "symbol": sym,
            "price": price,
            "change_pct": change_pct,
            "score": score,
            "confidence": r.get("confidence", 0),
            "verdict": verdict,
            "action": action,
            "buy_zone": r.get("buy_zone", ""),
            "stop_loss": r.get("stop_loss", ""),
            "target_1": r.get("target_1", ""),
            "rr": r.get("risk_reward", ""),
            "structure": smc.get("structure", "RANGE"),
            "smc_summary": smc.get("smc_summary", ""),
            "in_ote": bool(ote and ote.get("in_ote_zone")),
            "in_discount": bool(ote and ote.get("in_discount"))
        }

        # 1. Danger Traps
        is_trap = (
            "TRAP" in verdict
            or "AVOID" in verdict
            or "LOWER CIRCUIT" in verdict
            or "CRASH" in verdict
            or "REJECTION" in verdict
            or action == "AVOID"
            or score <= -30
            or change_pct <= -6.0
        )

        if is_trap:
            danger_traps.append(summary_item)
        # 2. Top Buy Opportunities (Strictly genuine buys with positive score and no active trap)
        elif action == "BUY" and not is_trap and score >= 25:
            opportunities.append(summary_item)
        # 3. Watchlist / Selective Setups
        else:
            watchlist.append(summary_item)

    # Sort opportunities by score descending
    opportunities.sort(key=lambda x: x["score"], reverse=True)
    danger_traps.sort(key=lambda x: x["score"])
    watchlist.sort(key=lambda x: x["score"], reverse=True)

    # Calculate Market Regime
    total = len(results)
    bull_pct = round((bullish_count / total) * 100, 1) if total else 50.0
    bear_pct = round((bearish_count / total) * 100, 1) if total else 50.0
    flow_pct = round((positive_flow_count / total) * 100, 1) if total else 50.0

    if bull_pct >= 55 and flow_pct >= 50:
        market_regime = "🟢 RISK-ON EXPANSION (Institutional Buying Across Market)"
        regime_desc = f"{bull_pct}% leaders bullish with positive money flow. Swing buys have high market tailwind."
    elif bear_pct >= 55:
        market_regime = "🔴 RISK-OFF CORRECTION (Broad Market Supply Pressure)"
        regime_desc = f"{bear_pct}% leaders under distribution. Keep tight stop losses and reduce position sizes."
    else:
        market_regime = "🟡 SELECTIVE ROTATION (Stock-Specific Action)"
        regime_desc = f"Market is mixed ({bull_pct}% Bull / {bear_pct}% Bear). Smart money is rotating selectively into discount POIs."

    report = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "total_scanned": total,
        "market_regime": market_regime,
        "regime_desc": regime_desc,
        "bull_pct": bull_pct,
        "bear_pct": bear_pct,
        "flow_pct": flow_pct,
        "top_opportunities": opportunities[:5],
        "top_watchlist": watchlist[:6],
        "danger_traps": danger_traps[:5]
    }

    _CACHE["data"] = report
    _CACHE["ts"] = now
    return report
