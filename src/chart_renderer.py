"""Render chart candlestick beranotasi (M15 + H1) sebagai PNG untuk AI vision."""
import io

import mplfinance as mpf
import pandas as pd


def _make_addplots(df, zones=None, levels=None, show_ema=True):
    adds = []
    if show_ema and "ema20" in df.columns:
        adds.append(mpf.make_addplot(df["ema20"], color="#f0b90b", width=0.9))
    return adds


def render_chart(df, zones=None, levels=None, title="XAUUSD", style="charles",
                 figsize=(16, 9), show_ema=True):
    """Render chart ke bytes PNG. zones: list {top,bottom,type,fresh}; levels: list {name,price}."""
    plot_df = df[["Open", "High", "Low", "Close", "Volume"]].tail(120).copy()
    kwargs = dict(
        type="candle", style=style, volume=False, figsize=figsize,
        tight_layout=True, returnfig=True, xrotation=0, datetime_format="%H:%M",
        scale_padding={"left": 0.1, "right": 0.75, "top": 2.0, "bottom": 0.6},
    )
    adds = _make_addplots(plot_df, show_ema=show_ema)
    if adds:
        kwargs["addplot"] = adds
    fig, axes = mpf.plot(plot_df, **kwargs)
    ax = axes[0]

    for z in (zones or []):
        color = "#26a69a" if z["type"] == "bull" else "#ef5350"
        alpha = 0.35 if z.get("fresh", False) else 0.12
        ax.axhspan(z["bottom"], z["top"], color=color, alpha=alpha)
        ax.text(len(plot_df) + 1, (z["top"] + z["bottom"]) / 2,
                f"{'FRESH ' if z.get('fresh') else ''}{'OB' if z.get('kind') == 'ob' else 'FVG'} {z['type']}",
                fontsize=8, va="center", color=color)

    for lv in (levels or []):
        ax.axhline(lv["price"], color="#42a5f5", linestyle="--", linewidth=0.8, alpha=0.8)
        ax.text(len(plot_df) + 1, lv["price"], lv["name"], fontsize=8, va="center", color="#42a5f5")

    ax.set_title(f"{title} | last: {plot_df['Close'].iloc[-1]:.2f}", fontsize=12)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=100)
    import matplotlib.pyplot as plt
    plt.close(fig)
    return buf.getvalue()
