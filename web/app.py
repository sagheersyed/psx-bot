"""Flask dashboard. Chalayein: python web/app.py"""
import os
import sys
import webbrowser
from pathlib import Path
from threading import Timer

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from flask import Flask, request, jsonify, send_file, render_template  # noqa: E402

import config  # noqa: E402
from psx import data, journal  # noqa: E402
from psx.analyzer import analyze_stock  # noqa: E402
from psx.charts import generate_candlestick_chart  # noqa: E402
from psx.screener import scan_market  # noqa: E402
from psx.sizer import calculate_position_size  # noqa: E402
from psx.eagle_eye import start_eagle_eye  # noqa: E402
from psx.notifier import get_recent_alerts, broadcast_alert  # noqa: E402

app = Flask(__name__, template_folder=str(Path(__file__).resolve().parent / "templates"))
TF_BY_NAME = {t["name"]: t for t in config.TIMEFRAMES}


def _valid_symbol(s: str) -> bool:
    return s.isalnum() and 2 <= len(s) <= 10


@app.after_request
def add_header(response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.route("/")
def index():
    return render_template("index.html", view_mode="main")


@app.route("/low_float")
@app.route("/radar")
def low_float_page():
    return render_template("index.html", view_mode="lowfloat")


@app.route("/api/analyze")
def api_analyze():
    symbol = request.args.get("symbol", "OGDC").upper().strip()
    if not _valid_symbol(symbol):
        return jsonify({"error": "Invalid symbol"}), 400
    return jsonify(analyze_stock(symbol, chart_tf=request.args.get("tf", "1D").upper().strip()))


@app.route("/api/scan")
def api_scan():
    force = request.args.get("refresh", "0") == "1"
    return jsonify(scan_market(force_refresh=force))


@app.route("/api/low_float")
def api_low_float():
    try:
        from psx.low_float_analyzer import analyze_low_float_stocks
        force = request.args.get("refresh", "0") == "1"
        return jsonify(analyze_low_float_stocks(force_refresh=force))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/stats")
def api_stats():
    return jsonify(journal.live_stats())


@app.route("/api/sizer")
def api_sizer():
    try:
        capital = float(request.args.get("capital", 500000))
        risk_pct = float(request.args.get("risk", 1.5))
        entry = float(request.args.get("entry", 0))
        stop = float(request.args.get("stop", 0))
        return jsonify(calculate_position_size(capital, risk_pct, entry, stop))
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/alerts")
def api_alerts():
    return jsonify(get_recent_alerts())


@app.route("/api/alerts/test")
def api_test_alert():
    sample = {
        "symbol": "OGDC",
        "price": 316.24,
        "trigger": "BULLISH_TREND_START",
        "badge": "🟢 BULLISH TREND START",
        "action": "BUY",
        "details": "Eagle-Eye Test Alert: Bullish BOS confirmed, price trading inside wholesale discount zone.",
        "buy_zone": "Rs. 312.00 - 316.24",
        "stop_loss": 302.50,
        "target_1": 328.00,
        "target_2": 345.00,
        "rr": "1:2.4"
    }
    broadcast_alert(sample)
    return jsonify({"status": "sent", "alert": sample})


@app.route("/api/sector_rotation")
def api_sector_rotation():
    from psx.sector_rotation import get_sector_rotation
    refresh = bool(int(request.args.get("refresh", 0)))
    return jsonify(get_sector_rotation(force_refresh=refresh))


@app.route("/api/reports/eod")
def api_reports_eod():
    from psx.reports import generate_post_market_report
    broadcast = bool(int(request.args.get("broadcast", 0)))
    refresh = bool(int(request.args.get("refresh", 0)))
    return jsonify(generate_post_market_report(broadcast=broadcast, force_refresh=refresh))


@app.route("/api/reports/premarket")
def api_reports_premarket():
    from psx.reports import generate_pre_market_report
    broadcast = bool(int(request.args.get("broadcast", 0)))
    refresh = bool(int(request.args.get("refresh", 0)))
    return jsonify(generate_pre_market_report(broadcast=broadcast, force_refresh=refresh))


@app.route("/api/low_float/seasonality")
def api_low_float_seasonality():
    from psx.seasonal_backtest import backtest_stock_seasonality
    sym = request.args.get("symbol", "SINDM").upper().strip()
    return jsonify(backtest_stock_seasonality(sym))


@app.route("/chart/<symbol>/<tf>")
@app.route("/chart/<symbol>")
def chart(symbol, tf="1D"):
    symbol, tf = symbol.upper().strip(), tf.upper().strip()
    if not _valid_symbol(symbol) or tf not in TF_BY_NAME:
        return "", 404
    path = config.CHARTS_DIR / f"{symbol}_{tf}_chart.png"
    if not path.exists():
        cfg = TF_BY_NAME[tf]
        df = data.fetch_history(symbol, cfg["res"], cfg["days"])
        if df is not None and len(df) >= 10:
            from psx.smc import analyze_smc
            smc_tf = analyze_smc(df, float(df["close"].iloc[-1]))
            generate_candlestick_chart(symbol, df, tf, smc_data=smc_tf)
    return send_file(path, mimetype="image/png") if path.exists() else ("", 404)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    host, port = os.getenv("DASHBOARD_HOST", "127.0.0.1"), int(os.getenv("DASHBOARD_PORT", "5000"))
    print(f"🚀 PSX Terminal: http://127.0.0.1:{port}  (host={host})")
    start_eagle_eye(poll_interval=90)
    
    # Pre-warm low float, sector rotation, screener and daily reports in background
    from threading import Thread
    def _prewarm_cache():
        try:
            from psx.low_float_analyzer import analyze_low_float_stocks
            analyze_low_float_stocks()
            from psx.sector_rotation import get_sector_rotation
            get_sector_rotation()
            from psx.screener import scan_market
            scan_market()
            from psx.reports import generate_post_market_report, generate_pre_market_report
            generate_post_market_report()
            generate_pre_market_report()
            print("⚡ All Institutional terminal caches pre-warmed (<0.05s response time)!")
        except Exception as e:
            print("Prewarm notice:", e)

    Thread(target=_prewarm_cache, daemon=True).start()
    
    if host == "127.0.0.1":
        Timer(1.2, lambda: webbrowser.open_new(f"http://127.0.0.1:{port}")).start()
    app.run(host=host, port=port, debug=False)
