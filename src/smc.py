"""Deteksi zona SMC: BOS/CHoCH, order block, FVG, liquidity sweep."""
import pandas as pd


def find_swings(df, left=3, right=3):
    highs, lows = [], []
    for i in range(left, len(df) - right):
        w = df.iloc[i - left:i + right + 1]
        if df["High"].iloc[i] == w["High"].max():
            highs.append((df.index[i], float(df["High"].iloc[i])))
        if df["Low"].iloc[i] == w["Low"].min():
            lows.append((df.index[i], float(df["Low"].iloc[i])))
    return highs, lows


def detect_bos(df, lookback=60):
    """Break of structure: close menembus swing high/low terakhir. Return 'bull'/'bear'/None + index."""
    seg = df.iloc[-lookback:]
    highs, lows = find_swings(seg)
    if len(highs) < 2 or len(lows) < 2:
        return None, None
    last_close = float(seg["Close"].iloc[-1])
    last_h = highs[-1][1]
    last_l = lows[-1][1]
    if last_close > last_h:
        return "bull", seg.index[-1]
    if last_close < last_l:
        return "bear", seg.index[-1]
    return None, None


def detect_choch(df, lookback=60):
    """Change of character sederhana: BOS berlawanan dengan struktur sebelumnya."""
    seg = df.iloc[-lookback * 2:]
    highs, lows = find_swings(seg)
    if len(highs) < 3 or len(lows) < 3:
        return None
    closes = seg["Close"]
    prev_high_broken = float(closes.iloc[-1]) > highs[-2][1]
    prev_low_broken = float(closes.iloc[-1]) < lows[-2][1]
    # struktur sebelumnya bearish (LH) lalu close tembus high -> CHoCH bull
    if prev_high_broken and highs[-2][1] < highs[-3][1]:
        return "bull"
    if prev_low_broken and lows[-2][1] > lows[-3][1]:
        return "bear"
    return None


def find_order_blocks(df, bos_dir, lookback=60, max_age=40):
    """
    Order block = candle berlawanan terakhir SEBELUM pergerakan impulsif yang menyebabkan BOS.
    Return list of dict: {type, top, bottom, time, mitigated}
    """
    if bos_dir not in ("bull", "bear"):
        return []
    seg = df.iloc[-lookback:]
    blocks = []
    n = len(seg)
    for i in range(n - max_age, n):
        if i < 1:
            continue
        c = seg.iloc[i]
        nxt = seg.iloc[i + 1:]
        if nxt.empty:
            continue
        if bos_dir == "bull" and c["Close"] < c["Open"]:
            # impulsif naik setelahnya
            if float(nxt["High"].max()) > float(c["High"]):
                touched = float(nxt["Low"].min()) <= float(c["Low"])
                blocks.append({"type": "bull", "top": float(c["High"]), "bottom": float(c["Low"]),
                               "time": seg.index[i], "mitigated": touched})
        if bos_dir == "bear" and c["Close"] > c["Open"]:
            if float(nxt["Low"].min()) < float(c["Low"]):
                touched = float(nxt["High"].max()) >= float(c["High"])
                blocks.append({"type": "bear", "top": float(c["High"]), "bottom": float(c["Low"]),
                               "time": seg.index[i], "mitigated": touched})
    return blocks


def find_fvg(df, lookback=40, min_gap_atr=0.15, atr_now=1.0):
    """Fair Value Gap 3-candle. Return list {type, top, bottom, time, mitigated}."""
    seg = df.iloc[-lookback:]
    gaps = []
    for i in range(len(seg) - 1, 1, -1):
        c0, c2 = seg.iloc[i - 2], seg.iloc[i]
        if float(c2["Low"]) > float(c0["High"]):
            top, bottom = float(c2["Low"]), float(c0["High"])
            if top - bottom >= min_gap_atr * atr_now:
                between = seg.iloc[i + 1:]["Low"]
                mitigated = len(between) > 0 and float(between.min()) <= bottom
                gaps.append({"type": "bull", "top": top, "bottom": bottom,
                             "time": seg.index[i], "mitigated": mitigated})
        if float(c2["High"]) < float(c0["Low"]):
            top, bottom = float(c0["Low"]), float(c2["High"])
            if top - bottom >= min_gap_atr * atr_now:
                between = seg.iloc[i + 1:]["High"]
                mitigated = len(between) > 0 and float(between.max()) >= top
                gaps.append({"type": "bear", "top": top, "bottom": bottom,
                             "time": seg.index[i], "mitigated": mitigated})
    return gaps


def find_liquidity_levels(df, asia_hours_utc=(0, 7)):
    """Equal highs/lows + high/low sesi Asia + PDH/PDL."""
    levels = []
    # PDH/PDL
    if len(df) > 96:
        prev_day = df.iloc[-96:-48] if len(df) >= 144 else df.iloc[:-48]
        levels.append({"name": "PDH", "price": float(prev_day["High"].max())})
        levels.append({"name": "PDL", "price": float(prev_day["Low"].min())})
    # Sesi Asia (00:00-07:00 UTC)
    asia = df.between_time(f"{asia_hours_utc[0]:02d}:00", f"{asia_hours_utc[1]-1:02d}:59")
    if not asia.empty and asia.index[-1].date() == df.index[-1].date():
        levels.append({"name": "Asia High", "price": float(asia["High"].max())})
        levels.append({"name": "Asia Low", "price": float(asia["Low"].min())})
    return levels


def detect_sweep(df, levels, lookback=20):
    """Liquidity sweep: high/low tembus level lalu close balik ke dalam."""
    seg = df.iloc[-lookback:]
    sweeps = []
    last = seg.iloc[-1]
    for lv in levels:
        if float(last["High"]) > lv["price"] and float(last["Close"]) < lv["price"]:
            sweeps.append({"level": lv["name"], "price": lv["price"], "dir": "bear"})
        if float(last["Low"]) < lv["price"] and float(last["Close"]) > lv["price"]:
            sweeps.append({"level": lv["name"], "price": lv["price"], "dir": "bull"})
    return sweeps


def analyze(df, cfg_smc, atr_now):
    """Analisa SMC lengkap. Return dict zona & konteks."""
    bos_dir, bos_time = detect_bos(df, cfg_smc["bos_lookback"])
    choch = detect_choch(df, cfg_smc["bos_lookback"])
    obs = find_order_blocks(df, bos_dir, cfg_smc["bos_lookback"], cfg_smc["ob_max_age"]) if bos_dir else []
    fresh_obs = [ob for ob in obs if not ob["mitigated"]]
    fvgs = find_fvg(df, 40, cfg_smc["fvg_min_gap_atr"], atr_now)
    fresh_fvgs = [g for g in fvgs if not g["mitigated"]]
    liq = find_liquidity_levels(df)
    sweeps = detect_sweep(df, liq)
    return {
        "bos": bos_dir,
        "choch": choch,
        "order_blocks": obs[-4:],
        "fresh_obs": fresh_obs[-2:],
        "fvgs": fvgs[-4:],
        "fresh_fvgs": fresh_fvgs[-2:],
        "liquidity": liq,
        "sweeps": sweeps,
    }
