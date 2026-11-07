import os
from pathlib import Path
import config


def generate_candlestick_chart(symbol: str, df, tf_name: str = "1D", support: float = None, resistance: float = None, stop_loss: float = None, smc_data: dict = None) -> str:
    """
    Generate professional dark-mode candlestick chart with Clean Institutional SMC Overlays:
    - Collision-free text placement with breathing room margin
    - 50% Equilibrium Line
    - OTE 62%-79% Fibonacci Discount Zone (Gold Span)
    - Bullish Order Block (+OB Demand Green Span)
    - Bearish Order Block (-OB Supply Red Span)
    - Fair Value Gaps (FVG Cyan/Magenta Spans)
    - BSL & SSL Liquidity Lines
    - Precise Support, Resistance, and Stop Loss markers
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import mplfinance as mpf
        from psx.smc import analyze_smc

        if df is None or len(df) < 5:
            return ""

        # Auto-compute timeframe-specific SMC data if not passed or empty
        if not smc_data:
            try:
                curr_p = float(df["close"].iloc[-1])
                smc_data = analyze_smc(df, curr_p)
            except Exception:
                smc_data = {}

        bars_to_show = min(55, len(df))
        chart_df = df.tail(bars_to_show).copy().rename(columns=str.title)
        
        # Professional Institutional Dark Color Palette
        mc = mpf.make_marketcolors(
            up="#00c087", down="#ff3860",
            edge={"up": "#00c087", "down": "#ff3860"},
            wick={"up": "#00c087", "down": "#ff3860"},
            volume="in"
        )
        style = mpf.make_mpf_style(
            base_mpf_style="nightclouds",
            marketcolors=mc,
            gridcolor="#1b222d",
            facecolor="#0b0e14",
            edgecolor="#1f2937",
            figcolor="#07090e",
            y_on_right=True
        )

        path = str(config.CHARTS_DIR / f"{symbol}_{tf_name}_chart.png")
        
        kw = dict(
            type="candle",
            style=style,
            volume=True,
            title=f"\nPSX: {symbol} - Timeframe: {tf_name} (Institutional SMC Engine)",
            returnfig=True,
            figsize=(11, 6.2)
        )
        if len(chart_df) >= 20:
            kw["mav"] = (9, 20)

        fig, axlist = mpf.plot(chart_df, **kw)
        ax = axlist[0]

        c_min = float(chart_df["Low"].min())
        c_max = float(chart_df["High"].max())
        price_range = max(c_max - c_min, 1.0)

        # Helper for clean pill badge styling
        def badge(color, alpha=0.9):
            return dict(boxstyle="round,pad=0.25", facecolor="#07090e", edgecolor=color, alpha=alpha, linewidth=0.8)

        # 1. SMC Visual Overlays: OTE Discount & Equilibrium
        if smc_data:
            ote = smc_data.get("ote_poi")
            if ote:
                fib_50 = ote.get("fib_50")
                if fib_50 and (c_min * 0.92 <= fib_50 <= c_max * 1.08):
                    ax.axhline(fib_50, color="#94a3b8", linestyle="--", linewidth=1.1, alpha=0.75)
                    ax.text(1.5, fib_50, f" 50% Eq: Rs. {fib_50:.2f} ", color="#cbd5e1", fontsize=7.5,
                            va="bottom", bbox=badge("#64748b"))

                # OTE 62% - 79% Zone
                fib_62 = ote.get("fib_62")
                fib_79 = ote.get("fib_79")
                if fib_62 and fib_79:
                    y_low = min(fib_62, fib_79)
                    y_high = max(fib_62, fib_79)
                    if (y_high >= c_min * 0.95 and y_low <= c_max * 1.05):
                        ax.axhspan(y_low, y_high, color="#f59e0b", alpha=0.15)
                        ax.text(bars_to_show * 0.40, (y_low + y_high) / 2, f" OTE 62%-79% (Rs. {y_low:.2f} - {y_high:.2f}) ",
                                color="#f59e0b", fontsize=7.5, fontweight="bold", va="center", bbox=badge("#f59e0b"))

            # 2. Bullish & Bearish Order Blocks
            obs = smc_data.get("order_blocks") or smc_data.get("all_obs") or []
            ob_drawn = 0
            for ob in obs:
                if ob_drawn >= 3:
                    break
                ob_bottom = ob.get("bottom")
                ob_top = ob.get("top")
                if ob_bottom and ob_top and (ob_top >= c_min * 0.95 and ob_bottom <= c_max * 1.05):
                    if ob.get("type") == "BULLISH_OB":
                        ax.axhspan(ob_bottom, ob_top, color="#10b981", alpha=0.18)
                        ax.text(bars_to_show - 10, (ob_top + ob_bottom) / 2, " +OB Demand ", color="#10b981",
                                fontsize=7.5, fontweight="bold", va="center", bbox=badge("#10b981"))
                        ob_drawn += 1
                    elif ob.get("type") == "BEARISH_OB":
                        ax.axhspan(ob_bottom, ob_top, color="#ef4444", alpha=0.18)
                        ax.text(bars_to_show - 10, (ob_top + ob_bottom) / 2, " -OB Supply ", color="#ef4444",
                                fontsize=7.5, fontweight="bold", va="center", bbox=badge("#ef4444"))
                        ob_drawn += 1

            # 3. Fair Value Gaps (FVG)
            fvgs = smc_data.get("active_fvgs", [])
            fvg_drawn = 0
            for fvg in fvgs:
                if fvg_drawn >= 2:
                    break
                fb = fvg.get("bottom")
                ft = fvg.get("top")
                if fb and ft and (ft >= c_min * 0.95 and fb <= c_max * 1.05):
                    if fvg.get("type") == "BULLISH_FVG":
                        ax.axhspan(fb, ft, color="#06b6d4", alpha=0.14)
                        ax.text(bars_to_show * 0.70, (fb + ft) / 2, " Bullish FVG ", color="#06b6d4",
                                fontsize=7.0, va="center", bbox=badge("#06b6d4"))
                        fvg_drawn += 1
                    elif fvg.get("type") == "BEARISH_FVG":
                        ax.axhspan(fb, ft, color="#ec4899", alpha=0.14)
                        ax.text(bars_to_show * 0.70, (fb + ft) / 2, " Bearish FVG ", color="#ec4899",
                                fontsize=7.0, va="center", bbox=badge("#ec4899"))
                        fvg_drawn += 1

            # 4. BSL & SSL Liquidity Lines
            last_sh = smc_data.get("last_swing_high")
            last_sl = smc_data.get("last_swing_low")
            if last_sh and (c_min * 0.90 <= last_sh <= c_max * 1.10):
                ax.axhline(last_sh, color="#f87171", linestyle=":", linewidth=1.1, alpha=0.85)
                ax.text(1.5, last_sh, f" BSL: Rs. {last_sh:.2f} ", color="#f87171", fontsize=7.5, va="bottom", bbox=badge("#f87171"))
            if last_sl and (c_min * 0.90 <= last_sl <= c_max * 1.10):
                ax.axhline(last_sl, color="#4ade80", linestyle=":", linewidth=1.1, alpha=0.85)
                ax.text(1.5, last_sl, f" SSL: Rs. {last_sl:.2f} ", color="#4ade80", fontsize=7.5, va="top", bbox=badge("#4ade80"))

        # 5. Key Support, Resistance, and Strict Stop Loss
        if stop_loss and stop_loss > 0 and (c_min * 0.90 <= stop_loss <= c_max * 1.05):
            ax.axhline(stop_loss, color="#ff3860", linestyle="--", linewidth=1.2, alpha=0.9)
            ax.text(bars_to_show - 2, stop_loss, f" SL: Rs. {stop_loss:.2f} ", color="#ff3860",
                    fontsize=8.0, fontweight="bold", va="bottom", ha="right", bbox=badge("#ff3860"))

        if support and support > 0 and (c_min * 0.90 <= support <= c_max * 1.05):
            ax.axhline(support, color="#38bdf8", linestyle="--", linewidth=1.0, alpha=0.8)
            ax.text(bars_to_show - 2, support, f" Sup: Rs. {support:.2f} ", color="#38bdf8",
                    fontsize=7.5, va="bottom", ha="right", bbox=badge("#38bdf8"))

        if resistance and resistance > 0 and (c_min * 0.95 <= resistance <= c_max * 1.15):
            ax.axhline(resistance, color="#34d399", linestyle="--", linewidth=1.0, alpha=0.8)
            ax.text(bars_to_show - 2, resistance, f" Res: Rs. {resistance:.2f} ", color="#34d399",
                    fontsize=7.5, va="bottom", ha="right", bbox=badge("#34d399"))

        # Save clean figure
        fig.savefig(path, dpi=125, bbox_inches="tight")
        plt.close("all")
        return path
    except Exception as e:
        print(f"Chart error {symbol} {tf_name}: {e}")
        return ""
