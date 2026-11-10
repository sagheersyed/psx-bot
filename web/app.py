"""Flask dashboard. Chalayein: python web/app.py"""
import os
import sys
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import webbrowser
from pathlib import Path
from threading import Timer

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from flask import Flask, request, jsonify, send_file, render_template  # noqa: E402

import config  # noqa: E402
from psx import data, journal  # noqa: E402
from psx.cache_engine import cache  # noqa: E402
from psx.smart_worker import start_smart_worker, get_worker_status  # noqa: E402
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
    if not force:
        cached = cache.get_json("psx:screener")
        if cached:
            return jsonify(cached)
    res = scan_market(force_refresh=force)
    if res and "error" not in res:
        cache.set_json("psx:screener", res, ttl=180)
    return jsonify(res)


@app.route("/api/low_float")
def api_low_float():
    try:
        force = request.args.get("refresh", "0") == "1"
        if not force:
            cached = cache.get_json("psx:low_float")
            if cached:
                return jsonify(cached)
        from psx.low_float_analyzer import analyze_low_float_stocks
        res = analyze_low_float_stocks(force_refresh=force)
        cache.set_json("psx:low_float", res, ttl=180)
        return jsonify(res)
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
    force = bool(int(request.args.get("refresh", 0)))
    if not force:
        cached = cache.get_json("psx:sector_rotation")
        if cached:
            return jsonify(cached)
    from psx.sector_rotation import get_sector_rotation
    res = get_sector_rotation(force_refresh=force)
    cache.set_json("psx:sector_rotation", res, ttl=90)
    return jsonify(res)


@app.route("/api/nccpl/flows")
def api_nccpl_flows():
    try:
        force = bool(int(request.args.get("refresh", 0)))
        target_date = request.args.get("date", "").strip() or None
        if not force and not target_date:
            cached = cache.get_json("psx:nccpl:flows")
            if cached:
                return jsonify(cached)
        from psx.nccpl_tracker import fetch_nccpl_flows
        res = fetch_nccpl_flows(target_date=target_date, force_refresh=force)
        if res and "error" not in res and not target_date:
            cache.set_json("psx:nccpl:flows", res, ttl=300)
        return jsonify(res)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/reports/eod")
def api_reports_eod():
    broadcast = bool(int(request.args.get("broadcast", 0)))
    refresh = bool(int(request.args.get("refresh", 0)))
    if not refresh and not broadcast:
        cached = cache.get_json("psx:reports:eod")
        if cached:
            return jsonify(cached)
    from psx.reports import generate_post_market_report
    res = generate_post_market_report(broadcast=broadcast, force_refresh=refresh)
    cache.set_json("psx:reports:eod", res, ttl=600)
    return jsonify(res)


@app.route("/api/reports/premarket")
def api_reports_premarket():
    broadcast = bool(int(request.args.get("broadcast", 0)))
    refresh = bool(int(request.args.get("refresh", 0)))
    if not refresh and not broadcast:
        cached = cache.get_json("psx:reports:premarket")
        if cached:
            return jsonify(cached)
    from psx.reports import generate_pre_market_report
    res = generate_pre_market_report(broadcast=broadcast, force_refresh=refresh)
    cache.set_json("psx:reports:premarket", res, ttl=600)
    return jsonify(res)


@app.route("/api/low_float/seasonality")
def api_low_float_seasonality():
    from psx.seasonal_backtest import backtest_stock_seasonality
    sym = request.args.get("symbol", "SINDM").upper().strip()
    return jsonify(backtest_stock_seasonality(sym))


@app.route("/api/intraday/radar")
def api_intraday_radar():
    try:
        force = bool(int(request.args.get("refresh", 0)))
        if not force:
            cached = cache.get_json("psx:intraday:radar")
            if cached:
                return jsonify(cached)
        from psx.intraday_engine import scan_intraday_radar
        res = scan_intraday_radar(force_refresh=force)
        cache.set_json("psx:intraday:radar", res, ttl=45)
        return jsonify(res)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/worker/status")
def api_worker_status():
    return jsonify(get_worker_status())


@app.route("/api/candles/<symbol>/<tf>")
@app.route("/api/candles/<symbol>")
def api_candles(symbol, tf="1D"):
    symbol, tf = symbol.upper().strip(), tf.upper().strip()
    if not _valid_symbol(symbol) or tf not in TF_BY_NAME:
        return jsonify({"error": "Invalid symbol or timeframe"}), 400

    cache_key = f"psx:candles:{symbol}:{tf}"
    cached = cache.get_json(cache_key)
    if cached:
        return jsonify(cached)

    cfg = TF_BY_NAME[tf]
    df = data.fetch_history(symbol, cfg["res"], cfg["days"])
    if df is None or len(df) < 5:
        return jsonify({"error": f"No candle history for {symbol}"}), 404

    is_intraday = tf in ("60M", "30M", "15M", "5M", "1M")
    candles = []
    volumes = []
    for idx, row in df.iterrows():
        t_val = int(idx.timestamp()) if is_intraday else idx.strftime("%Y-%m-%d")
        c_open, c_high, c_low, c_close = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
        c_vol = float(row.get("volume", 0))

        candles.append({
            "time": t_val,
            "open": round(c_open, 2),
            "high": round(c_high, 2),
            "low": round(c_low, 2),
            "close": round(c_close, 2)
        })
        volumes.append({
            "time": t_val,
            "value": round(c_vol, 0),
            "color": "rgba(0, 192, 135, 0.45)" if c_close >= c_open else "rgba(255, 56, 96, 0.45)"
        })

    from psx.smc import analyze_smc
    smc_data = analyze_smc(df, float(df["close"].iloc[-1]))

    payload = {
        "symbol": symbol,
        "tf": tf,
        "candles": candles,
        "volumes": volumes,
        "current_price": float(df["close"].iloc[-1]),
        "smc": {
            "bias": smc_data.get("smc_bias"),
            "structure": smc_data.get("structure"),
            "order_blocks": smc_data.get("order_blocks", [])[:3]
        }
    }
    cache.set_json(cache_key, payload, ttl=30)
    return jsonify(payload)


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
    host, port = os.getenv("DASHBOARD_HOST", "127.0.0.1"), int(os.getenv("DASHBOARD_PORT", "5002"))
    print(f"🚀 PSX Terminal: http://127.0.0.1:{port}  (host={host})")
    start_eagle_eye(poll_interval=90)
    
    # Start the Decoupled Background Smart Worker (Serving 6,000+ users via Redis/RAM)
    start_smart_worker()
    print("⚡ [SMART WORKER] Decoupled In-Memory Streaming Engine Activated!")
    
    if host == "127.0.0.1":
        Timer(1.2, lambda: webbrowser.open_new(f"http://127.0.0.1:{port}")).start()
    app.run(host=host, port=port, debug=False)
