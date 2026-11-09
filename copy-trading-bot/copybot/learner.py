"""Lernen aus eigenen Ergebnissen.

Sekündlich (jeder Durchlauf):  Risikobremse – bei Verlusten automatisch kleinere Positionen.
Täglich:                       1) Trader-Gewichte: Wer dir Geld bringt, bekommt mehr Kapital (und umgekehrt)
                               2) Stop-Loss-Abstand: Wurde er oft "ausgestoppt und dann lief es doch"? -> weiter.
                                  Waren Stops berechtigt? -> enger.
                               3) Verzögerungs-Kosten: Steigst du deutlich schlechter ein als der Trader?
                                  -> nur noch Trader mit längerer Haltedauer.
Alle Änderungen sind begrenzt (siehe tuning.py) und werden im Tagebuch + per Telegram gemeldet.
"""
from __future__ import annotations

import math
import time

from .tuning import param, set_param

W_MIN, W_MAX = 0.25, 2.5


def risk_throttle(drawdown: float, max_dd: float, floor: float = 0.3) -> float:
    """1.0 ohne Verlust, linear kleiner bis 'floor' kurz vor dem Kill-Switch."""
    if max_dd <= 0:
        return 1.0
    return max(floor, 1.0 - drawdown / max_dd)


def leader_weights(state: dict, leaders: list[dict]) -> dict[str, float]:
    w = state.get("weights", {})
    return {t["address"]: w.get(t["address"], 1.0) for t in leaders}


def update_trader_weights(state: dict, leaders: list[dict], equity: float, cfg: dict) -> list[str]:
    """Multiplicative-Weights: w *= exp(eta * Rendite_seit_gestern - Verzögerungsstrafe)."""
    lcfg = cfg.get("learning", {})
    eta = lcfg.get("weight_learning_rate", 2.0)
    if not leaders:
        return []
    alloc = equity * cfg["copy"]["capital_usage"] / len(leaders)
    weights = state.setdefault("weights", {})
    notes = []
    for t in leaders:
        a = t["address"]
        st = state["trader_stats"].setdefault(a, {"pnl": 0.0, "since": time.time()})
        r = (st["pnl"] - st.get("pnl_at_learn", 0.0)) / alloc if alloc > 0 else 0.0
        st["pnl_at_learn"] = st["pnl"]
        lag = st["lag_sum"] / st["lag_n"] if st.get("lag_n") else 0.0
        old = weights.get(a, 1.0)
        new = old * math.exp(eta * max(-0.2, min(0.2, r)) - 10 * max(0.0, lag - 0.003))
        weights[a] = max(W_MIN, min(W_MAX, new))
        if abs(weights[a] - old) > 0.05:
            notes.append(f"{a[:10]}… Gewicht {old:.2f} → {weights[a]:.2f} (gestern {r * 100:+.1f} %)")
    # nicht mehr kopierte Trader vergessen
    for a in list(weights):
        if a not in {t["address"] for t in leaders}:
            weights.pop(a)
    return notes


def evaluate_stops(state: dict, mids: dict, sl_pct: float, min_age_h: float = 24) -> None:
    """Prüft 24 h nach jedem Stop-Loss: Lief der Kurs danach doch zurück über den Einstieg? (= unnötiger Stop)"""
    now = time.time()
    for s in state.get("journal", {}).get("stops", []):
        if "whipsaw" in s or now - s["t"] < min_age_h * 3600 or s["coin"] not in mids or not s.get("entry"):
            continue
        back_above_entry = (mids[s["coin"]] - s["entry"]) * s["side"] > 0
        s["whipsaw"] = bool(back_above_entry)


def adapt_stop_loss(state: dict, cfg: dict) -> dict | None:
    stops = [s for s in state.get("journal", {}).get("stops", []) if "whipsaw" in s][-10:]
    if len(stops) < cfg.get("learning", {}).get("min_samples", 3):
        return None
    rate = sum(s["whipsaw"] for s in stops) / len(stops)
    cur = param(cfg, state, "risk.stop_loss_pct")
    if rate >= 0.6:
        return set_param(cfg, state, "risk.stop_loss_pct", cur + 0.01,
                         f"{rate:.0%} der letzten {len(stops)} Stops waren unnötig (Kurs lief zurück)", "lernen")
    if rate <= 0.2:
        return set_param(cfg, state, "risk.stop_loss_pct", cur - 0.005,
                         f"nur {rate:.0%} der Stops waren unnötig – Stop darf enger", "lernen")
    return None


def adapt_hold_filter(state: dict, cfg: dict) -> dict | None:
    """Wenn das späte Einsteigen viel kostet: nur noch langsamere Trader kopieren."""
    trades = [t for t in state.get("journal", {}).get("trades", [])[-100:] if t.get("lag") is not None]
    if len(trades) < max(10, cfg.get("learning", {}).get("min_samples", 3)):
        return None
    avg = sum(t["lag"] for t in trades) / len(trades)
    cur = param(cfg, state, "selection.min_median_hold_minutes")
    if avg > 0.005:
        return set_param(cfg, state, "selection.min_median_hold_minutes", cur + 30,
                         f"Einstieg im Schnitt {avg * 100:.2f} % schlechter als der Trader", "lernen")
    if avg < 0.001 and len(trades) >= 30:
        return set_param(cfg, state, "selection.min_median_hold_minutes", cur - 15,
                         f"Verzögerung kostet kaum ({avg * 100:.2f} %) – auch schnellere Trader möglich", "lernen")
    return None


def daily_learning(bot, mids: dict, equity: float) -> list[str]:
    """Läuft 1x täglich. Gibt Klartext-Notizen zurück."""
    st, cfg = bot.state, bot.cfg
    if not cfg.get("learning", {}).get("enabled", True):
        return ["Lernen ist ausgeschaltet."]
    notes = update_trader_weights(st, bot.leaders, equity, cfg)
    evaluate_stops(st, mids, param(cfg, st, "risk.stop_loss_pct"))
    for ch in (adapt_stop_loss(st, cfg), adapt_hold_filter(st, cfg)):
        if ch:
            notes.append(f"{ch['param']}: {ch['old']} → {ch['new']} ({ch['reason']})")
            if ch["param"].startswith("selection."):
                st["last_select"] = 0  # neue Trader-Auswahl mit neuem Filter
    return notes
