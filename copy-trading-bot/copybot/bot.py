"""Hauptschleife des Copy-Trading-Bots."""
from __future__ import annotations

import logging
import time

from .broker import LiveBroker, PaperBroker
from .hl_api import HyperliquidData
from .selector import select_traders
from .strategy import apply_risk, plan_orders, target_exposures

log = logging.getLogger("copybot")


class CopyBot:
    def __init__(self, cfg: dict, data: HyperliquidData | None = None, broker=None):
        self.cfg = cfg
        self.data = data or HyperliquidData()
        if broker is not None:
            self.broker = broker
        elif cfg["mode"] == "live":
            self.broker = LiveBroker(cfg["state_file"])
        else:
            self.broker = PaperBroker(cfg["state_file"], cfg["paper_start_balance"])
        self.leaders: list[dict] = []
        self.last_select = 0.0
        self.halted = False

    def refresh_leaders(self, force: bool = False):
        due = time.time() - self.last_select > self.cfg["reselect_interval_hours"] * 3600
        if not (force or due or not self.leaders):
            return
        rows = self.data.leaderboard()
        self.leaders = select_traders(rows, self.cfg["selection"])
        self.last_select = time.time()
        log.info("=== %d Trader ausgewählt (aus %d im Leaderboard) ===", len(self.leaders), len(rows))
        for t in self.leaders:
            log.info("  %s  Konto=%s  MonatROI=%s  Score=%.2f", t["address"], _usd(t.get("accountValue")),
                     _pct(t.get("monthRoi")), t["score"])

    def step(self):
        self.refresh_leaders()
        mids = self.data.mids()
        meta = self.data.meta()
        risk, copy_cfg = self.cfg["risk"], self.cfg["copy"]

        equity = self.broker.equity(mids)
        peak = max(self.broker.state.get("peak_equity", 0) or equity, equity)
        self.broker.state["peak_equity"] = peak
        dd = 1 - equity / peak if peak > 0 else 0
        log.info("Kontowert: %s | Höchststand: %s | Drawdown: %s", _usd(equity), _usd(peak), _pct(dd))
        if dd >= risk["max_drawdown_pct"]:
            log.critical("KILL-SWITCH: Drawdown %s >= %s – schließe alles und stoppe.", _pct(dd),
                         _pct(risk["max_drawdown_pct"]))
            self.broker.close_all(mids, meta, copy_cfg["slippage"])
            self.broker.save()
            self.halted = True
            return []

        leader_states = {}
        for t in self.leaders:
            try:
                acc = self.data.account(t["address"])
            except Exception as e:  # ein Trader-Ausfall soll den Bot nicht stoppen
                log.warning("Konnte %s nicht laden: %s", t["address"], e)
                continue
            for coin, p in acc["positions"].items():
                p["px"] = mids.get(coin, p["entryPx"])
            leader_states[t["address"]] = acc

        targets = target_exposures(leader_states, equity, copy_cfg)
        targets = {c: v for c, v in targets.items() if c in meta}
        targets = apply_risk(targets, equity, risk)
        orders = plan_orders(targets, self.broker.positions(), mids, copy_cfg, risk["close_on_leader_exit"])

        for o in orders:
            log.info("-> %s %s: %+.6g (%s)", o["reason"].upper(), o["coin"], o["sz"], _usd(abs(o["sz"]) * o["px"]))
            self.broker.execute(o["coin"], o["sz"], o["px"], meta[o["coin"]]["szDecimals"], copy_cfg["slippage"])
        self.broker.save()
        return orders

    def run(self):
        log.info("Starte Copy-Bot im Modus: %s", self.cfg["mode"].upper())
        while not self.halted:
            try:
                self.step()
            except KeyboardInterrupt:
                raise
            except Exception:
                log.exception("Fehler im Zyklus – versuche es im nächsten Durchlauf erneut")
            time.sleep(self.cfg["poll_interval_sec"])


def _usd(v):
    return "-" if v is None else f"${v:,.2f}"


def _pct(v):
    return "-" if v is None else f"{v * 100:.1f}%"
