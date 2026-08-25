"""Ambil data candle XAU/USD dari TwelveData, fallback yfinance."""
import pandas as pd
import requests


def fetch_twelvedata(symbol, interval, outputsize, api_key):
    url = "https://api.twelvedata.com/time_series"
    params = {
        "symbol": symbol,
        "interval": interval,
        "outputsize": outputsize,
        "apikey": api_key,
        "order": "ASC",
    }
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    data = r.json()
    if data.get("status") != "ok" or "values" not in data:
        raise RuntimeError(f"TwelveData error: {data}")
    df = pd.DataFrame(data["values"])
    df["datetime"] = pd.to_datetime(df["datetime"])
    df = df.set_index("datetime").astype(float)
    df = df.rename(columns={"open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume"})
    if "Volume" not in df.columns:
        df["Volume"] = 0.0
    df.index = df.index.tz_localize("UTC")
    return df[["Open", "High", "Low", "Close", "Volume"]]


def fetch_yfinance(interval, outputsize):
    import yfinance as yf
    yf_map = {"5min": "5m", "15min": "15m", "1h": "60m"}
    yf_interval = yf_map.get(interval, "15m")
    period = {"5m": "60d", "15m": "60d", "60m": "730d"}.get(yf_interval, "60d")
    df = yf.download("GC=F", period=period, interval=yf_interval, progress=False)
    if df is None or df.empty:
        raise RuntimeError("yfinance kosong")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.rename(columns=str.title)[["Open", "High", "Low", "Close", "Volume"]]
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    else:
        df.index = df.index.tz_convert("UTC")
    return df.tail(outputsize)


def fetch(symbol, interval, outputsize, api_key):
    try:
        return fetch_twelvedata(symbol, interval, outputsize, api_key), "twelvedata"
    except Exception:
        return fetch_yfinance(interval, outputsize), "yfinance"
