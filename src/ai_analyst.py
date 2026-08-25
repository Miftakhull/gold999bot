"""Kirim data + gambar chart ke AI (Claude via OpenAI-compatible endpoint) untuk validasi setup."""
import base64
import json

import requests

BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

SYSTEM_PROMPT = """You are a strict trading setup VALIDATOR for XAUUSD M15 scalping/day trading.
A rule-based engine has ALREADY computed all strategy rules and price levels (entry/SL/TP).
Your job is NOT to invent a strategy. Your job:
1. Look at the annotated charts (M15 execution + H1 bias) and verify visually what is hard to compute:
   - Is the marked order block / FVG zone FRESH (untouched) and likely to react?
   - Is the breakout candle a genuine impulsive break (not a wick fakeout)?
   - Does price action on H1 support the stated bias?
2. Check the provided numeric checklist data for consistency.
3. For EACH strategy (trend, smc) return a verdict:
   - "perfect": setup fully valid, high quality, worth trading now
   - "good": valid but not exceptional
   - "no": invalid, unclear, or contradicts the charts
4. confidence: 0-100 integer. Be conservative: only 85+ for truly clean setups.
5. reasoning: max 2 short sentences in Indonesian.

Respond with ONLY this JSON (no markdown fences, no extra text):
{"trend": {"verdict": "perfect|good|no", "confidence": 0, "reasoning": "..."},
 "smc": {"verdict": "perfect|good|no", "confidence": 0, "reasoning": "..."}}"""


def _img_content(b64):
    return {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}


def validate(secrets, cfg, data_payload, chart_m15_png, chart_h1_png):
    """Return dict {trend: {verdict, confidence, reasoning}, smc: {...}} atau raise."""
    b64_m15 = base64.b64encode(chart_m15_png).decode()
    b64_h1 = base64.b64encode(chart_h1_png).decode()
    user_text = (
        "DATA TERHITUNG ENGINE (fakta, jangan diubah):\n"
        + json.dumps(data_payload, ensure_ascii=False, indent=1)
        + "\n\nGambar 1 = chart M15 (zona OB/FVG + level dianotasi). "
        "Gambar 2 = chart H1 (bias trend). Validasi sesuai instruksi sistem."
    )
    body = {
        "model": secrets["AI_MODEL"],
        "max_tokens": cfg["ai"]["max_tokens"],
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": [
                {"type": "text", "text": user_text},
                _img_content(b64_m15),
                _img_content(b64_h1),
            ]},
        ],
    }
    url = secrets["AI_BASE_URL"].rstrip("/") + "/chat/completions"
    r = requests.post(
        url, json=body, timeout=cfg["ai"]["timeout"],
        headers={
            "Authorization": f"Bearer {secrets['AI_API_KEY']}",
            "Content-Type": "application/json",
            "User-Agent": BROWSER_UA,
        },
    )
    r.raise_for_status()
    content = r.json()["choices"][0]["message"]["content"]
    content = content.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    result = json.loads(content)
    for k in ("trend", "smc"):
        if k not in result:
            raise ValueError(f"AI response tidak punya key '{k}': {content[:200]}")
    return result
