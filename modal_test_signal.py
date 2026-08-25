"""Tes sinyal dummy via Modal: data asli -> chart -> AI vision -> Telegram.
Jalankan: python -m modal run modal_test_signal.py"""
import modal

app = modal.App("goldbot-dummy-test")

image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install_from_requirements("requirements.txt")
    .add_local_dir("src", remote_path="/app/src")
    .add_local_file("config.yaml", remote_path="/app/config.yaml")
)


@app.function(image=image, secrets=[modal.Secret.from_name("goldbot-secrets")], timeout=600)
def dummy_signal():
    import os
    import subprocess
    import sys

    env = dict(os.environ, BOT_DATA_DIR="/tmp", DUMMY_TEST="1")
    r = subprocess.run(["python", "src/dummy_signal.py"], cwd="/app", env=env,
                       capture_output=True, text=True)
    print(r.stdout[-3000:])
    print(r.stderr[-2000:])


# opsional: jalankan juga tes dari GitHub Actions dengan workflow_dispatch input
