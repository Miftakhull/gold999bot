import json, subprocess, zipfile, io, requests

def token():
    out = subprocess.run(["git", "credential", "fill"], input="protocol=https\nhost=github.com\n\n",
                         capture_output=True, text=True).stdout
    return dict(l.split("=", 1) for l in out.strip().splitlines())["password"]

t = token()
h = {"Authorization": f"token {t}"}
z = requests.get("https://api.github.com/repos/Miftakhull/gold999bot/actions/runs/32801356408/logs", headers=h)
zf = zipfile.ZipFile(io.BytesIO(z.content))
print("files:", zf.namelist())
for name in zf.namelist():
    if "bot" in name.lower():
        text = zf.read(name).decode("utf-8", errors="replace")
        print("=" * 20, name)
        print(text[-3000:])
