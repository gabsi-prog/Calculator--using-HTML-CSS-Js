"""Selbstheilung: erkennt Fehler, ordnet sie ein und behebt sie automatisch – in Echtzeit."""
from __future__ import annotations

import logging
import time

from .tuning import log_event

log = logging.getLogger(__name__)

# Fehlertext (Kleinbuchstaben) -> (Kategorie, Gegenmaßnahme)
ORDER_RULES = [
    (("minimum value", "min order"), "zu_klein", "skip"),
    (("insufficient margin", "margin"), "zu_wenig_margin", "half"),
    (("tick size", "invalid price", "price must", "too far from"), "preis", "wider_slippage"),
    (("invalid size", "sz decimals", "size must"), "groesse", "round_coarser"),
    (("rate limit", "429", "too many"), "rate_limit", "backoff"),
    (("reduce only", "reduceonly"), "reduce_only", "skip"),
]

EXC_RULES = [
    (("timeout", "timed out", "connection", "nicht erreichbar", "temporarily", "502", "503", "504"), "netzwerk"),
    (("429", "rate limit"), "rate_limit"),
    (("keyerror", "unexpected", "jsondecode", "expecting value"), "datenformat"),
]


def classify_order_error(msg: str) -> tuple[str, str]:
    m = (msg or "").lower()
    for keys, cat, action in ORDER_RULES:
        if any(k in m for k in keys):
            return cat, action
    return "unbekannt", "retry"


def classify_exception(exc: BaseException) -> str:
    m = f"{type(exc).__name__} {exc}".lower()
    for keys, cat in EXC_RULES:
        if any(k in m for k in keys):
            return cat
    return "unbekannt"


class Healer:
    QUARANTINE_AFTER = 3        # Fehlschläge pro Coin ...
    QUARANTINE_WINDOW = 3600    # ... innerhalb 1 h
    QUARANTINE_HOURS = 6

    def __init__(self, state: dict, notifier):
        self.state = state
        self.notifier = notifier
        for k, v in {"quarantine": {}, "coin_failures": {}, "error_counts": {}, "consecutive_failures": 0,
                     "backoff_until": 0.0}.items():
            state.setdefault(k, v)

    # ---------- Orders
    def execute_with_healing(self, broker, coin, sz, px, sz_dec, slippage) -> bool:
        """Führt eine Order aus; bei Fehler wird EINE passende Korrektur versucht."""
        if broker.execute(coin, sz, px, sz_dec, slippage):
            return True
        err = getattr(broker, "last_error", "") or ""
        cat, action = classify_order_error(err)
        self._count(cat)
        fix = None
        if action == "half":
            fix, args = "Größe halbiert", (coin, sz / 2, px, sz_dec, slippage)
        elif action == "wider_slippage":
            fix, args = "Slippage verdoppelt", (coin, sz, px, sz_dec, min(slippage * 2, 0.05))
        elif action == "round_coarser":
            fix, args = "gröber gerundet", (coin, sz, px, max(0, sz_dec - 1), slippage)
        elif action == "retry":
            fix, args = "erneut versucht", (coin, sz, px, sz_dec, slippage)
        elif action == "backoff":
            self.state["backoff_until"] = time.time() + 120
            fix, args = "2 min Pause (Rate-Limit)", None
        else:
            args = None
        ok = bool(args) and broker.execute(*args)
        log_event(self.state, "errors", {"t": time.time(), "coin": coin, "kategorie": cat, "fehler": err[:200],
                                         "korrektur": fix, "behoben": ok}, limit=500)
        log.warning("Order-Fehler %s (%s): %s -> %s %s", coin, cat, err[:120], fix or "übersprungen",
                    "✔" if ok else "✘")
        if ok:
            self._count("selbst_behoben")
            return True
        if action != "skip":
            self._coin_failed(coin, cat)
        return False

    def _coin_failed(self, coin, cat):
        now = time.time()
        fails = [t for t in self.state["coin_failures"].get(coin, []) if now - t < self.QUARANTINE_WINDOW] + [now]
        self.state["coin_failures"][coin] = fails
        if len(fails) >= self.QUARANTINE_AFTER:
            self.state["quarantine"][coin] = now + self.QUARANTINE_HOURS * 3600
            self.state["coin_failures"][coin] = []
            self.notifier.send(f"🩹 {coin} schlägt wiederholt fehl ({cat}) – {self.QUARANTINE_HOURS} h Quarantäne, "
                               "danach versucht der Bot es automatisch erneut.")

    def quarantined(self) -> set[str]:
        now = time.time()
        self.state["quarantine"] = {c: u for c, u in self.state["quarantine"].items() if u > now}
        return set(self.state["quarantine"])

    def in_backoff(self) -> bool:
        return time.time() < self.state.get("backoff_until", 0)

    # ---------- Durchlauf-Fehler
    def cycle_ok(self):
        self.state["consecutive_failures"] = 0

    def cycle_failed(self, exc: BaseException) -> str:
        cat = classify_exception(exc)
        self._count(cat)
        self.state["consecutive_failures"] = self.state.get("consecutive_failures", 0) + 1
        n = self.state["consecutive_failures"]
        log_event(self.state, "errors", {"t": time.time(), "kategorie": cat, "fehler": f"{type(exc).__name__}: {exc}"[:200],
                                         "korrektur": "nächster Durchlauf", "behoben": False}, limit=500)
        if cat == "rate_limit":
            self.state["backoff_until"] = time.time() + 120
        hints = {"netzwerk": "Netzwerkproblem – der Bot versucht es automatisch weiter.",
                 "datenformat": "Hyperliquid hat evtl. sein Datenformat geändert – das braucht ein Code-Update.",
                 "rate_limit": "Zu viele Anfragen – der Bot macht automatisch Pause."}
        if n in (5, 20, 100):
            self.notifier.send(f"⚠️ {n} Durchläufe hintereinander fehlgeschlagen ({cat}).\n"
                               f"{hints.get(cat, 'Unbekannter Fehler – Log prüfen.')}\nLetzter Fehler: {exc}")
        return cat

    def _count(self, cat):
        c = self.state["error_counts"]
        c[cat] = c.get(cat, 0) + 1

    def daily_summary_and_reset(self) -> str:
        c = self.state["error_counts"]
        self.state["error_counts"] = {}
        if not c:
            return "Keine Fehler 👍"
        fixed = c.pop("selbst_behoben", 0)
        parts = ", ".join(f"{k}: {v}" for k, v in sorted(c.items(), key=lambda x: -x[1]))
        return f"Fehler: {parts}" + (f" | davon selbst behoben: {fixed}" if fixed else "")
