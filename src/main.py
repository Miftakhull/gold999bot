"""Orkestrator utama Gold AI Signal Bot."""
import os
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ai_analyst
import chart_renderer
import data_fetcher
import logger
import signal_builder
import smc
import stats
import telegram_bot as tg
import tracker
from indicators import add_indicators, atr, ema, swing_low

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_secrets():
    secrets = {}
    path = os.path.join(ROOT, "secret.txt")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    secrets[k.strip()] = v.strip()
    for k in ("TWELVEDATA_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID",
              "AI_API_KEY", "AI_BASE_URL", "AI_MODEL"):
        if k in os.environ:
            secrets[k] = os.environ[k]
    missing = [k for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "AI_API_KEY",
                           "AI_BASE_URL", "AI_MODEL") if not secrets.get(k)]
    if missing:
        raise SystemExit(f"Secret hilang: {missing}")
    return secrets


def main():
    with open(os.path.join(ROOT, "config.yaml"), encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    secrets = load_secrets()
    state = tracker.load_state()

    # ---------- 1. Data ----------
    df_m15, src1 = data_fetcher.fetch(cfg["symbol"], cfg["entry_tf"], cfg["lookback_entry"],
                                      secrets.get("TWELVEDATA_KEY", ""))
    df_h1, _ = data_fetcher.fetch(cfg["symbol"], cfg["bias_tf"], cfg["lookback_bias"],
                                  secrets.get("TWELVEDATA_KEY", ""))
    df_m15 = add_indicators(df_m15, cfg["trend"], cfg["smc"])
    last_closed = df_m15.index[-1]

    # ---------- 2. Skip jika belum ada candle M15 baru ----------
    if state.get("last_bar") == str(last_closed):
        print(f"Tidak ada candle baru ({last_closed}). Selesai.")
        _post_actions(state, secrets, cfg, df_m15)
        return

    atr_now = float(df_m15["atr"].iloc[-1])
    last_price = float(df_m15["Close"].iloc[-1])

    # ---------- 3. Guard Layer 0 ----------
    g = cfg["guards"]
    guard_block = None
    if not (g["atr_min"] <= atr_now <= g["atr_max"]):
        guard_block = f"ATR {atr_now:.2f} di luar range"
    elif abs(float(df_m15["High"].iloc[-1]) - float(df_m15["Low"].iloc[-1])) > g["spike_atr_mult"] * atr_now:
        guard_block = "news spike"
    if guard_block:
        print(f"Guard: {guard_block}. Skip scan baru.")
        state["last_bar"] = str(last_closed)
        tracker.save_state(state)
        _post_actions(state, secrets, cfg, df_m15)
        return

    # ---------- 4. Tracker sinyal aktif ----------
    for s in state["active"]:
        if s["trail_method"] == "ema20":
            s["trail_value"] = float(df_m15["ema20"].iloc[-1])
        else:
            s["trail_value"] = float(swing_low(df_m15, cfg["runner"]["trail_swing_period"])) \
                if s["direction"] == "Buy" else float(df_m15["High"].iloc[-cfg["runner"]["trail_swing_period"]:].max())
        if s.get("bar_time") != str(last_closed) and s["status"] == "ACTIVE":
            s["bars_elapsed"] = s.get("bars_elapsed", 0) + 1
    tracker.check_active(state, last_price, cfg, tg, secrets)
    state["last_bar"] = str(last_closed)
    tracker.save_state(state)

    # ---------- 5. Hitung setup ----------
    bias = signal_builder.bias_h1(df_h1, cfg["trend"])
    trend_sig, trend_checks, trend_score = signal_builder.build_trend(df_m15, df_h1, cfg, df_m15)
    smc_ctx = smc.analyze(df_m15, cfg["smc"], atr_now)
    smc_ctx["bias_direction"] = bias["direction"]
    smc_sig, smc_info = signal_builder.build_smc(df_m15, smc_ctx, cfg, df_m15)

    print(f"bias={bias['direction']} trend_score={trend_score} trend_sig={bool(trend_sig)} "
          f"smc_sig={bool(smc_sig)} freshOB={len(smc_ctx['fresh_obs'])} sweeps={smc_ctx['sweeps']}")

    # ---------- 6. Gate sebelum AI (hemat biaya) ----------
    cooldown = cfg["guards"]["cooldown_hours"] * 3600
    now = datetime.now(timezone.utc)
    gate_trend = trend_sig is not None and trend_score >= cfg["trend"]["min_score"]
    gate_smc = smc_sig is not None
    if gate_trend:
        last_t = logger.last_signal_time("TREND",
                                         trend_sig["direction"])
        if last_t and (now - last_t).total_seconds() < cooldown:
            gate_trend = False
    if gate_smc:
        last_s = logger.last_signal_time("SMC", smc_sig["direction"])
        if last_s and (now - last_s).total_seconds() < cooldown:
            gate_smc = False
    if logger.signals_today() >= g["max_signals_per_day"] and (gate_trend or gate_smc):
        print("Kuota sinyal harian habis.")
        gate_trend = gate_smc = False

    if not gate_trend and not gate_smc:
        # ---------- MONITOR anti-miss ----------
        m = cfg["monitor"]
        if m["enabled"] and trend_sig is not None and trend_score >= m["near_miss_score"] \
                and logger.monitors_today() < m["max_per_day"]:
            tg.send_message(secrets["TELEGRAM_BOT_TOKEN"], secrets["TELEGRAM_CHAT_ID"],
                            f"👀 <b>MONITOR</b> — XAUUSD setup TREND hampir valid "
                            f"(skor {trend_score}/{trend_sig['max_score']}). Pantau manual. "
                            f"Checks: {trend_checks}")
            logger.append_signal({"strategy": "MONITOR", **trend_sig}, "-", 0, "monitor")
        tracker.save_state(state)
        _post_actions(state, secrets, cfg, df_m15)
        return

    # ---------- 7. Render chart + validasi AI ----------
    zones_m15 = [{"top": z["top"], "bottom": z["bottom"], "type": z["type"],
                  "fresh": True, "kind": z.get("kind", "ob")}
                 for z in smc_ctx["fresh_obs"] + smc_ctx["fresh_fvgs"]]
    chart_m15 = chart_renderer.render_chart(
        df_m15, zones=zones_m15, levels=smc_ctx["liquidity"], title="XAUUSD M15")
    chart_h1 = chart_renderer.render_chart(df_h1, title="XAUUSD H1 (bias)")

    payload = {
        "price": last_price, "atr_m15": round(atr_now, 2),
        "bias_h1": bias,
        "trend": {"signal": bool(trend_sig), "score": f"{trend_score}/{trend_sig['max_score'] if trend_sig else '-'}",
                  "checks": trend_checks,
                  "levels": {"entry": trend_sig["entry"], "sl": trend_sig["sl"],
                             "tp1": trend_sig["tp1"], "tp2": trend_sig["tp2"]} if trend_sig else None},
        "smc": {"signal": bool(smc_sig), "bos": smc_ctx["bos"], "choch": smc_ctx["choch"],
                "fresh_zones": [{"kind": z.get("kind"), "type": z["type"],
                                 "range": [z["bottom"], z["top"]]}
                                for z in zones_m15],
                "sweeps": smc_ctx["sweeps"], "liquidity": smc_ctx["liquidity"],
                "counter_trend": smc_sig.get("counter_trend") if smc_sig else False,
                "levels": {k: smc_sig[k] for k in ("entry", "sl", "tp1", "tp2")} if smc_sig else None},
    }
    ai = ai_analyst.validate(secrets, cfg, payload, chart_m15, chart_h1)
    print("AI:", ai)

    # ---------- 8. Gate AI ----------
    gc = cfg["gate"]
    ok_trend = gate_trend and ai["trend"]["verdict"] == "perfect" \
        and ai["trend"]["confidence"] >= gc["perfect_confidence"]
    ok_smc = gate_smc and ai["smc"]["verdict"] == "perfect" \
        and ai["smc"]["confidence"] >= gc["perfect_confidence"]

    # OCO: bertentangan arah -> tidak ada yang dikirim
    if ok_trend and ok_smc and trend_sig["direction"] != smc_sig["direction"]:
        print("OCO: dua jalur bertentangan, tidak kirim.")
        ok_trend = ok_smc = False

    confluence = ok_trend and ok_smc

    def _send(sig, verdict, conf, is_conf=False):
        reasoning = ai[sig["strategy"].lower()].get("reasoning", "")
        sig["reasoning"] = reasoning
        sig["hold"] = cfg["trend"]["hold_after_tp2"] if sig["strategy"] == "TREND" \
            else cfg["smc"]["hold_after_tp2"]
        caption = tg.format_signal(sig, cfg["telegram"], confluence=is_conf)
        tg.send_photo(secrets["TELEGRAM_BOT_TOKEN"], secrets["TELEGRAM_CHAT_ID"],
                      chart_m15, caption)
        logger.append_signal(sig, verdict, conf, reasoning)
        tracker.add_signal(state, sig, sig["hold"],
                           cfg["trend"]["runner_trail"] if sig["strategy"] == "TREND"
                           else "ema20")

    if ok_trend:
        _send(trend_sig, ai["trend"]["verdict"], ai["trend"]["confidence"], is_conf=confluence)
    if ok_smc and not (confluence and ok_trend):
        _send(smc_sig, ai["smc"]["verdict"], ai["smc"]["confidence"])
    if confluence:
        pass  # trend sudah terkirim sebagai CONFLUENCE

    tracker.save_state(state)
    _post_actions(state, secrets, cfg, df_m15)


def _post_actions(state, secrets, cfg, df_m15):
    """Polling /stats + rekap mingguan."""
    tz = ZoneInfo(cfg["telegram"]["timezone"])
    now_wib = datetime.now(tz)

    def stats_fn():
        return stats.stats_text(30)

    state["tg_offset"] = tg.poll_commands(
        secrets["TELEGRAM_BOT_TOKEN"], secrets["TELEGRAM_CHAT_ID"],
        state.get("tg_offset", 0), stats_fn)
    if now_wib.weekday() == 0 and now_wib.hour == cfg["telegram"]["weekly_recap_hour"]:
        week = now_wib.strftime("%G-W%V")
        if state.get("weekly_sent") != week:
            tg.send_message(secrets["TELEGRAM_BOT_TOKEN"], secrets["TELEGRAM_CHAT_ID"],
                            "🗓 <b>REKAP MINGGUAN</b>\n" + stats.stats_text(7))
            state["weekly_sent"] = week
    tracker.save_state(state)


if __name__ == "__main__":
    main()
