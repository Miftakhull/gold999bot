"""Tes 1x: apakah Cloudflare tabitoken nerema IP Modal?"""
import modal

app = modal.App("goldbot-ai-test")

image = modal.Image.debian_slim(python_version="3.12").pip_install("requests")


@app.function(secrets=[modal.Secret.from_name("goldbot-secrets")], timeout=120)
def test_ai():
    import json
    import os
    import urllib.request

    ua = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
    base = os.environ["AI_BASE_URL"].rstrip("/")
    body = json.dumps({"model": os.environ["AI_MODEL"], "max_tokens": 10,
                       "messages": [{"role": "user", "content": "Say OK"}]}).encode()
    req = urllib.request.Request(
        base + "/chat/completions", data=body, method="POST",
        headers={"Authorization": f"Bearer {os.environ['AI_API_KEY']}",
                 "Content-Type": "application/json", "User-Agent": ua,
                 "Accept": "application/json"},
    )
    try:
        k = os.environ.get("AI_API_KEY", "")
        print("DEBUG key len:", len(k), "| awal:", k[:6], "| akhir:", k[-4:])
        print("DEBUG base:", base)
        print("DEBUG model:", os.environ.get("AI_MODEL"))
        with urllib.request.urlopen(req, timeout=90) as resp:
            print("STATUS:", resp.status)
            print("BODY:", resp.read().decode()[:300])
    except Exception as e:
        print("GAGAL:", e)
