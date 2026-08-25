"""Log sinyal & hasil ke CSV."""
import csv
import os
from datetime import datetime, timezone

CSV_PATH = "signals_log.csv"
FIELDS = ["time", "strategy", "direction", "entry", "sl", "tp1", "tp2", "risk",
          "score", "ai_verdict", "ai_confidence", "status", "result_r", "closed_time", "reasoning"]


def append_signal(sig, ai_verdict, ai_confidence, reasoning):
    exists = os.path.exists(CSV_PATH)
    with open(CSV_PATH, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if not exists:
            w.writerow(FIELDS)
        w.writerow([
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
            sig["strategy"], sig["direction"],
            f"{sig['entry']:.2f}", f"{sig['sl']:.2f}", f"{sig['tp1']:.2f}", f"{sig['tp2']:.2f}",
            f"{sig['risk']:.2f}", sig.get("score", "-"), ai_verdict, ai_confidence,
            "ACTIVE", "", "", reasoning,
        ])


def update_status(sig, status, result_r=""):
    rows = []
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    for r in reversed(rows[1:]):
        if (r[1] == sig["strategy"] and r[2] == sig["direction"]
                and abs(float(r[3]) - sig["entry"]) < 1e-6
                and r[10] == "ACTIVE"):
            r[10] = status
            r[11] = result_r
            r[12] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            break
    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(rows)


def load_rows():
    if not os.path.exists(CSV_PATH):
        return []
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        return list(csv.reader(f))


def signals_today(strategy=None):
    today = datetime.now(timezone.utc).date().isoformat()
    n = 0
    for r in load_rows()[1:]:
        if r[0][:10] == today and r[10] in ("ACTIVE", "TP1", "RUNNING", "WIN", "RUNNER-WIN", "LOSS", "BE"):
            if strategy is None or r[1] == strategy:
                n += 1
    return n


def last_signal_time(strategy, direction):
    best = None
    for r in load_rows()[1:]:
        if r[1] == strategy and r[2] == direction and r[10] != "REJECTED":
            t = datetime.fromisoformat(r[0])
            if best is None or t > best:
                best = t
    return best


def monitors_today():
    today = datetime.now(timezone.utc).date().isoformat()
    return sum(1 for r in load_rows()[1:]
               if r[0][:10] == today and r[1] == "MONITOR")
