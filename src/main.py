"""Orkestrator utama Gold AI Signal Bot — 3 strategi independen (TREND, SMC, SCALP)."""
import csv
import os
import subprocess
import sys
import time
import urllib.request
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
import supply_demand
import telegram_bot as tg
import tracker
from indicators import add_indicators, atr, ema, swing_low

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_RAW = "https://raw.githubusercontent.com/Miftakhull/gold999bot/main/signals_log.csv"


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


def _already_sent_remote(strategy, direction, cooldown_hours):
    """Cek via repo GitHub: apakah sinyal serupa baru dikirim mesin lain (anti-dobel)."""
    try:
        url = f"{REPO_RAW}?t={int(time.time())}"
        with urllib.request.urlopen(url, timeout=10) as r:
            rows = list(csv.reader(r.read().decode().splitlines()))
        now = datetime.now(timezone.utc)
        for row in rows[1:]:
            if (len(row) > 11 and row[1] == strategy and row[2] == direction
                    and row[10] in ("ACTIVE", "TP1", "RUNNING", "WIN", "RUNNER-WIN", "LOSS", "BE")):
                t = datetime.fromisoformat(row[0])
                if (now - t).total_seconds() < cooldown_hours * 3600:
                    return True
    except Exception as e:
        print(f"Cek remote skip: {e}")
    return False


def _push_log():
    """Push log sinyal ke GitHub supaya mesin lain tahu (best-effort)."""
    try:
        subprocess.run(["git", "add", "signals_log.csv"], cwd=ROOT, capture_output=True, timeout=30)
        subprocess.run(["git", "commit", "-m", "signal log"], cwd=ROOT, capture_output=True, timeout=30)
        subprocess.run(["git", "pull", "--rebase", "-q", "origin", "main"],
                       cwd=ROOT, capture_output=True, timeout=60)
        subprocess.run(["git", "push", "-q", "origin", "main"],
                       cwd=ROOT, capture_output=True, timeout=60)
    except Exception as e:
        print(f"Push log skip: {e}")


def _cooldown_ok(strategy, direction, cooldown_seconds, remote_hours, cfg, now):
    if logger.last_signal_time(strategy, direction) is not None:
        last = logger.last_signal_time(strategy, direction)
        if (now - last).total_seconds() < cooldown_seconds:
            return False
    if _already_sent_remote(strategy, direction, remote_hours):
        print(f"Anti-dobel: mesin lain sudah kirim {strategy} {direction}.")
        return False
    return True


def main():
    with open(os.path.join(ROOT, "config.yaml"), encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    secrets = load_secrets()
    state = tracker.load_state()
    td_key = secrets.get("TWELVEDATA_KEY", "")
    now = datetime.now(timezone.utc)

    # ---------- 1. Selalu fetch M5 (untuk scalp) ----------
    df_m5, _ = data_fetcher.fetch(cfg["symbol"], cfg["scalp_tf"], cfg["lookback_scalp"], td_key)
    atr_m5 = float(atr(df_m5, 14).iloc[-1])
    last_price = float(df_m5["Close"].iloc[-1])

    # apakah ada candle M15 baru? (infer dari M5, floor ke 15 menit)
    last_m5_closed = df_m5.index[-1]
    last_m15_closed = last_m5_closed.floor("15min")
    new_m15 = state.get("last_bar") != str(last_m15_closed)

    # ---------- 2. Tracker sinyal aktif (setiap scan) ----------
    trend_sig, smc_sig, smc_ctx, bias = None, None, None, None
    df_m15 = df_h1 = None
    for s in state["active"]:
        if s["status"] == "ACTIVE":
            if s["strategy"] == "SCALP":
                s["bars_elapsed"] = s.get("bars_elapsed", 0) + 1
            elif new_m15 and s.get("bar_time") != str(last_m15_closed):
                s["bars_elapsed"] = s.get("bars_elapsed", 0) + 1
    # update trailing utk sinyal RUNNING (butuh df_m15)
    if df_m15 is not None:
        for s in state["active"]:
            if s["strategy"] == "SCALP" or s["status"] != "RUNNING":
                continue
            if s.get("trail_method") == "swing":
                s["trail_value"] = float(swing_low(df_m15, cfg["runner"]["trail_swing_period"])) \
                    if s["direction"] == "Buy" \
                    else float(df_m15["High"].iloc[-cfg["runner"]["trail_swing_period"]:].max())
            else:
                s["trail_value"] = float(df_m15["ema20"].iloc[-1])
    tracker.check_active(state, last_price, cfg, tg, secrets)

    # ---------- 3. Jalur TREND & SMC (hanya saat candle M15 baru) ----------
    if new_m15:
        df_m15, _ = data_fetcher.fetch(cfg["symbol"], cfg["entry_tf"], cfg["lookback_entry"], td_key)
        df_h1, _ = data_fetcher.fetch(cfg["symbol"], cfg["bias_tf"], cfg["lookback_bias"], td_key)
        df_m15 = add_indicators(df_m15, cfg["trend"], cfg["smc"])
        atr15 = float(df_m15["atr"].iloc[-1])

        # guard layer 0 (utk TREND/SMC)
        g = cfg["guards"]
        guard_block = None
        if not (g["atr_min"] <= atr15 <= g["atr_max"]):
            guard_block = f"ATR15 {atr15:.2f} di luar range"
        elif abs(float(df_m15["High"].iloc[-1]) - float(df_m15["Low"].iloc[-1])) > g["spike_atr_mult"] * atr15:
            guard_block = "news spike"

        if guard_block:
            print(f"Guard: {guard_block}. TREND/SMC skip.")
        else:
            bias = signal_builder.bias_h1(df_h1, cfg["trend"])
            trend_sig, trend_checks, trend_score = signal_builder.build_trend(
                df_m15, df_h1, cfg, df_m15)
            smc_ctx = smc.analyze(df_m15, cfg["smc"], atr15)
            smc_ctx["bias_direction"] = bias["direction"]
            smc_sig, smc_info = signal_builder.build_smc(df_m15, smc_ctx, cfg, df_m15)
            print(f"bias={bias['direction']} trend_score={trend_score} "
                  f"trend_sig={bool(trend_sig)} smc_sig={bool(smc_sig)} "
                  f"freshOB={len(smc_ctx['fresh_obs'])} sweeps={smc_ctx['sweeps']}")

        state["last_bar"] = str(last_m15_closed)

    # cache bias & level H1 utk scalp (dihitung ulang tiap candle M15 baru)
    cache = state.get("bias_cache") or {}
    if new_m15 and df_m15 is not None and df_h1 is not None:
        cache = {
            "m15_bar": str(last_m15_closed),
            "bias": signal_builder.bias_h1(df_h1, cfg["trend"]),
            "bias_m15": signal_builder.bias_m15(df_m15, cfg["scalp"]),
            "h1_levels": smc.find_liquidity_levels(df_h1),
        }
        state["bias_cache"] = cache
    bias = bias or cache.get("bias", {"direction": "range"})
    h1_levels = cache.get("h1_levels", [])
    scalp_bias_m15 = bias["direction"]

    # ---------- 4. Jalur SCALP (setiap scan, M5) ----------
    scalp_sig, scalp_info, zones_m5 = None, {"reason": "-"}, []
    if cache.get("m15_bar"):
        zones_m5 = supply_demand.find_sd_zones(df_m5, atr_m5, cfg["scalp"])
        bias_m15_dir = cache.get("bias_m15", "range")
        scalp_sig, scalp_info = signal_builder.build_scalp(
            df_m5, zones_m5, bias_m15_dir, h1_levels, cfg, atr_m5)
        print(f"scalp: {scalp_info} bias_m15={bias_m15_dir} zones={len(zones_m5)}")
    else:
        print("Scan pertama: build cache bias, scalp skip.")

    # ---------- 5. Gate pra-AI (per strategi, independen) ----------
    g = cfg["guards"]
    cooldown_s = g["cooldown_hours"] * 3600
    gate_trend = trend_sig is not None
    gate_smc = smc_sig is not None
    gate_scalp = scalp_sig is not None
    if gate_trend:
        gate_trend = _cooldown_ok("TREND", trend_sig["direction"], cooldown_s,
                                  g["cooldown_hours"], cfg, now) \
            and logger.signals_today("TREND") < g["max_signals_per_day"]
    if gate_smc:
        gate_smc = _cooldown_ok("SMC", smc_sig["direction"], cooldown_s,
                                g["cooldown_hours"], cfg, now) \
            and logger.signals_today("SMC") < g["max_signals_per_day"]
    if gate_scalp:
        sc = cfg["scalp"]
        gate_scalp = _cooldown_ok("SCALP", scalp_sig["direction"],
                                  sc["cooldown_minutes"] * 60,
                                  sc["cooldown_minutes"] / 60.0, cfg, now) \
            and logger.signals_today("SCALP") < sc["max_per_day"]

    candidates = [s for s, ok in (("TREND", gate_trend), ("SMC", gate_smc), ("SCALP", gate_scalp)) if ok]
    if not candidates:
        print("Tidak ada kandidat sinyal scan ini.")
        tracker.save_state(state)
        _post_actions(state, secrets, cfg)
        return

    # ---------- 6. Render chart + validasi AI (1 panggilan, semua kandidat) ----------
    charts = {}
    if gate_trend or gate_smc:
        zones_m15 = [{"top": z["top"], "bottom": z["bottom"], "type": z["type"],
                      "fresh": True, "kind": z.get("kind", "ob")}
                     for z in (smc_ctx["fresh_obs"] + smc_ctx["fresh_fvgs"] if smc_ctx else [])]
        charts["M15"] = chart_renderer.render_chart(
            df_m15, zones=zones_m15, levels=smc_ctx["liquidity"] if smc_ctx else None,
            title="XAUUSD M15")
        charts["H1"] = chart_renderer.render_chart(df_h1, title="XAUUSD H1 (bias)")
    if gate_scalp:
        zones_plot = [{"top": z["top"], "bottom": z["bottom"], "type": z["type"],
                       "fresh": True, "kind": "sd"} for z in zones_m5]
        charts["M5"] = chart_renderer.render_chart(
            df_m5, zones=zones_plot, levels=h1_levels, title="XAUUSD M5 (scalp S/D)")

    payload = {
        "price": last_price, "atr_m5": round(atr_m5, 2),
        "bias_h1": cache.get("bias"),
        "trend": {
            "signal": bool(trend_sig),
            "checks": trend_checks if trend_sig else {},
            "score": f"{trend_sig['score']}/{trend_sig['max_score']}" if trend_sig else None,
            "levels": {k: trend_sig[k] for k in ("entry", "sl", "tp1", "tp2")} if trend_sig else None,
        },
        "smc": {
            "signal": bool(smc_sig),
            "bos": smc_ctx["bos"] if smc_ctx else None,
            "choch": smc_ctx["choch"] if smc_ctx else None,
            "fresh_zones": [{"kind": z.get("kind"), "type": z["type"],
                             "range": [z["bottom"], z["top"]]} for z in zones_m15] if gate_trend or gate_smc else [],
            "sweeps": smc_ctx["sweeps"] if smc_ctx else [],
            "counter_trend": smc_sig.get("counter_trend") if smc_sig else False,
            "levels": {k: smc_sig[k] for k in ("entry", "sl", "tp1", "tp2")} if smc_sig else None,
        },
        "scalp": {
            "signal": bool(scalp_sig),
            "info": scalp_info,
            "score": f"{scalp_sig['score']}/{scalp_sig['max_score']}" if scalp_sig else None,
            "checks": scalp_sig.get("checks") if scalp_sig else {},
            "zone": scalp_sig.get("zone") if scalp_sig else None,
            "levels": {k: scalp_sig[k] for k in ("entry", "sl", "tp1", "tp2")} if scalp_sig else None,
        },
    }

    ai = None
    for attempt in (1, 2):
        try:
            ai = ai_analyst.validate(secrets, cfg, payload, charts)
            break
        except Exception as e:
            print(f"AI attempt {attempt} gagal: {e}")
    if ai is None:
        print("AI tidak bisa dihubungi — sinyal siklus ini dilewati (tidak crash).")
        tracker.save_state(state)
        _post_actions(state, secrets, cfg)
        return
    print("AI:", ai)

    # ---------- 7. Gate AI + kirim (masing-masing independen) ----------
    def _send(sig, verdict, conf, chart_png):
        reasoning = ai[sig["strategy"].lower()].get("reasoning", "")
        sig["reasoning"] = reasoning
        sig["hold"] = cfg["trend"]["hold_after_tp2"] if sig["strategy"] == "TREND" \
            else (cfg["smc"]["hold_after_tp2"] if sig["strategy"] == "SMC" else False)
        caption = tg.format_signal(sig, cfg["telegram"])
        tg.send_photo(secrets["TELEGRAM_BOT_TOKEN"], secrets["TELEGRAM_CHAT_ID"],
                      chart_png, caption)
        logger.append_signal(sig, verdict, conf, reasoning)
        tracker.add_signal(state, sig, sig["hold"],
                           cfg["trend"]["runner_trail"] if sig["strategy"] == "TREND"
                           else "ema20",
                           expiry=cfg["scalp"]["expiry_candles"] if sig["strategy"] == "SCALP" else None)
        _push_log()

    gc = cfg["gate"]
    if gate_trend and ai["trend"]["verdict"] == "perfect" \
            and ai["trend"]["confidence"] >= gc["perfect_confidence"]:
        _send(trend_sig, ai["trend"]["verdict"], ai["trend"]["confidence"], charts["M15"])
    else:
        print(f"TREND tidak lolos AI: {ai['trend']}")
    if gate_smc and ai["smc"]["verdict"] == "perfect" \
            and ai["smc"]["confidence"] >= gc["perfect_confidence"]:
        _send(smc_sig, ai["smc"]["verdict"], ai["smc"]["confidence"], charts["M15"])
    else:
        print(f"SMC tidak lolos AI: {ai['smc']}")
    if gate_scalp and ai["scalp"]["verdict"] == "perfect" \
            and ai["scalp"]["confidence"] >= cfg["scalp"]["confidence"]:
        _send(scalp_sig, ai["scalp"]["verdict"], ai["scalp"]["confidence"], charts["M5"])
    else:
        print(f"SCALP tidak lolos AI: {ai['scalp']}")

    tracker.save_state(state)
    _post_actions(state, secrets, cfg)


def _post_actions(state, secrets, cfg):
    """Polling /stats + rekap mingguan."""
    tz = ZoneInfo(cfg["telegram"]["timezone"])
    now_wib = datetime.now(tz)

    state["tg_offset"] = tg.poll_commands(
        secrets["TELEGRAM_BOT_TOKEN"], secrets["TELEGRAM_CHAT_ID"],
        state.get("tg_offset", 0), lambda: stats.stats_text(30))
    if now_wib.weekday() == 0 and now_wib.hour == cfg["telegram"]["weekly_recap_hour"]:
        week = now_wib.strftime("%G-W%V")
        if state.get("weekly_sent") != week:
            tg.send_message(secrets["TELEGRAM_BOT_TOKEN"], secrets["TELEGRAM_CHAT_ID"],
                            "🗓 <b>REKAP MINGGUAN</b>\n" + stats.stats_text(7))
            state["weekly_sent"] = week
    tracker.save_state(state)


if __name__ == "__main__":
    main()
