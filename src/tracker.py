"""Tracker sinyal aktif: cek TP1/TP2/SL/runner/void terhadap harga live."""
import json
import os

import logger

DATA_DIR = os.environ.get("BOT_DATA_DIR", ".")
STATE_PATH = os.path.join(DATA_DIR, "active_signals.json")


def load_state():
    if os.path.exists(STATE_PATH):
        with open(STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {"active": [], "tg_offset": 0, "last_bar": None, "weekly_sent": ""}


def save_state(state):
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=1, default=str)


def check_active(state, last_price, cfg, tg, secrets):
    """Cek semua sinyal aktif vs harga terkini. Kirim update Telegram. Mutasi state."""
    g = cfg["gate"]
    still_active = []
    for s in state["active"]:
        d = s["direction"]
        entry, sl, tp1, tp2 = s["entry"], s["sl"], s["tp1"], s["tp2"]
        risk = s["risk"]

        # VOID: entry tidak tersentuh dalam N candle
        expiry = s.get("expiry", g["signal_expiry_candles"])
        if s["status"] == "ACTIVE" and s.get("bars_elapsed", 0) >= expiry:
            _never_touched = (d == "Buy" and last_price < entry) or (d == "Sell" and last_price > entry)
            if _never_touched:
                tg.send_message(secrets["TELEGRAM_BOT_TOKEN"], secrets["TELEGRAM_CHAT_ID"],
                                f"⚠️ <b>SIGNAL VOID</b> — XAUUSD {d} @ {entry:.2f} tidak tercapai "
                                f"dalam {expiry} candle. Tidak dihitung menang/kalah.")
                logger.update_status(s, "VOID")
                continue

        if s["status"] == "ACTIVE":
            hit_sl = last_price <= sl if d == "Buy" else last_price >= sl
            hit_tp1 = last_price >= tp1 if d == "Buy" else last_price <= tp1
            if hit_sl:
                tg.send_message(secrets["TELEGRAM_BOT_TOKEN"], secrets["TELEGRAM_CHAT_ID"],
                                f"❌ <b>SL HIT — LOSS</b> XAUUSD {d} @ {entry:.2f} (-1R)")
                logger.update_status(s, "LOSS", -1.0)
                continue
            if hit_tp1:
                s["status"] = "TP1"
                s["sl"] = entry  # SL ke BE
                tg.send_message(secrets["TELEGRAM_BOT_TOKEN"], secrets["TELEGRAM_CHAT_ID"],
                                f"✅ <b>TP1 HIT</b> XAUUSD {d} @ {entry:.2f} — SL digeser ke BE ({entry:.2f})")
                logger.update_status(s, "TP1")
                still_active.append(s)
                continue

        elif s["status"] == "TP1":
            hit_be = last_price <= s["sl"] if d == "Buy" else last_price >= s["sl"]
            hit_tp2 = last_price >= tp2 if d == "Buy" else last_price <= tp2
            if hit_be:
                tg.send_message(secrets["TELEGRAM_BOT_TOKEN"], secrets["TELEGRAM_CHAT_ID"],
                                f"➖ <b>BREAK-EVEN</b> XAUUSD {d} @ {entry:.2f} (SL BE kena setelah TP1)")
                logger.update_status(s, "BE", 0.0)
                continue
            if hit_tp2:
                hold = s.get("hold", False)
                if hold:
                    s["status"] = "RUNNING"
                    s["runner_peak"] = last_price
                    tg.send_message(secrets["TELEGRAM_BOT_TOKEN"], secrets["TELEGRAM_CHAT_ID"],
                                    f"🏃 <b>TP2 HIT</b> XAUUSD {d} @ {entry:.2f} — jadi RUNNER, "
                                    f"SL trailing aktif (+{abs(tp2-entry)/risk:.1f}R terkunci)")
                    logger.update_status(s, "RUNNING", abs(tp2 - entry) / risk)
                else:
                    r = abs(tp2 - entry) / risk
                    tg.send_message(secrets["TELEGRAM_BOT_TOKEN"], secrets["TELEGRAM_CHAT_ID"],
                                    f"🏆 <b>TP2 HIT — WIN</b> XAUUSD {d} @ {entry:.2f} (+{r:.1f}R)")
                    logger.update_status(s, "WIN", abs(tp2 - entry) / risk)
                    continue
                still_active.append(s)
                continue

        elif s["status"] == "RUNNING":
            # trailing SL
            s["runner_peak"] = max(s.get("runner_peak", last_price), last_price) if d == "Buy" \
                else min(s.get("runner_peak", last_price), last_price)
            new_sl = s.get("trail_sl", entry)
            if s["trail_method"] == "swing":
                sw = s.get("trail_value")
                if sw:
                    new_sl = sw if d == "Buy" else sw
            else:  # ema20
                ema_v = s.get("trail_value")
                if ema_v:
                    new_sl = ema_v
            # SL hanya bergerak searah profit
            if d == "Buy" and new_sl > s["sl"]:
                s["sl"] = new_sl
            if d == "Sell" and (s["sl"] == entry or new_sl < s["sl"]):
                s["sl"] = new_sl
            hit_trail = last_price <= s["sl"] if d == "Buy" else last_price >= s["sl"]
            if hit_trail:
                r = abs(s["sl"] - entry) / risk
                tg.send_message(secrets["TELEGRAM_BOT_TOKEN"], secrets["TELEGRAM_CHAT_ID"],
                                f"🏃💰 <b>RUNNER CLOSE — WIN</b> XAUUSD {d} @ {entry:.2f} "
                                f"exit trailing {s['sl']:.2f} (+{r:.1f}R)")
                logger.update_status(s, "RUNNER-WIN", r)
                continue
            still_active.append(s)
            continue

        else:
            still_active.append(s)

    state["active"] = still_active


def add_signal(state, sig, hold, trail_method, expiry=None):
    entry = {
        "strategy": sig["strategy"],
        "direction": sig["direction"],
        "entry": sig["entry"],
        "sl": sig["sl"],
        "tp1": sig["tp1"],
        "tp2": sig["tp2"],
        "risk": sig["risk"],
        "status": "ACTIVE",
        "hold": hold,
        "trail_method": trail_method,
        "bars_elapsed": 0,
        "bar_time": str(sig["bar_time"]),
    }
    if expiry is not None:
        entry["expiry"] = expiry
    state["active"].append(entry)
