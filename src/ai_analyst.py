"""Kirim data + gambar chart ke AI (Claude via OpenAI-compatible endpoint) untuk validasi setup."""
import base64
import json

import requests

BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

SYSTEM_PROMPT = """You are a strict trading setup VALIDATOR for XAUUSD (M15 swing setups + M5 supply/demand scalping).
A rule-based engine has ALREADY computed all strategy rules and price levels (entry/SL/TP).
Your job is NOT to invent a strategy. Your job:
1. Look at the annotated charts and verify visually what is hard to compute:
   - Is the marked order block / FVG / supply-demand zone FRESH (untouched) and likely to react?
   - Is the breakout candle a genuine impulsive break (not a wick fakeout)?
   - For M5 scalp: does the base zone look clean, and does the price action reaction at the zone look genuine?
   - Does the higher timeframe chart support the stated bias?
2. Check the provided numeric checklist data for consistency.
3. For EACH strategy (trend, smc, scalp) return a verdict:
   - "perfect": setup fully valid, high quality, worth trading now
   - "good": valid but not exceptional
   - "no": invalid, unclear, or contradicts the charts
   (If a strategy has "signal": false in the data, verdict must be "no".)
4. confidence: 0-100 integer. Be conservative: only 85+ for truly clean setups.
5. reasoning: max 2 short sentences in Indonesian.

Respond with ONLY this JSON (no markdown fences, no extra text):
{"trend": {"verdict": "perfect|good|no", "confidence": 0, "reasoning": "..."},
 "smc": {"verdict": "perfect|good|no", "confidence": 0, "reasoning": "..."},
 "scalp": {"verdict": "perfect|good|no", "confidence": 0, "reasoning": "..."}}"""


def _img_content(b64):
    return {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}


def validate(secrets, cfg, data_payload, charts):
    """charts: dict {nama: png_bytes}. Return dict verdict per strategi atau raise."""
    content = [{"type": "text", "text": (
        "DATA TERHITUNG ENGINE (fakta, jangan diubah):\n"
        + json.dumps(data_payload, ensure_ascii=False, indent=1)
        + "\n\nGambar-gambar chart ter-anotasi (urutan): "
        + ", ".join(charts.keys())
        + ". Validasi sesuai instruksi sistem."
    )}]
    for name, png in charts.items():
        b64 = base64.b64encode(png).decode()
        content.append(_img_content(b64))
    body = {
        "model": secrets["AI_MODEL"],
        "max_tokens": cfg["ai"]["max_tokens"],
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": content},
        ],
    }
    url = secrets["AI_BASE_URL"].rstrip("/") + "/chat/completions"
    origin = "/".join(secrets["AI_BASE_URL"].rstrip("/").split("/")[:3])
    r = requests.post(
        url, json=body, timeout=cfg["ai"]["timeout"],
        headers={
            "Authorization": f"Bearer {secrets['AI_API_KEY']}",
            "Content-Type": "application/json",
            "User-Agent": BROWSER_UA,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9,id;q=0.8",
            "Origin": origin,
            "Referer": origin + "/",
            "sec-ch-ua": '"Not/A)Brand";v="8", "Chromium";v="126", "Google Chrome";v="126"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
        },
    )
    if r.status_code == 403:
        raise PermissionError("AI endpoint 403 (Cloudflare blok IP ini)")
    r.raise_for_status()
    content_txt = r.json()["choices"][0]["message"]["content"]
    result = _parse_verdicts(content_txt)
    for k in ("trend", "smc"):
        if k not in result:
            raise ValueError(f"AI response tidak punya key '{k}': {content_txt[:200]}")
    result.setdefault("scalp", {"verdict": "no", "confidence": 0, "reasoning": "tidak dievaluasi"})
    return result


def _parse_verdicts(text):
    """Parse JSON verdict; kalau AI balas JSON rusak, pakai parser regex cadangan."""
    text = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # cadangan: ekstrak per-strategi dengan regex
    import re
    result = {}
    for strat in ("trend", "smc", "scalp"):
        m = re.search(
            rf'"{strat}"\s*:\s*{{.*?"verdict"\s*:\s*"(\w+)".*?"confidence"\s*:\s*(\d+).*?"reasoning"\s*:\s*"(.*?)"\s*}}',
            text, re.DOTALL)
        if m:
            result[strat] = {"verdict": m.group(1), "confidence": int(m.group(2)),
                             "reasoning": m.group(3)}
    if not result:
        raise ValueError(f"AI response tidak bisa diparse: {text[:200]}")
    return result
