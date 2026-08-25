"""Deploy Gold Signal Bot ke Modal (jadwal tiap 15 menit, tanpa server).

Setup sekali:
  1. pip install modal
  2. python -m modal setup          (login via browser, pakai akun GitHub)
  3. Buat secret di dashboard Modal (modal.com/secrets) nama: goldbot-secrets
     isi env: TWELVEDATA_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
              AI_API_KEY, AI_BASE_URL, AI_MODEL
  4. modal deploy modal_app.py
"""
import subprocess

import modal

app = modal.App("gold-signal-bot")

image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install_from_requirements("requirements.txt")
    .add_local_dir("src", remote_path="/app/src")
    .add_local_file("config.yaml", remote_path="/app/config.yaml")
)

volume = modal.Volume.from_name("goldbot-data", create_if_missing=True)


@app.function(
    image=image,
    schedule=modal.Cron("12-59/15 * * * *"),  # offset +12 menit: PC jalan duluan (menit 9/24/39/54)
    secrets=[modal.Secret.from_name("goldbot-secrets")],
    volumes={"/data": volume},
    timeout=300,
)
def scan():
    import os
    import shutil

    os.makedirs("/data", exist_ok=True)
    for f in ("config.yaml",):
        if not os.path.exists(f"/data/{f}"):
            shutil.copy(f"/app/{f}", f"/data/{f}")
    env = dict(os.environ, BOT_DATA_DIR="/data")
    r = subprocess.run(
        ["python", "src/main.py"], cwd="/app", env=env, capture_output=True, text=True,
    )
    print(r.stdout)
    print(r.stderr)
    volume.commit()
