"""Tes pipeline penuh: data -> chart -> AI vision -> Telegram."""
import os, sys, json
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))
import yaml
from main import load_secrets, ROOT
import data_fetcher, smc as smc_mod, chart_renderer, ai_analyst, telegram_bot as tg
from indicators import add_indicators, atr

with open(os.path.join(ROOT, "config.yaml"), encoding="utf-8") as f:
    cfg = yaml.safe_load(f)
secrets = load_secrets()

df_m15, _ = data_fetcher.fetch(cfg["symbol"], cfg["entry_tf"], cfg["lookback_entry"], secrets["TWELVEDATA_KEY"])
df_h1, _ = data_fetcher.fetch(cfg["symbol"], cfg["bias_tf"], cfg["lookback_bias"], secrets["TWELVEDATA_KEY"])
df_m15 = add_indicators(df_m15, cfg["trend"], cfg["smc"])
atr_now = float(df_m15["atr"].iloc[-1])
ctx = smc_mod.analyze(df_m15, cfg["smc"], atr_now)
zones = [{"top": z["top"], "bottom": z["bottom"], "type": z["type"], "fresh": True, "kind": z.get("kind", "ob")}
         for z in ctx["fresh_obs"] + ctx["fresh_fvgs"]]
chart_m15 = chart_renderer.render_chart(df_m15, zones=zones, levels=ctx["liquidity"], title="XAUUSD M15 (TES)")
chart_h1 = chart_renderer.render_chart(df_h1, title="XAUUSD H1 (TES)")
with open("test_m15.png", "wb") as f:
    f.write(chart_m15)

payload = {"price": float(df_m15["Close"].iloc[-1]), "atr_m15": round(atr_now, 2),
           "bias": "TEST PIPELINE", "trend": {"signal": False}, "smc": {"signal": False,
           "bos": ctx["bos"], "choch": ctx["choch"], "sweeps": ctx["sweeps"],
           "fresh_zones": zones}}
ai = ai_analyst.validate(secrets, cfg, payload, chart_m15, chart_h1)
print("AI response:", json.dumps(ai, indent=1))

fake = {"strategy": "SMC", "direction": "Buy", "entry": float(df_m15["Close"].iloc[-1]),
        "sl": float(df_m15["Close"].iloc[-1]) - atr_now, "tp1": float(df_m15["Close"].iloc[-1]) + atr_now,
        "tp2": float(df_m15["Close"].iloc[-1]) + 2.5 * atr_now, "risk": atr_now, "atr": atr_now,
        "score": 6, "max_score": 7, "reasoning": "[TES PIPELINE] " + ai["smc"]["reasoning"]}
tg.send_photo(secrets["TELEGRAM_BOT_TOKEN"], secrets["TELEGRAM_CHAT_ID"], chart_m15,
              tg.format_signal(fake, cfg["telegram"]))
print("Telegram terkirim. Cek HP lo.")
