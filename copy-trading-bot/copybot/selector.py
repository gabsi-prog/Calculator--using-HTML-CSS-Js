"""Wählt die 'besten' Trader aus dem Hyperliquid-Leaderboard.

Nicht einfach der mit dem höchsten Gewinn (oft Glück / Riesen-Hebel), sondern Trader,
die konstant profitabel, aktiv, groß genug sind – und lange genug halten, um kopierbar zu sein.
"""
from __future__ import annotations

import math
import statistics


def _perf(row: dict) -> dict[str, dict[str, float]]:
    return {w: {k: float(v) for k, v in vals.items()} for w, vals in row.get("windowPerformances", [])}


def score_trader(row: dict) -> float:
    """Höher = besser. Gewichtet Monat und Woche (gedämpft) + Konsistenz + Größe."""
    p = _perf(row)
    month_roi = p.get("month", {}).get("roi", 0.0)
    week_roi = p.get("week", {}).get("roi", 0.0)
    alltime_pnl = p.get("allTime", {}).get("pnl", 0.0)
    windows_positive = sum(1 for k in ("day", "week", "month", "allTime") if p.get(k, {}).get("pnl", 0) > 0)
    roi_part = math.copysign(math.sqrt(abs(month_roi)), month_roi) * 2 + math.copysign(
        math.sqrt(abs(week_roi)), week_roi
    )
    return roi_part * (1 + windows_positive / 4) + math.log10(max(alltime_pnl, 1)) * 0.1


def rank_traders(rows: list[dict], cfg: dict, exclude: set[str] | None = None) -> list[dict]:
    """Gefilterte, nach Score sortierte Kandidaten (ohne pinned)."""
    excluded = {a.lower() for a in cfg.get("excluded_traders", [])} | {a.lower() for a in (exclude or set())}
    pinned = {a.lower() for a in cfg.get("pinned_traders", [])}
    out = []
    for row in rows:
        addr = row["ethAddress"].lower()
        if addr in excluded or addr in pinned:
            continue
        p = _perf(row)
        acct = float(row.get("accountValue", 0))
        m, w, a = p.get("month", {}), p.get("week", {}), p.get("allTime", {})
        if not (cfg["min_account_value"] <= acct <= cfg["max_account_value"]):
            continue
        if not (cfg["min_month_roi"] <= m.get("roi", 0) <= cfg["max_month_roi"]):
            continue
        if a.get("pnl", 0) < cfg["min_alltime_pnl"]:
            continue
        if cfg.get("require_positive_week", True) and w.get("pnl", 0) <= 0:
            continue
        if m.get("vlm", 0) < cfg["min_month_volume"]:
            continue
        out.append({
            "address": addr,
            "name": row.get("displayName") or addr[:10],
            "accountValue": acct,
            "monthRoi": m.get("roi", 0),
            "weekRoi": w.get("roi", 0),
            "allTimePnl": a.get("pnl", 0),
            "score": score_trader(row),
        })
    out.sort(key=lambda c: c["score"], reverse=True)
    return out


def holding_stats(fills: list[dict]) -> dict:
    """Schätzt aus den Fills, wie lange ein Trader Positionen hält und wie oft er handelt."""
    fills = sorted(fills, key=lambda f: f["time"])
    if not fills:
        return {"median_hold_min": None, "fills_per_day": 0.0, "closed_trades": 0}
    opened: dict[str, int] = {}
    holds = []
    for f in fills:
        coin, t = f["coin"], f["time"]
        start = float(f["startPosition"])
        new = start + float(f["sz"]) * (1 if f["side"] == "B" else -1)
        was_flat, is_flat = abs(start) < 1e-12, abs(new) < 1e-12
        if was_flat and not is_flat:
            opened[coin] = t
        elif not was_flat and (is_flat or (new > 0) != (start > 0)):
            if coin in opened:
                holds.append((t - opened[coin]) / 60_000)
            opened.pop(coin, None)
            if not is_flat:
                opened[coin] = t
    span_days = max((fills[-1]["time"] - fills[0]["time"]) / 86_400_000, 1.0)
    return {
        "median_hold_min": statistics.median(holds) if holds else None,
        "fills_per_day": len(fills) / span_days,
        "closed_trades": len(holds),
    }


def is_scalper(stats: dict, cfg: dict) -> bool:
    mh = stats.get("median_hold_min")
    if mh is not None and mh < cfg.get("min_median_hold_minutes", 0):
        return True
    return stats.get("fills_per_day", 0) > cfg.get("max_fills_per_day", float("inf"))
