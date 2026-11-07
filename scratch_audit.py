import urllib.request
import json
import time
import os
import sys
import re

# Enforce UTF-8 encoding for clean Windows console output
sys.stdout.reconfigure(encoding="utf-8")

def audit_all():
    print("=" * 65)
    print("PSX INSTITUTIONAL TERMINAL: FULL FEATURE-BY-FEATURE AUDIT")
    print("=" * 65)

    endpoints = [
        ("1. Cockpit Stats", "http://127.0.0.1:5000/api/stats"),
        ("2. Analyze OGDC 1D", "http://127.0.0.1:5000/api/analyze?symbol=OGDC&tf=1D"),
        ("3. Analyze FTSM 1D", "http://127.0.0.1:5000/api/analyze?symbol=FTSM&tf=1D"),
        ("4. Chart PNG (OGDC 1D)", "http://127.0.0.1:5000/chart/OGDC/1D"),
        ("5. Autonomous Screener", "http://127.0.0.1:5000/api/scan"),
        ("6. Low-Float Radar", "http://127.0.0.1:5000/api/low_float"),
        ("7. Seasonality SINDM", "http://127.0.0.1:5000/api/low_float/seasonality?symbol=SINDM"),
        ("8. Seasonality FTSM", "http://127.0.0.1:5000/api/low_float/seasonality?symbol=FTSM"),
        ("9. Sector Rotation", "http://127.0.0.1:5000/api/sector_rotation"),
        ("10. Pre-Market Report", "http://127.0.0.1:5000/api/reports/premarket"),
        ("11. EOD Debrief Report", "http://127.0.0.1:5000/api/reports/eod"),
        ("12. Intraday Radar", "http://127.0.0.1:5000/api/intraday/radar"),
        ("13. Position Sizer", "http://127.0.0.1:5000/api/sizer?capital=500000&risk=1.5&entry=100&stop=95"),
        ("14. Alerts Stream", "http://127.0.0.1:5000/api/alerts")
    ]

    findings = []

    for name, url in endpoints:
        t0 = time.time()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "AuditScript/1.0"})
            with urllib.request.urlopen(req, timeout=30) as res:
                elapsed = time.time() - t0
                content_type = res.headers.get("Content-Type", "")
                raw = res.read()
                
                if "image" in content_type:
                    size_kb = len(raw) / 1024
                    print(f"[OK] {name:25s} | Status {res.status} | {elapsed:.2f}s | Image Size: {size_kb:.1f} KB")
                    continue
                
                data = json.loads(raw.decode("utf-8"))
                has_error = isinstance(data, dict) and data.get("error") is not None
                
                status_str = "ERROR" if has_error else "OK"
                count_info = len(data) if isinstance(data, (dict, list)) else 1
                print(f"[{status_str}] {name:25s} | Status {res.status} | {elapsed:.2f}s | Response Items: {count_info}")
                
                if has_error:
                    findings.append((name, f"API returned error: {data.get('error')}"))

                # Deep inspection of data contents
                if "Analyze" in name:
                    if "matrix" not in data or len(data.get("matrix", [])) == 0:
                        findings.append((name, "Matrix table is empty or missing"))
                    if "smc" not in data or not data.get("smc"):
                        findings.append((name, "SMC data is missing"))
                    if not data.get("current_price"):
                        findings.append((name, "Current price is None or 0"))

                elif "Autonomous Screener" in name:
                    opps = data.get("top_opportunities", [])
                    traps = data.get("danger_traps", [])
                    print(f"      -> Screener: {len(opps)} Opportunities, {len(traps)} Traps, Regime: {data.get('market_regime')}")

                elif "Low-Float Radar" in name:
                    stocks = data.get("stocks", [])
                    print(f"      -> Total Low-Float stocks returned: {len(stocks)}")
                    ftsm = next((s for s in stocks if s["symbol"] == "FTSM"), None)
                    if ftsm:
                        print(f"      -> FTSM check: Name='{ftsm.get('name')}', Sector='{ftsm.get('sector')}'")
                        if "Fateh Textile" in ftsm.get("name", ""):
                            findings.append((name, "FTSM is misnamed as Fateh Textile instead of First Tri-Star Modaraba"))
                        if ftsm.get("sector") != "Modarabas":
                            findings.append((name, f"FTSM sector is '{ftsm.get('sector')}', expected 'Modarabas'"))

                elif "Sector Rotation" in name:
                    sectors = data if isinstance(data, list) else data.get("sectors", [])
                    print(f"      -> Total Sectors returned: {len(sectors)}")
                    for sec in sectors:
                        if sec.get("sector") == "Modarabas & Financials":
                            scrip_symbols = [sc["symbol"] for sc in sec.get("scrips", [])]
                            print(f"      -> Modaraba Scrips in Sector Flow: {scrip_symbols}")

                elif "Seasonality" in name:
                    if not data.get("has_data"):
                        findings.append((name, f"No seasonal backtest data returned for {name}"))
                    else:
                        best = data.get('best_month', {})
                        curr = data.get('current_month', {})
                        print(f"      -> Seasonality {data.get('symbol')}: Best={best.get('name')} ({best.get('win_rate')}%), Current={curr.get('month_name')} ({curr.get('win_rate')}%)")

                elif "Intraday Radar" in name:
                    kz = data.get("kill_zone", {})
                    print(f"      -> Kill-Zone Phase: '{kz.get('phase_name')}', Can Enter: {kz.get('can_enter')}")

                elif "Report" in name:
                    print(f"      -> Report Title: '{data.get('title')}', Generated: {data.get('generated_at')}")

        except Exception as ex:
            elapsed = time.time() - t0
            print(f"[FAIL] {name:25s} | {elapsed:.2f}s | Exception: {ex}")
            findings.append((name, f"Exception occurred: {str(ex)}"))

    print("\n" + "=" * 65)
    print("FRONTEND TEMPLATE (index.html) DEEP AUDIT")
    print("=" * 65)
    
    with open("web/templates/index.html", "r", encoding="utf-8") as f:
        html = f.read()

    # 1. Check all getElementById calls have matching elements in HTML
    dom_ids_called = set(re.findall(r"document\.getElementById\(['\"]([a-zA-Z0-9_-]+)['\"]\)", html))
    dom_ids_in_html = set(re.findall(r'id=["\']([a-zA-Z0-9_-]+)["\']', html))

    missing_ids = dom_ids_called - dom_ids_in_html
    print(f"Total DOM IDs called in JavaScript: {len(dom_ids_called)}")
    print(f"Total DOM IDs defined in HTML: {len(dom_ids_in_html)}")
    if missing_ids:
        print(f"MISSING DOM IDs referenced in JS but NOT in HTML ({len(missing_ids)}):")
        for m in sorted(missing_ids):
            print(f"   - {m}")
            findings.append(("Frontend DOM Check", f"Element ID '{m}' referenced in JS but does not exist in HTML"))
    else:
        print("OK: All JavaScript getElementById references match valid HTML elements!")

    # 2. Check for leftover forbidden branding keywords
    forbidden = ["SCS TRADER", "SCSTRADE", "GUARDEER"]
    for word in forbidden:
        matches = [m.start() for m in re.finditer(re.escape(word), html, re.IGNORECASE)]
        if matches:
            print(f"WARNING: Found {len(matches)} occurrences of forbidden label '{word}' in index.html!")
            findings.append(("Frontend Branding Check", f"Forbidden label '{word}' found in index.html"))
        else:
            print(f"OK: Forbidden label '{word}' is completely clean from index.html.")

    print("\n" + "=" * 65)
    print("SUMMARY OF AUDIT FINDINGS")
    print("=" * 65)
    if not findings:
        print("ZERO GLITCHES FOUND! All 14 endpoints, data models, and DOM bindings are 100% HEALTHY.")
    else:
        print(f"Total Issues/Glitches Identified: {len(findings)}")
        for comp, issue in findings:
            print(f" - [{comp}]: {issue}")

if __name__ == "__main__":
    audit_all()
