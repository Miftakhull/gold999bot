"""Bangun sinyal lengkap (entry/SL/TP) dari hasil hitung engine + checklist skor."""
from indicators import swing_high, swing_low, dealing_range, ema, structure_direction


def bias_m15(df_m15, cfg_s):
    """Bias utk scalp: EMA20/50 M15 + struktur."""
    c = df_m15["Close"]
    e20, e50 = ema(c, cfg_s["bias_ema_fast"]), ema(c, cfg_s["bias_ema_slow"])
    struct = structure_direction(df_m15, 40)
    if float(e20.iloc[-1]) > float(e50.iloc[-1]) and struct == "bull":
        return "bull"
    if float(e20.iloc[-1]) < float(e50.iloc[-1]) and struct == "bear":
        return "bear"
    return "range"


def build_scalp(df_m5, zones, bias, h1_levels, cfg, atr_m5):
    """
    Scalp S/D + PA. Return (signal|None, info).
    Wajib: zona fresh searah bias + konfirmasi PA. Skor >= min_score.
    """
    s = cfg["scalp"]
    if bias == "range":
        return None, {"reason": "bias M15 range -> scalp mati"}
    if atr_m5 < s["atr_min"]:
        return None, {"reason": f"ATR M5 {atr_m5:.2f} < {s['atr_min']} (market mati/spread)"}

    direction = bias  # hanya zona searah bias
    ztype = "bull" if direction == "bull" else "bear"
    last = df_m5.iloc[-1]
    last_price = float(last["Close"])

    # zona searah bias yang paling baru terbentuk & sedang didekati harga
    candidates = [z for z in zones if z["type"] == ztype]
    if not candidates:
        return None, {"reason": "tidak ada zona fresh searah bias"}
    candidates.sort(key=lambda z: z["time"], reverse=True)
    zone = None
    for z in candidates:
        touched = (last_price <= z["top"] + 0.2 * atr_m5) if ztype == "bull" \
            else (last_price >= z["bottom"] - 0.2 * atr_m5)
        if touched:
            zone = z
            break
    if zone is None:
        return None, {"reason": "belum ada pullback ke zona"}

    # konfirmasi price action pada candle terakhir (sudah close)
    from price_action import confirm_pa, has_stop_hunt
    ok_pa, pattern = confirm_pa(df_m5, zone, ztype == "bull", s["pa_min_wick_pct"])
    if not ok_pa:
        return None, {"reason": "belum ada konfirmasi PA"}

    # checklist skor
    score, max_score = 2, 6  # zona fresh + PA = wajib
    checks = {"zone_fresh": True, "pa": pattern}
    if zone["strength"] >= 2.0:
        score += 2
        checks["strong_impulse"] = True
    if has_stop_hunt(df_m5, zone, ztype == "bull"):
        score += 2
        checks["stop_hunt"] = True
    confluence = any(abs(lv["price"] - zone["top"]) <= 0.5 * atr_m5
                     or abs(lv["price"] - zone["bottom"]) <= 0.5 * atr_m5
                     or zone["bottom"] <= lv["price"] <= zone["top"]
                     for lv in (h1_levels or []))
    if confluence:
        score += 1
        checks["htf_confluence"] = True
    if score < s["min_score"]:
        return None, {"reason": f"skor {score}/{max_score} < {s['min_score']}", "score": score}

    entry = float(last["Close"])
    if ztype == "bull":
        sl = zone["bottom"] - s["sl_atr_buffer"] * atr_m5
    else:
        sl = zone["top"] + s["sl_atr_buffer"] * atr_m5
    risk = abs(entry - sl)
    if risk <= 0:
        return None, {"reason": "risk invalid"}
    tp1 = entry + risk * s["tp1_r"] if ztype == "bull" else entry - risk * s["tp1_r"]

    # TP2: zona berlawanan terdekat / level liquidity, min 1.5R
    targets = [z["bottom"] if z["type"] == "bear" else z["top"] for z in zones if z["type"] != ztype]
    targets += [lv["price"] for lv in (h1_levels or [])]
    if ztype == "bull":
        ahead = sorted([p for p in targets if p >= entry + s["tp2_min_r"] * risk])
    else:
        ahead = sorted([p for p in targets if p <= entry - s["tp2_min_r"] * risk], reverse=True)
    if not ahead:
        return None, {"reason": "tidak ada target >= 1.5R -> skip"}
    tp2 = ahead[0]

    signal = {
        "strategy": "SCALP",
        "direction": "Buy" if ztype == "bull" else "Sell",
        "entry": entry,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "risk": risk,
        "atr": atr_m5,
        "score": score,
        "max_score": max_score,
        "checks": checks,
        "pattern": pattern,
        "zone": {"top": zone["top"], "bottom": zone["bottom"], "strength": round(zone["strength"], 1)},
        "bar_time": last.name,
    }
    return signal, {"reason": "ok", "score": score}


def build_trend(df_m15, df_h1, cfg, ind):
    """Checklist TREND. Return (signal|None, checklist dict, skor)."""
    t = cfg["trend"]
    last = df_m15.iloc[-1]
    prev = df_m15.iloc[-2]
    atr = float(ind["atr"].iloc[-1])
    rsi_v = float(ind["rsi"].iloc[-1])

    bias = bias_h1(df_h1, t)
    if bias["direction"] == "range":
        return None, {"bias": "range - jalur mati"}, 0

    direction = bias["direction"]
    sw_high = swing_high(df_m15, t["swing_period"])
    sw_low = swing_low(df_m15, t["swing_period"])

    # Wajib: breakout close konfirmasi
    if direction == "bull":
        breakout = float(last["Close"]) > sw_high and float(prev["Close"]) <= sw_high
    else:
        breakout = float(last["Close"]) < sw_low and float(prev["Close"]) >= sw_low
    if not breakout:
        return None, {"breakout": False}, 0

    score, checks = 1, {"breakout": True}

    # 2. Discount/premium
    hi, lo, mid = dealing_range(df_h1, 100)
    if direction == "bull" and float(last["Close"]) < mid:
        score += 2; checks["discount_premium"] = True
    elif direction == "bear" and float(last["Close"]) > mid:
        score += 2; checks["discount_premium"] = True
    else:
        checks["discount_premium"] = False

    # 3. RSI searah
    ok_rsi = t["rsi_buy_min"] <= rsi_v <= t["rsi_buy_max"] if direction == "bull" \
        else t["rsi_sell_min"] <= rsi_v <= t["rsi_sell_max"]
    if ok_rsi:
        score += 2
    checks["rsi"] = ok_rsi

    # 4. Volume (skip item jika data volume tidak tersedia)
    has_vol = df_m15["Volume"].sum() > 0
    checks["volume_available"] = bool(has_vol)
    if has_vol:
        vol_avg = float(df_m15["Volume"].iloc[-(t["vol_avg_period"] + 1):-1].mean())
        ok_vol = float(last["Volume"]) > t["vol_breakout_mult"] * vol_avg
        if ok_vol:
            score += 1
        checks["volume"] = ok_vol

    # 5. Breakout di awal sesi London/NY (14:00-16:00 atau 19:30-21:30 WIB)
    hour = last.name.hour + 7  # UTC -> WIB
    hour = hour % 24
    ok_session = (14 <= hour <= 16) or (19 <= hour <= 21)
    if ok_session:
        score += 1
    checks["session_open"] = ok_session

    # 6. Retest (candle sebelum breakout dekat level)
    checks["retest"] = False  # diisi ulang bila perlu; sederhana: candle sebelum dekat level

    max_score = 7 if has_vol else 6
    entry = float(last["Close"])
    if direction == "bull":
        sl = sw_low - t["sl_atr_buffer"] * atr
    else:
        sl = sw_high + t["sl_atr_buffer"] * atr
    risk = abs(entry - sl)
    signal = {
        "strategy": "TREND",
        "direction": "Buy" if direction == "bull" else "Sell",
        "entry": entry,
        "sl": sl,
        "tp1": entry + risk * t["tp1_r"] if direction == "bull" else entry - risk * t["tp1_r"],
        "tp2": entry + risk * t["tp2_r"] if direction == "bull" else entry - risk * t["tp2_r"],
        "risk": risk,
        "atr": atr,
        "score": score,
        "max_score": max_score,
        "checks": checks,
        "bar_time": last.name,
    }
    return signal, checks, score


def bias_h1(df_h1, t):
    from indicators import ema, structure_direction
    c = df_h1["Close"]
    e50, e200 = ema(c, t["ema_fast"]), ema(c, t["ema_slow"])
    slope = (e20 := ema(c, t["ema_slope_ref"])).iloc[-1] - e20.iloc[-4]
    atr_h1 = (df_h1["High"] - df_h1["Low"]).rolling(14).mean().iloc[-1]
    struct = structure_direction(df_h1, 60)
    if e50.iloc[-1] > e200.iloc[-1] and float(c.iloc[-1]) > e50.iloc[-1] \
            and slope > 0.05 * atr_h1 and struct == "bull":
        return {"direction": "bull", "structure": struct, "slope": float(slope)}
    if e50.iloc[-1] < e200.iloc[-1] and float(c.iloc[-1]) < e50.iloc[-1] \
            and slope < -0.05 * atr_h1 and struct == "bear":
        return {"direction": "bear", "structure": struct, "slope": float(slope)}
    return {"direction": "range", "structure": struct, "slope": float(slope)}


def build_smc(df_m15, smc_ctx, cfg, ind):
    """Bangun sinyal SMC dari zona fresh. Return (signal|None, info)."""
    s = cfg["smc"]
    atr = float(ind["atr"].iloc[-1])
    last = df_m15.iloc[-1]
    bias_dir = smc_ctx.get("bias_direction")  # dari main

    if not smc_ctx["fresh_obs"] and not smc_ctx["fresh_fvgs"]:
        return None, {"reason": "tidak ada zona fresh"}

    # pilih zona terdekat dari harga
    zones = [{"kind": "ob", **z} for z in smc_ctx["fresh_obs"]] + \
            [{"kind": "fvg", **z} for z in smc_ctx["fresh_fvgs"]]
    zones.sort(key=lambda z: abs((z["top"] + z["bottom"]) / 2 - float(last["Close"])))
    zone = zones[0]
    direction = zone["type"]  # bull -> Buy dari zona

    # counter-trend hanya jika sweep + CHoCH searah zona
    counter = (bias_dir is not None and
               ((bias_dir == "bull" and direction == "bear") or
                (bias_dir == "bear" and direction == "bull")))
    if counter:
        has_sweep = any(sw["dir"] == direction for sw in smc_ctx["sweeps"])
        has_choch = smc_ctx["choch"] == direction
        if not (has_sweep and has_choch):
            return None, {"reason": "counter-trend tanpa sweep+CHoCH -> ditolak kode"}

    # entry = batas zona terdekat ke harga; hanya jika harga dekat zona (belum lari jauh)
    entry = zone["bottom"] if direction == "bull" else zone["top"]
    dist = abs(float(last["Close"]) - entry)
    if dist > 2.0 * atr:
        return None, {"reason": f"harga terlalu jauh dari zona ({dist:.1f} > 2 ATR)"}

    if direction == "bull":
        sl = zone["bottom"] - s["sl_atr_buffer"] * atr
    else:
        sl = zone["top"] + s["sl_atr_buffer"] * atr
    risk = abs(entry - sl)

    # TP dari liquidity pool terdekat
    pools = [lv["price"] for lv in smc_ctx["liquidity"]]
    if direction == "bull":
        ahead = sorted([p for p in pools if p > entry + s["tp1_min_r"] * risk])
    else:
        ahead = sorted([p for p in pools if p < entry - s["tp1_min_r"] * risk], reverse=True)
    if not ahead:
        return None, {"reason": "tidak ada liquidity pool >= 1.5R -> skip"}
    tp1 = ahead[0]
    tp2 = ahead[1] if len(ahead) > 1 and abs(ahead[1] - entry) >= 3 * risk else (
        entry + 3 * risk if direction == "bull" else entry - 3 * risk)

    signal = {
        "strategy": "SMC",
        "direction": "Buy" if direction == "bull" else "Sell",
        "entry": entry,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "risk": risk,
        "atr": atr,
        "zone": {"kind": zone["kind"], "top": zone["top"], "bottom": zone["bottom"],
                 "fresh": True},
        "counter_trend": counter,
        "sweep": [sw["level"] for sw in smc_ctx["sweeps"] if sw["dir"] == direction],
        "bar_time": last.name,
    }
    return signal, {"reason": "ok"}
