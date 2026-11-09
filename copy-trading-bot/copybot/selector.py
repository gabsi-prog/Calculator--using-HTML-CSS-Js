"""Wählt die 'besten' Trader aus dem Hyperliquid-Leaderboard.

Idee: Nicht einfach den mit dem höchsten Gewinn nehmen (oft Glück / Riesen-Hebel),
sondern Trader, die konstant profitabel, aktiv und groß genug sind.
"""
from __future__ import annotations

import math


def _perf(row: dict) -> dict[str, dict[str, float]]:
    out = {}
    for window, vals in row.get("windowPerformances", []):
        out[window] = {k: float(v) for k, v in vals.items()}
    return out


def score_trader(row: dict) -> float:
    """Höher = besser. Gewichtet Monat, Woche und Gesamtperformance + Konsistenz."""
    p = _perf(row)
    m, w, a = p.get("month", {}), p.get("week", {}), p.get("allTime", {})
    month_roi = m.get("roi", 0.0)
    week_roi = w.get("roi", 0.0)
    alltime_pnl = a.get("pnl", 0.0)
    # Konsistenz: Bonus wenn Tag/Woche/Monat/Gesamt alle positiv
    windows_positive = sum(1 for k in ("day", "week", "month", "allTime") if p.get(k, {}).get("pnl", 0) > 0)
    # log-skaliert, damit Wal-Konten nicht alles dominieren
    size_factor = math.log10(max(alltime_pnl, 1))
    # ROI gedämpft (sqrt), damit extreme Glücks-Treffer nicht gewinnen
    roi_part = math.copysign(math.sqrt(abs(month_roi)), month_roi) * 2 + math.copysign(
        math.sqrt(abs(week_roi)), week_roi
    )
    return roi_part * (1 + windows_positive / 4) + size_factor * 0.1


def select_traders(rows: list[dict], cfg: dict) -> list[dict]:
    excluded = {a.lower() for a in cfg.get("excluded_traders", [])}
    pinned = [a.lower() for a in cfg.get("pinned_traders", [])]
    candidates = []
    for row in rows:
        addr = row["ethAddress"].lower()
        if addr in excluded or addr in pinned:
            continue
        p = _perf(row)
        acct = float(row.get("accountValue", 0))
        m, w, a = p.get("month", {}), p.get("week", {}), p.get("allTime", {})
        if not (cfg["min_account_value"] <= acct <= cfg["max_account_value"]):
            continue
        if m.get("roi", 0) < cfg["min_month_roi"] or m.get("roi", 0) > cfg["max_month_roi"]:
            continue
        if a.get("pnl", 0) < cfg["min_alltime_pnl"]:
            continue
        if cfg.get("require_positive_week", True) and w.get("pnl", 0) <= 0:
            continue
        if m.get("vlm", 0) < cfg["min_month_volume"]:
            continue
        candidates.append(
            {
                "address": addr,
                "name": row.get("displayName") or addr[:10],
                "accountValue": acct,
                "monthRoi": m.get("roi", 0),
                "weekRoi": w.get("roi", 0),
                "allTimePnl": a.get("pnl", 0),
                "score": score_trader(row),
            }
        )
    candidates.sort(key=lambda c: c["score"], reverse=True)
    picked = [{"address": a, "name": "pinned", "score": float("inf")} for a in pinned]
    picked += candidates[: max(0, cfg["top_n"] - len(picked))]
    return picked
