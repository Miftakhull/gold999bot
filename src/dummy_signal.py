"""Kirim SATU sinyal dummy (tes pipeline, TIDAK dicatat ke CSV/winrate).
Dipakai untuk tes via Modal atau GitHub Actions (workflow_dispatch input dummy_test).
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))

import ai_analyst
import chart_renderer
import data_fetcher
import telegram_bot as tg
from indicators import atr

from main import load_secrets, ROOT


def run():
    import yaml
    with open(os.path.join(ROOT, "config.yaml"), encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    secrets = load_secrets()

    df_m5, _ = data_fetcher.fetch(cfg["symbol"], cfg["scalp_tf"], cfg["lookback_scalp"],
                                  secrets.get("TWELVEDATA_KEY", ""))
    atr_now = float(atr(df_m5, 14).iloc[-1])
    zones = [{"top": float(df_m5["Low"].iloc[-30:].min()) + atr_now,
              "bottom": float(df_m5["Low"].iloc[-30:].min()),
              "type": "bull", "fresh": True, "kind": "sd"}]
    chart = chart_renderer.render_chart(df_m5, zones=zones, title="XAUUSD M5 (DUMMY TEST)")

    entry = float(df_m5["Close"].iloc[-1])
    payload = {"price": entry, "atr_m5": round(atr_now, 2), "bias_h1": "DUMMY TEST",
               "trend": {"signal": False}, "smc": {"signal": False},
               "scalp": {"signal": True, "score": "5/6", "checks": {"zone_fresh": True, "pa": "pin bar",
                        "strong_impulse": True, "htf_confluence": True},
                         "zone": zones[0] and {"top": zones[0]["top"], "bottom": zones[0]["bottom"]},
                         "levels": {"entry": entry, "sl": entry - atr_now,
                                    "tp1": entry + atr_now, "tp2": entry + 1.8 * atr_now}}}

    ai = None
    for attempt in range(1, 6):
        try:
            ai = ai_analyst.validate(secrets, cfg, payload, {"M5 (DUMMY)": chart})
            break
        except Exception as e:
            print(f"AI attempt {attempt}: {e}")
    if ai is None:
        print("GAGAL: AI tidak bisa dihubungi setelah 5 percobaan.")
        return
    print("AI verdict:", json.dumps(ai.get("scalp"), indent=1))

    dummy = {"strategy": "SCALP", "direction": "Buy", "entry": entry,
             "sl": entry - atr_now, "tp1": entry + atr_now, "tp2": entry + 1.8 * atr_now,
             "risk": atr_now, "atr": atr_now, "score": 5, "max_score": 6,
             "hold": False,
             "reasoning": "[TES DUMMY - BUKAN SINYAL VALID] " + ai["scalp"]["reasoning"]}
    tg.send_photo(secrets["TELEGRAM_BOT_TOKEN"], secrets["TELEGRAM_CHAT_ID"], chart,
                  tg.format_signal(dummy, cfg["telegram"]))
    print("DUMMY TERKIRIM ke Telegram.")


if __name__ == "__main__":
    run()
