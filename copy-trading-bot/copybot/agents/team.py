"""Führt das Agenten-Team aus und übersetzt die Entscheidung des Risiko-Chefs in Bot-Regeln."""
from __future__ import annotations

import contextlib
import datetime as dt
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor

from ..tuning import log_event
from .base import DEFAULT_MODEL, BudgetExceeded, CostTracker
from .indicators import summarize
from .specialists import SPECIALISTS, RiskChief

log = logging.getLogger(__name__)

OVERLAY_TTL_H = 24  # Entscheidung verfällt, wenn das Team so lange nicht mehr lief


def gather_context(bot) -> dict:
    data, st = bot.data, bot.state
    mids = data.mids()
    positions = [{"coin": d["coin"], "richtung": "LONG" if d["szi"] > 0 else "SHORT", "wert_usd": round(d["value"], 2),
                  "gewinn_usd": round(d["upnl"], 2)} for d in bot.broker.position_details(mids)]
    leader_pos, traders = {}, []
    for t in bot.leaders:
        try:
            acc = data.account(t["address"])
        except Exception as e:
            log.warning("Trader %s nicht ladbar: %s", t["address"], e)
            continue
        av = acc["accountValue"] or 1
        pos = {c: {"richtung": "LONG" if p["szi"] > 0 else "SHORT",
                   "hebel_auf_konto": round(abs(p["szi"]) * mids.get(c, p["entryPx"]) / av, 2),
                   "unreal_pnl": round(p.get("unrealizedPnl", 0))} for c, p in acc["positions"].items()}
        for c in pos:
            leader_pos.setdefault(c, 0)
            leader_pos[c] += 1
        s = st["trader_stats"].get(t["address"], {})
        traders.append({"adresse": t["address"], "konto_usd": round(av), "positionen": pos,
                        "monat_roi": t.get("monthRoi"), "haltedauer_min": t.get("median_hold_min"),
                        "gewinn_fuer_bot_usd": round(s.get("pnl", 0), 2),
                        "gewicht": round(st.get("weights", {}).get(t["address"], 1.0), 2),
                        "einstiegs_verzoegerung_pct": round(s["lag_sum"] / s["lag_n"] * 100, 3) if s.get("lag_n") else None})
    coins = sorted({p["coin"] for p in positions} | set(leader_pos) | {"BTC", "ETH"},
                   key=lambda c: (-(leader_pos.get(c, 0)), c))[:12]
    try:
        ctxs = data.market_contexts()
    except Exception:
        ctxs = {}
    market = {}
    for c in coins:
        try:
            market[c] = summarize(data.candles(c), ctxs.get(c))
        except Exception as e:
            market[c] = {"fehler": str(e)[:100]}
    equity = bot.broker.equity(mids)
    peak = st.get("peak_equity") or equity
    return {"datum": dt.date.today().isoformat(), "coins": coins, "market": market, "positions": positions,
            "traders": traders, "trader_ids": [t["adresse"] for t in traders],
            "account": {"kontowert": round(equity, 2), "hoechststand": round(peak, 2),
                        "drawdown_pct": round((1 - equity / peak) * 100, 2) if peak else 0, "modus": bot.cfg["mode"]}}


def clamp01(x) -> float:
    try:
        return max(0.0, min(1.0, float(x)))
    except (TypeError, ValueError):
        return 1.0


def apply_decision(state: dict, decision: dict) -> dict:
    now = time.time()
    overlay = {
        "t": now,
        "ampel": decision.get("marktampel", "gruen"),
        "global": clamp01(decision.get("global_faktor", 1.0)),
        "coins": {c["coin"]: clamp01(c["faktor"]) for c in decision.get("coin_faktoren", [])},
        "trader": {t["adresse"].lower(): clamp01(t["faktor"]) for t in decision.get("trader_vertrauen", [])},
        "sperren": {s["coin"]: now + max(1, min(72, float(s["stunden"]))) * 3600 for s in decision.get("sperren", [])},
    }
    state["agent_overlay"] = overlay
    return overlay


def active_overlay(state: dict) -> dict | None:
    o = state.get("agent_overlay")
    if not o or time.time() - o["t"] > OVERLAY_TTL_H * 3600:
        return None
    return o


def run_team(bot, client=None, lock=None) -> str:
    acfg = bot.cfg.get("agents", {})
    if not acfg.get("enabled", True):
        return "Agenten sind ausgeschaltet."
    if client is None:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            return "Agenten übersprungen: ANTHROPIC_API_KEY ist nicht gesetzt."
        import anthropic
        client = anthropic.Anthropic()
    lock = lock or contextlib.nullcontext()
    model = acfg.get("model", DEFAULT_MODEL)
    with lock:
        costs = CostTracker(bot.state, acfg.get("monthly_budget_usd", 30))
    try:
        costs.check()
    except BudgetExceeded as e:
        return f"💸 {e} – Agenten pausieren bis Monatsende."

    started = time.time()
    ctx = gather_context(bot)  # nur lesen + Netzwerk -> blockiert den Handel nicht

    def run_one(cls):
        agent = cls(client, model, costs)
        try:
            return agent.run(ctx)
        except Exception as e:
            log.exception("%s fehlgeschlagen", cls.name)
            return {"key": cls.key, "name": cls.name, "emoji": cls.emoji, "role": cls.role, "t": time.time(),
                    "ok": False, "text": f"Fehler: {type(e).__name__}: {str(e)[:200]}"}

    with ThreadPoolExecutor(max_workers=len(SPECIALISTS)) as ex:
        reports = list(ex.map(run_one, SPECIALISTS))
    ctx["reports"] = reports
    chief = run_one(RiskChief)
    all_reports = reports + [chief]

    with lock:
        return _store_results(bot, reports, chief, all_reports, model, started)


def _store_results(bot, reports, chief, all_reports, model, started) -> str:
    st = bot.state
    st["agents"] = {"t": time.time(), "dauer_s": round(time.time() - started, 1), "model": model,
                    "reports": {r["key"]: r for r in all_reports}}
    lines = ["🧑‍💼 Agenten-Team Bericht"]
    if chief.get("ok") and "data" in chief:
        d = chief["data"]
        ov = apply_decision(st, d)
        log_event(st, "agent_decisions", {"t": time.time(), **d}, limit=200)
        ampel = {"gruen": "🟢", "gelb": "🟡", "rot": "🔴"}.get(ov["ampel"], "⚪")
        lines += [f"{ampel} Markt-Ampel: {ov['ampel'].upper()}", "", d["zusammenfassung"], "",
                  f"Positionsgröße gesamt: {ov['global'] * 100:.0f} %"]
        lines += [f"• {c['coin']}: {clamp01(c['faktor']) * 100:.0f} % – {c['grund']}" for c in d["coin_faktoren"]]
        lines += [f"⛔ {s['coin']} gesperrt für {s['stunden']:.0f} h – {s['grund']}" for s in d["sperren"]]
        lines += [f"🕵️ Trader {t['adresse'][:10]}… Vertrauen {clamp01(t['faktor']) * 100:.0f} % – {t['grund']}"
                  for t in d["trader_vertrauen"]]
        if d["warnungen"]:
            lines += ["", "⚠️ Warnungen:"] + [f"• {w}" for w in d["warnungen"]]
    else:
        lines.append("Risiko-Chef konnte nicht entscheiden – Bot läuft mit normalen Regeln weiter.")
    failed = [r["name"] for r in reports if not r.get("ok")]
    if failed:
        lines.append("Ausgefallen: " + ", ".join(failed))
    lines.append(f"\nKosten diesen Monat: {st['agent_costs']['usd']:.2f} USD")
    return "\n".join(lines)
