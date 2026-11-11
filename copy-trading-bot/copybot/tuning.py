"""Gemeinsame Regeln, welche Einstellungen der Bot selbst verändern darf – und in welchen Grenzen.

Grundsatz: Der Bot darf VORSICHTIGER werden, aber nie riskanter, als du es in config.yaml eingestellt hast
(Ausnahme: Stop-Loss-Abstand, der innerhalb fester Grenzen in beide Richtungen lernen darf).
"""
from __future__ import annotations

import copy
import time

# parameter -> (untere Grenze, obere Grenze, "cap"=nie über den Wert aus config.yaml, Ganzzahl?)
TUNABLE = {
    "risk.stop_loss_pct": (0.04, 0.15, False, False),
    "copy.copy_ratio": (0.1, 1.0, True, False),
    "risk.max_leverage": (0.5, 5.0, True, False),
    "risk.max_position_pct": (0.1, 0.5, True, False),
    "selection.top_n": (3, 8, False, True),
    "selection.min_median_hold_minutes": (30, 480, False, False),
    "selection.drop_trader_loss_pct": (0.05, 0.3, False, False),
}


def get_cfg_value(cfg: dict, key: str):
    sec, name = key.split(".")
    return cfg[sec][name]


def param(cfg: dict, state: dict, key: str):
    """Aktueller Wert: gelernter Wert (falls vorhanden), sonst config.yaml."""
    return state.get("overrides", {}).get(key, get_cfg_value(cfg, key))


def clamp(cfg: dict, key: str, value: float):
    lo, hi, cap, is_int = TUNABLE[key]
    if cap:
        hi = min(hi, get_cfg_value(cfg, key))
    v = max(lo, min(hi, float(value)))
    return int(round(v)) if is_int else round(v, 4)


def set_param(cfg: dict, state: dict, key: str, value, reason: str, source: str) -> dict | None:
    """Setzt einen gelernten Wert (begrenzt). Gibt die Änderung zurück oder None, wenn nichts geändert wurde."""
    if key not in TUNABLE:
        return None
    old = param(cfg, state, key)
    new = clamp(cfg, key, value)
    if abs(float(new) - float(old)) < 1e-9:
        return None
    state.setdefault("overrides", {})[key] = new
    change = {"t": time.time(), "param": key, "old": old, "new": new, "reason": reason, "source": source}
    log_event(state, "changes", change, limit=300)
    return change


def log_event(state: dict, kind: str, entry: dict, limit: int = 1000):
    """Tagebuch: begrenzte Listen im Zustand (trades, stops, errors, days, changes, reviews)."""
    j = state.setdefault("journal", {})
    lst = j.setdefault(kind, [])
    lst.append(entry)
    if len(lst) > limit:
        del lst[: len(lst) - limit]


def effective_cfg(cfg: dict, state: dict) -> dict:
    """config.yaml + gelernte Werte = die Einstellungen, mit denen der Bot gerade wirklich handelt."""
    c = copy.deepcopy(cfg)
    for key, v in state.get("overrides", {}).items():
        sec, name = key.split(".")
        c[sec][name] = v
    return c
