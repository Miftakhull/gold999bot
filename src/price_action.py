"""Pola price action: pin bar, engulfing, strong close, stop hunt."""


def _body(c):
    return abs(float(c["Close"]) - float(c["Open"]))


def is_pin_bar(c, bullish, min_wick_pct=60):
    """Pin bar: ekor >= min_wick_pct% dari range, close di sisi berlawanan ekor."""
    rng = float(c["High"]) - float(c["Low"])
    if rng <= 0:
        return False
    body_top = max(float(c["Open"]), float(c["Close"]))
    body_bot = min(float(c["Open"]), float(c["Close"]))
    if bullish:
        lower_wick = body_bot - float(c["Low"])
        return (lower_wick >= min_wick_pct / 100 * rng
                and float(c["Close"]) >= body_bot + (rng - lower_wick) * 0.5)
    upper_wick = float(c["High"]) - body_top
    return (upper_wick >= min_wick_pct / 100 * rng
            and float(c["Close"]) <= body_top - (rng - upper_wick) * 0.5)


def is_engulfing(c, prev, bullish):
    """Engulfing: body candle menelan full body candle sebelumnya, searah."""
    if bullish:
        return (float(c["Close"]) > float(c["Open"])
                and float(prev["Close"]) < float(prev["Open"])
                and float(c["Close"]) > float(prev["Open"])
                and float(c["Open"]) <= float(prev["Close"]))
    return (float(c["Close"]) < float(c["Open"])
            and float(prev["Close"]) > float(prev["Open"])
            and float(c["Close"]) < float(prev["Open"])
            and float(c["Open"]) >= float(prev["Close"]))


def is_strong_close(c, zone, bullish):
    """Candle menyentuh zona lalu close keluar zona searah, body dominan."""
    rng = float(c["High"]) - float(c["Low"])
    if rng <= 0:
        return False
    body = _body(c)
    if body < rng * 0.5:
        return False
    if bullish:
        return float(c["Low"]) <= zone["top"] and float(c["Close"]) > zone["top"]
    return float(c["High"]) >= zone["bottom"] and float(c["Close"]) < zone["bottom"]


def has_stop_hunt(df, zone, bullish, lookback=3):
    """Stop hunt: dalam `lookback` candle terakhir ada wick menyapu kebalik
    zona (melewati batas zona) lalu close balik."""
    seg = df.iloc[-lookback:]
    for _, c in seg.iterrows():
        if bullish:
            if float(c["Low"]) < zone["bottom"] and float(c["Close"]) > zone["bottom"]:
                return True
        else:
            if float(c["High"]) > zone["top"] and float(c["Close"]) < zone["top"]:
                return True
    return False


def confirm_pa(df, zone, bullish, min_wick_pct=60):
    """Candle terakhir (sudah close) mengonfirmasi zona. Return (bool, nama_pola)."""
    c = df.iloc[-1]
    prev = df.iloc[-2]
    if is_pin_bar(c, bullish, min_wick_pct):
        return True, "pin bar"
    if is_engulfing(c, prev, bullish):
        return True, "engulfing"
    if is_strong_close(c, zone, bullish):
        return True, "strong close"
    return False, ""
