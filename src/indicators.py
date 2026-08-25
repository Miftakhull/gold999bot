"""Indikator teknikal: EMA, RSI, ATR, swing, dealing range."""
import pandas as pd


def ema(series, period):
    return series.ewm(span=period, adjust=False).mean()


def rsi(close, period=14):
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain / loss.replace(0, pd.NA)
    return 100 - (100 / (1 + rs))


def atr(df, period=14):
    h, l, c = df["High"], df["Low"], df["Close"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def swing_high(df, period=20, offset=1):
    """Swing high tertinggi dari `period` candle sebelum candle terakhir (offset utk skip candle berjalan)."""
    window = df["High"].iloc[-(period + offset):-offset] if offset else df["High"].iloc[-period:]
    return float(window.max())


def swing_low(df, period=20, offset=1):
    window = df["Low"].iloc[-(period + offset):-offset] if offset else df["Low"].iloc[-period:]
    return float(window.min())


def structure_direction(df, lookback=40):
    """Deteksi HH/HL (bull) atau LH/LL (bear) dari 2 ayunan terakhir."""
    seg = df.iloc[-lookback:]
    half = len(seg) // 2
    h1, h2 = float(seg["High"][:len(seg) - half].max()), float(seg["High"][len(seg) - half:].max())
    l1, l2 = float(seg["Low"][:len(seg) - half].min()), float(seg["Low"][len(seg) - half:].min())
    if h2 > h1 and l2 > l1:
        return "bull"
    if h2 < h1 and l2 < l1:
        return "bear"
    return "range"


def dealing_range(df, lookback=100):
    """Range dealing H1 utk premium/discount."""
    seg = df.iloc[-lookback:]
    hi, lo = float(seg["High"].max()), float(seg["Low"].min())
    return hi, lo, (hi + lo) / 2


def add_indicators(df, cfg_trend, cfg_smc):
    df = df.copy()
    df["ema20"] = ema(df["Close"], cfg_trend["ema_entry"])
    df["rsi"] = rsi(df["Close"], cfg_trend["rsi_period"])
    df["atr"] = atr(df)
    return df
