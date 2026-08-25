"""Deteksi zona Supply & Demand M5: pola base-leg (impuls), freshness."""
import pandas as pd


def find_sd_zones(df, atr_now, cfg_s):
    """
    Deteksi zona S/D dari pola base (kompresi) -> impuls.
    Return list zona fresh: {type, top, bottom, time, strength}
    """
    zones = []
    n = len(df)
    start = max(1, n - cfg_s["zone_max_age"])
    for i in range(start, n - 2):
        for base_len in range(1, cfg_s["sd_base_max_candles"] + 1):
            b_start = i - base_len + 1
            if b_start < 1:
                continue
            base = df.iloc[b_start:i + 1]
            base_range = float(base["High"].max() - base["Low"].min())
            if base_range > cfg_s["sd_base_max_range_atr"] * atr_now:
                continue
            imp = df.iloc[i + 1:i + 6]
            if len(imp) < 2:
                continue
            top, bot = float(base["High"].max()), float(base["Low"].min())
            move_up = float(imp["High"].max()) - top
            move_dn = bot - float(imp["Low"].min())
            if move_up >= cfg_s["sd_impulse_atr"] * atr_now:
                zones.append({"type": "bull", "top": top, "bottom": bot,
                              "time": df.index[i], "strength": move_up / atr_now})
            if move_dn >= cfg_s["sd_impulse_atr"] * atr_now:
                zones.append({"type": "bear", "top": top, "bottom": bot,
                              "time": df.index[i], "strength": move_dn / atr_now})

    # dedupe: zona overlap sejenis -> simpan yang terkuat
    zones.sort(key=lambda z: z["time"], reverse=True)
    kept = []
    for z in zones:
        overlap = any(k["type"] == z["type"]
                      and z["bottom"] <= k["top"] and k["bottom"] <= z["top"]
                      for k in kept)
        if not overlap:
            kept.append(z)

    # freshness: belum dimitigasi (harga menembus seluruh zona)
    fresh = []
    for z in kept:
        after = df[df.index > z["time"]]
        if after.empty:
            continue
        if z["type"] == "bull":
            z["mitigated"] = float(after["Low"].min()) <= z["bottom"]
        else:
            z["mitigated"] = float(after["High"].max()) >= z["top"]
        if not z["mitigated"]:
            fresh.append(z)
    return fresh
