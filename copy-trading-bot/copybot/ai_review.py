"""Wöchentliche KI-Analyse mit Claude: liest das Tagebuch des Bots, findet Muster und Fehler
und schlägt begrenzte Einstellungs-Änderungen vor (optional automatisch übernommen).
Benötigt die Umgebungsvariable ANTHROPIC_API_KEY. Kosten: wenige Cent pro Analyse.
"""
from __future__ import annotations

import json
import logging
import os
import time

from .tuning import TUNABLE, param, set_param

log = logging.getLogger(__name__)
MODEL = "claude-opus-5-5"

SYSTEM = """Du bist ein erfahrener, nüchterner Risiko-Analyst für einen automatischen Copy-Trading-Bot \
auf Hyperliquid (Perpetual Futures). Du bekommst das Tagebuch der letzten Woche als JSON.

Deine Aufgabe:
1. Fasse in einfachem Deutsch zusammen, wie die Woche lief (der Besitzer ist Einsteiger).
2. Finde konkrete Probleme und Fehlerquellen (z. B. Trader, die Geld kosten, unnötige Stop-Outs, \
teure Verzögerung, wiederkehrende technische Fehler).
3. Schlage höchstens 3 Änderungen an den erlaubten Parametern vor. Ändere nur etwas, wenn die Daten \
es klar stützen – bei wenig Daten lieber nichts ändern. Kapitalerhalt geht vor Rendite.
4. Nenne Probleme, die eine Code-Änderung brauchen, separat unter code_probleme."""


def _schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "zusammenfassung": {"type": "string"},
            "probleme": {"type": "array", "items": {"type": "string"}},
            "code_probleme": {"type": "array", "items": {"type": "string"}},
            "vorschlaege": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "parameter": {"type": "string", "enum": sorted(TUNABLE)},
                        "neuer_wert": {"type": "number"},
                        "begruendung": {"type": "string"},
                    },
                    "required": ["parameter", "neuer_wert", "begruendung"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["zusammenfassung", "probleme", "code_probleme", "vorschlaege"],
        "additionalProperties": False,
    }


def build_digest(bot, days: int = 7) -> dict:
    st, cfg = bot.state, bot.cfg
    since = time.time() - days * 86400
    j = st.get("journal", {})
    recent = lambda k: [e for e in j.get(k, []) if e.get("t", 0) >= since]  # noqa: E731
    return {
        "modus": cfg["mode"],
        "parameter_aktuell": {k: param(cfg, st, k) for k in TUNABLE},
        "parameter_grenzen": {k: {"min": v[0], "max": v[1], "nie_ueber_config": v[2]} for k, v in TUNABLE.items()},
        "tageswerte": recent("days"),
        "trades": recent("trades")[-200:],
        "stop_losses": recent("stops"),
        "fehler": recent("errors")[-100:],
        "bisherige_aenderungen": recent("changes"),
        "trader": [{**{k: t.get(k) for k in ("address", "monthRoi", "median_hold_min", "accountValue")},
                    "gewicht": st.get("weights", {}).get(t["address"], 1.0),
                    "dein_gewinn_usd": round(st["trader_stats"].get(t["address"], {}).get("pnl", 0.0), 2)}
                   for t in bot.leaders],
        "aussortiert": list(st.get("benched", {})),
        "kill_switch_aktiv": st.get("halted", False),
    }


def run_review(bot, client=None) -> str:
    if client is None:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            return "KI-Analyse übersprungen: ANTHROPIC_API_KEY ist nicht gesetzt."
        import anthropic
        client = anthropic.Anthropic()

    digest = build_digest(bot)
    resp = client.beta.messages.create(
        model=MODEL,
        max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        system=SYSTEM,
        output_config={"effort": "high", "format": {"type": "json_schema", "schema": _schema()}},
        messages=[{"role": "user", "content": "Tagebuch der letzten Woche:\n" + json.dumps(digest, default=str)}],
    )
    if resp.stop_reason == "refusal":
        return "KI-Analyse wurde abgelehnt – keine Änderungen."
    if resp.stop_reason == "max_tokens":
        return "KI-Analyse unvollständig (zu lang) – keine Änderungen."
    text = next((b.text for b in resp.content if b.type == "text"), "")
    result = json.loads(text)

    auto = bot.cfg.get("ai_review", {}).get("auto_apply", True)
    applied = []
    for v in result.get("vorschlaege", [])[:3]:
        if auto:
            ch = set_param(bot.cfg, bot.state, v["parameter"], v["neuer_wert"], v["begruendung"], "ki")
            if ch:
                applied.append(f"✅ {ch['param']}: {ch['old']} → {ch['new']} – {v['begruendung']}")
        else:
            applied.append(f"💡 {v['parameter']} → {v['neuer_wert']} – {v['begruendung']}")
    bot.state.setdefault("journal", {}).setdefault("reviews", []).append(
        {"t": time.time(), "ergebnis": result, "angewendet": applied})
    bot.state["journal"]["reviews"] = bot.state["journal"]["reviews"][-12:]

    lines = ["🤖 Wöchentliche KI-Analyse", "", result["zusammenfassung"]]
    if result["probleme"]:
        lines += ["", "Gefundene Probleme:"] + [f"• {p}" for p in result["probleme"]]
    lines += ["", "Änderungen:" if auto else "Vorschläge (nicht automatisch übernommen):"]
    lines += applied or ["• keine – Daten sprechen nicht klar für eine Änderung"]
    if result["code_probleme"]:
        lines += ["", "🛠 Braucht ein Code-Update (bitte an Claude weitergeben):"] + [f"• {p}" for p in result["code_probleme"]]
    return "\n".join(lines)
