"""Statistik winrate & profit R dari CSV."""
from datetime import datetime, timezone, timedelta

import logger


def _fmt_block(name, rows):
    wins = sum(1 for r in rows if r[10] in ("WIN", "RUNNER-WIN"))
    losses = sum(1 for r in rows if r[10] == "LOSS")
    bes = sum(1 for r in rows if r[10] == "BE")
    voids = sum(1 for r in rows if r[10] == "VOID")
    total_r = 0.0
    for r in rows:
        try:
            if r[11]:
                total_r += float(r[11])
        except (ValueError, IndexError):
            pass
    decided = wins + losses
    wr = (wins / decided * 100) if decided else 0.0
    return (f"{name:<11}: {wins} win | {losses} loss | {bes} BE | {voids} void "
            f"→ {wr:.1f}% | {total_r:+.1f}R\n"), decided, wins


def stats_text(days=30):
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()
    rows = [r for r in logger.load_rows()[1:]
            if len(r) > 11 and r[0][:10] >= cutoff and r[1] != "MONITOR"]
    if not rows:
        return "📊 Belum ada sinyal selesai dalam 30 hari terakhir."
    out = [f"📊 XAUUSD M15 — {days} hari terakhir"]
    total_decided, total_wins = 0, 0
    for name, strat in [("[TREND]", "TREND"), ("[SMC]", "SMC")]:
        sub = [r for r in rows if r[1] == strat]
        if sub:
            line, d, w = _fmt_block(name, sub)
            out.append(line.rstrip())
            total_decided += d
            total_wins += w
    conf = [r for r in rows if r[1] in ("TREND", "SMC")]
    line, d, w = _fmt_block("TOTAL", conf)
    out.append("─" * 30)
    out.append(line.rstrip())
    return "\n".join(out)
