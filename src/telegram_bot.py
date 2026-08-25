"""Kirim pesan/foto ke Telegram + polling /stats."""
import io
import json
import time

import requests

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0"


def _api(token, method):
    return f"https://api.telegram.org/bot{token}/{method}"


def send_message(token, chat_id, text):
    r = requests.post(_api(token, "sendMessage"), json={
        "chat_id": chat_id, "text": text, "parse_mode": "HTML",
    }, headers={"User-Agent": UA}, timeout=30)
    if not r.ok:
        # fallback tanpa parse_mode kalau HTML error
        r = requests.post(_api(token, "sendMessage"), json={
            "chat_id": chat_id, "text": text,
        }, headers={"User-Agent": UA}, timeout=30)
    r.raise_for_status()


def send_photo(token, chat_id, png_bytes, caption):
    r = requests.post(_api(token, "sendPhoto"),
                      data={"chat_id": chat_id, "caption": caption[:1024], "parse_mode": "HTML"},
                      files={"photo": ("chart.png", io.BytesIO(png_bytes))},
                      headers={"User-Agent": UA}, timeout=60)
    if not r.ok:
        r = requests.post(_api(token, "sendPhoto"),
                          data={"chat_id": chat_id, "caption": caption[:1024]},
                          files={"photo": ("chart.png", io.BytesIO(png_bytes))},
                          headers={"User-Agent": UA}, timeout=60)
    r.raise_for_status()


def poll_commands(token, chat_id, offset, stats_fn):
    """Cek /stats di getUpdates. Return offset baru."""
    try:
        r = requests.get(_api(token, "getUpdates"), params={"offset": offset, "timeout": 0},
                         headers={"User-Agent": UA}, timeout=15)
        updates = r.json().get("result", [])
    except Exception:
        return offset
    new_offset = offset
    for u in updates:
        new_offset = u["update_id"] + 1
        msg = u.get("message") or {}
        if msg.get("chat", {}).get("id") != int(chat_id):
            continue
        text = (msg.get("text") or "").strip().lower()
        if text.startswith("/stats"):
            try:
                send_message(token, chat_id, stats_fn())
            except Exception as e:
                send_message(token, chat_id, f"Error stats: {e}")
    return new_offset


DISCLAIMER = ("\n\n⚠️ Sinyal otomatis, bukan nasihat keuangan. "
              "Backtest ≠ hasil masa depan. Risiko & keputusan tanggung jawab kamu.")


def format_signal(sig, cfg_tg):
    tag = "📈 TREND" if sig["strategy"] == "TREND" else "🧠 SMC"
    arrow = "🟢 BUY" if sig["direction"] == "Buy" else "🔴 SELL"
    equity = cfg_tg["account_equity"]
    risk_usd = equity * cfg_tg["risk_pct"] / 100
    sl_dist = abs(sig["entry"] - sig["sl"])
    # XAUUSD: 1.00 lot = 100 oz, $1 gerak = $100/lot -> lot = risk / (sl_dist * 100)
    lot = round(risk_usd / (sl_dist * 100), 2)
    rr2 = abs(sig["tp2"] - sig["entry"]) / sl_dist
    extra = ""
    if sig["strategy"] == "TREND":
        extra = f"\n📋 Checklist: {sig['score']}/{sig['max_score']}"
    elif sig.get("counter_trend"):
        extra = "\n⚠️ Counter-trend (sweep + CHoCH)"
    return (
        f"<b>{tag} | XAUUSD {arrow}</b>\n"
        f"{'─' * 22}\n"
        f"🎯 Entry : <code>{sig['entry']:.2f}</code>\n"
        f"🛑 SL    : <code>{sig['sl']:.2f}</code>  (-1R)\n"
        f"✅ TP1   : <code>{sig['tp1']:.2f}</code>  (SL→BE)\n"
        f"🏆 TP2   : <code>{sig['tp2']:.2f}</code>  ({rr2:.1f}R)"
        f"{'  +RUNNER' if sig.get('hold') else ''}\n"
        f"📏 Jarak SL: {sl_dist:.1f} pts | ATR: {sig['atr']:.2f}\n"
        f"💰 Saran lot (equity ${equity:.0f}, risk {cfg_tg['risk_pct']}%): <b>{lot}</b>"
        f"{extra}\n\n🤖 <b>Alasan AI:</b>\n{sig.get('reasoning', '-')}"
        f"{DISCLAIMER}"
    )
