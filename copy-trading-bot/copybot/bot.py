"""Hauptlogik des Copy-Trading-Bots."""
from __future__ import annotations

import datetime as dt
import logging
import threading
import time

from .broker import LiveBroker, PaperBroker
from .hl_api import HyperliquidData
from .healer import Healer
from .agents.team import active_overlay
from .learner import daily_learning, leader_weights, risk_throttle
from .notify import Notifier
from .selector import holding_stats, is_scalper, rank_traders
from .strategy import apply_risk, plan_orders, target_exposures
from .tuning import effective_cfg, log_event

log = logging.getLogger("copybot")


class CopyBot:
    def __init__(self, cfg: dict, data=None, broker=None, notifier=None):
        self.cfg = cfg
        self.data = data or HyperliquidData()
        if broker is not None:
            self.broker = broker
        elif cfg["mode"] == "live":
            self.broker = LiveBroker(cfg["state_file"])
        else:
            self.broker = PaperBroker(cfg["state_file"], cfg["paper_start_balance"])
        self.notifier = notifier or Notifier()
        for k, v in {"leaders": [], "last_select": 0.0, "cooldown": {}, "trader_stats": {}, "benched": {},
                     "attrib": {}, "halted": False, "last_positions": {}, "last_entries": {},
                     "weights": {}, "overrides": {}}.items():
            self.state.setdefault(k, v)
        self.healer = Healer(self.state, self.notifier)
        self.lock = threading.RLock()  # Agenten-Thread & Handels-Schleife teilen sich den Zustand

    @property
    def ecfg(self) -> dict:
        """Aktuell gültige Einstellungen (config.yaml + selbst gelernte Werte)."""
        return effective_cfg(self.cfg, self.state)

    @property
    def state(self) -> dict:
        return self.broker.state

    @property
    def leaders(self) -> list[dict]:
        return self.state["leaders"]

    @property
    def halted(self) -> bool:
        return self.state["halted"]

    # ------------------------------------------------------------------ Trader-Auswahl
    def refresh_leaders(self, force: bool = False):
        now = time.time()
        due = now - self.state["last_select"] > self.cfg["reselect_interval_hours"] * 3600
        if not (force or due or not self.leaders):
            return
        sel = self.ecfg["selection"]
        benched = {a for a, until in self.state["benched"].items() if until > now}
        rows = self.data.leaderboard()
        picked = [{"address": a.lower(), "name": "fest eingestellt", "score": 0.0, "pinned": True}
                  for a in sel.get("pinned_traders", [])]
        skipped = 0
        for c in rank_traders(rows, sel, exclude=benched):
            if len(picked) >= sel["top_n"]:
                break
            try:
                c.update(holding_stats(self.data.user_fills(c["address"])))
            except Exception as e:
                log.warning("Fills von %s nicht ladbar: %s", c["address"], e)
                continue
            if is_scalper(c, sel):
                skipped += 1
                log.info("  übersprungen (Scalper): %s  Haltedauer=%s  Fills/Tag=%.0f", c["address"],
                         _min(c["median_hold_min"]), c["fills_per_day"])
                continue
            picked.append(c)

        old = {t["address"] for t in self.leaders}
        for t in picked:
            if t["address"] not in old:
                self.state["trader_stats"][t["address"]] = {"pnl": 0.0, "since": now}
        self.state["leaders"] = picked
        self.state["last_select"] = now
        log.info("=== %d Trader ausgewählt (%d im Leaderboard, %d Scalper übersprungen) ===",
                 len(picked), len(rows), skipped)
        for t in picked:
            log.info("  %s  Konto=%s  MonatROI=%s  Haltedauer=%s", t["address"], _usd(t.get("accountValue")),
                     _pct(t.get("monthRoi")), _min(t.get("median_hold_min")))
        if {t["address"] for t in picked} != old:
            self.notifier.send("👥 Neue Trader-Auswahl:\n" + "\n".join(
                f"• {t['address'][:10]}…  Monat {_pct(t.get('monthRoi'))}  Konto {_usd(t.get('accountValue'))}"
                for t in picked))

    def _check_trader_losses(self, equity: float) -> bool:
        """Sortiert Trader aus, mit denen DU Geld verlierst."""
        sel = self.ecfg["selection"]
        if not self.leaders:
            return False
        weights = leader_weights(self.state, self.leaders)
        total_w = sum(weights.values()) or 1.0
        dropped = []
        for t in self.leaders:
            st = self.state["trader_stats"].get(t["address"])
            if t.get("pinned") or not st:
                continue
            alloc = equity * self.ecfg["copy"]["capital_usage"] * weights[t["address"]] / total_w
            if st["pnl"] < -sel["drop_trader_loss_pct"] * alloc:
                self.state["benched"][t["address"]] = time.time() + sel["bench_days"] * 86400
                dropped.append((t["address"], st["pnl"]))
        if dropped:
            msg = "\n".join(f"• {a[:10]}… ({p:+.2f} USD)" for a, p in dropped)
            log.warning("Trader aussortiert:\n%s", msg)
            self.notifier.send(f"🚫 Trader aussortiert (zu viel Verlust für dich), {sel['bench_days']} Tage gesperrt:\n{msg}")
            self.refresh_leaders(force=True)
        return bool(dropped)

    # ------------------------------------------------------------------ Gewinn je Trader
    def _attribute_pnl(self, mids):
        a = self.state["attrib"]
        for coin, sz in a.get("pos", {}).items():
            px0, px1 = a.get("px", {}).get(coin), mids.get(coin)
            if not px0 or not px1:
                continue
            pnl = sz * (px1 - px0)
            for addr, w in a.get("w", {}).get(coin, {}).items():
                self.state["trader_stats"].setdefault(addr, {"pnl": 0.0, "since": time.time()})["pnl"] += pnl * w

    def _save_attribution(self, positions, mids, contrib):
        weights = {}
        for coin, sz in positions.items():
            parts = {a: max(0.0, v * (1 if sz > 0 else -1)) for a, v in contrib.get(coin, {}).items()}
            tot = sum(parts.values())
            if tot > 0:
                weights[coin] = {a: v / tot for a, v in parts.items() if v > 0}
        self.state["attrib"] = {"pos": positions, "px": {c: mids[c] for c in positions if c in mids}, "w": weights}

    # ------------------------------------------------------------------ Ein Durchlauf
    def step(self) -> list[dict]:
        with self.lock:
            return self._step()

    def _step(self) -> list[dict]:
        if self.halted:
            log.warning("Bot ist gestoppt (Kill-Switch). Zum Fortsetzen: --reset-halt")
            return []
        if self.healer.in_backoff():
            log.info("Pause wegen Rate-Limit – nächster Durchlauf")
            return []
        self.refresh_leaders()
        mids, meta = self.data.mids(), self.data.meta()
        ecfg = self.ecfg
        risk, copy_cfg = ecfg["risk"], ecfg["copy"]
        now = time.time()
        notes = []

        # 1) Stop-Loss (Paper simuliert; Live macht das die Börse) + Gewinnzuordnung
        self.broker.check_stops(mids)
        self._attribute_pnl(mids)

        # 2) Wurde seit dem letzten Lauf etwas von der Börse geschlossen? -> Stop-Loss/Liquidation
        current = self.broker.positions()
        for coin, prev in self.state["last_positions"].items():
            cur = current.get(coin, 0.0)
            if cur == 0 or (cur > 0) != (prev > 0):
                self.state["cooldown"][coin] = {"until": now + risk["stop_cooldown_hours"] * 3600,
                                                "side": 1 if prev > 0 else -1}
                log_event(self.state, "stops", {"t": now, "coin": coin, "side": 1 if prev > 0 else -1,
                                                "px": mids.get(coin), "entry": self.state["last_entries"].get(coin),
                                                "sl_pct": risk["stop_loss_pct"]}, limit=200)
                notes.append(f"🛑 {coin} wurde per Stop-Loss geschlossen – {risk['stop_cooldown_hours']} h Pause für diesen Coin")
        self.state["cooldown"] = {c: v for c, v in self.state["cooldown"].items() if v["until"] > now}

        # 3) Kill-Switch
        equity = self.broker.equity(mids)
        peak = max(self.state.get("peak_equity") or equity, equity)
        self.state["peak_equity"] = peak
        dd = 1 - equity / peak if peak > 0 else 0
        log.info("Kontowert: %s | Höchststand: %s | Drawdown: %s", _usd(equity), _usd(peak), _pct(dd))
        if dd >= risk["max_drawdown_pct"]:
            log.critical("KILL-SWITCH: Drawdown %s – schließe alles und stoppe.", _pct(dd))
            self.broker.close_all(mids, meta, copy_cfg["slippage"])
            self.state["halted"] = True
            self.state["last_positions"] = {}
            self.broker.save()
            self.notifier.send(f"🚨 KILL-SWITCH ausgelöst!\nDrawdown {_pct(dd)} (Konto {_usd(equity)}).\n"
                               "Alle Positionen geschlossen, Bot gestoppt.")
            return []

        # 4) Verlust-Trader aussortieren
        self._check_trader_losses(equity)

        # 5) Positionen der Trader laden
        leader_states = {}
        for t in self.leaders:
            try:
                acc = self.data.account(t["address"])
            except Exception as e:
                log.warning("Konnte %s nicht laden: %s", t["address"], e)
                continue
            for coin, p in acc["positions"].items():
                p["px"] = mids.get(coin, p["entryPx"])
            leader_states[t["address"]] = acc

        # 6) Ziel berechnen -> Risiko -> Orders
        weights = leader_weights(self.state, self.leaders)
        overlay = active_overlay(self.state)
        trust = overlay["trader"] if overlay else None
        targets, contrib = target_exposures(leader_states, equity, copy_cfg, weights, trust)
        targets = {c: v for c, v in targets.items() if c in meta}
        factor = 1.0
        if ecfg.get("learning", {}).get("risk_throttle", True):
            factor = risk_throttle(dd, risk["max_drawdown_pct"])
            if factor < 1:
                log.info("Risikobremse aktiv: Positionen auf %.0f %% (Drawdown %s)", factor * 100, _pct(dd))
                targets = {c: v * factor for c, v in targets.items()}
        if overlay:  # Entscheidung des Risiko-Chefs (nur bremsen, nie verstärken)
            targets = {c: v * overlay["global"] * overlay["coins"].get(c, 1.0)
                       for c, v in targets.items() if overlay["sperren"].get(c, 0) < now}
        self.state["throttle"] = factor if ecfg.get("learning", {}).get("risk_throttle", True) else 1.0
        for coin, cd in self.state["cooldown"].items():
            if coin in targets and (targets[coin] > 0) == (cd["side"] > 0):
                targets.pop(coin)
        targets = apply_risk(targets, equity, risk)
        orders = plan_orders(targets, current, mids, copy_cfg, risk["close_on_leader_exit"])
        quarantined = self.healer.quarantined()
        orders = [o for o in orders if o["coin"] not in quarantined]

        names = {"open": "🟢 Eröffnet", "increase": "➕ Nachgekauft", "reduce": "➖ Reduziert",
                 "close": "⚪ Geschlossen", "flip": "🔄 Gedreht"}
        for o in orders:
            side = "LONG" if (current.get(o["coin"], 0) + o["sz"]) > 0 else "SHORT"
            log.info("-> %s %s: %+.6g (%s)", o["reason"].upper(), o["coin"], o["sz"], _usd(abs(o["sz"]) * o["px"]))
            if self.healer.execute_with_healing(self.broker, o["coin"], o["sz"], o["px"],
                                                meta[o["coin"]]["szDecimals"], copy_cfg["slippage"]):
                self._journal_trade(o, side, contrib, leader_states, now)
                notes.append(f"{names[o['reason']]} {o['coin']} {'' if o['reason'] == 'close' else side} "
                             f"({_usd(abs(o['sz']) * o['px'])})")

        # 7) Stop-Loss an der Börse setzen/aktualisieren
        if risk.get("stop_loss_pct"):
            try:
                self.broker.ensure_stops(risk["stop_loss_pct"], meta)
            except Exception:
                log.exception("Stop-Loss konnte nicht gesetzt werden")
                notes.append("⚠️ Stop-Loss konnte nicht gesetzt werden – bitte prüfen!")

        after = self.broker.positions()
        self.state["last_positions"] = after
        self.state["last_entries"] = {d["coin"]: d["entryPx"] for d in self.broker.position_details(mids)}
        self._save_attribution(after, mids, contrib)
        if notes and self.cfg.get("telegram", {}).get("notify_trades", True):
            self.notifier.send("\n".join(notes) + f"\nKonto: {_usd(self.broker.equity(mids))}")
        self._record_equity(now, equity)
        self._maybe_daily_report(mids)
        self.healer.cycle_ok()
        self.broker.save()
        return orders

    def _record_equity(self, now, equity):
        curve = self.state.setdefault("equity_curve", [])
        if not curve or now - curve[-1][0] >= 600:  # alle 10 min ein Punkt
            curve.append([int(now), round(equity, 2)])
            del curve[:-3000]

    def _journal_trade(self, o, side, contrib, leader_states, now):
        """Tagebuch + Messung der Verzögerungs-Kosten: Wie viel schlechter steige ich ein als der Trader?"""
        coin, lag = o["coin"], None
        if o["reason"] in ("open", "increase", "flip"):
            sgn = 1 if side == "LONG" else -1
            lags = {}
            for addr, usd in contrib.get(coin, {}).items():
                lp = leader_states.get(addr, {}).get("positions", {}).get(coin)
                if lp and lp.get("entryPx") and (usd > 0) == (sgn > 0):
                    lags[addr] = sgn * (o["px"] - lp["entryPx"]) / lp["entryPx"]
            for addr, lg in lags.items():
                st = self.state["trader_stats"].setdefault(addr, {"pnl": 0.0, "since": now})
                st["lag_sum"] = st.get("lag_sum", 0.0) + lg
                st["lag_n"] = st.get("lag_n", 0) + 1
            if lags:
                lag = sum(lags.values()) / len(lags)
        log_event(self.state, "trades", {"t": now, "coin": coin, "reason": o["reason"], "side": side,
                                         "usd": round(abs(o["sz"]) * o["px"], 2), "px": o["px"],
                                         "lag": None if lag is None else round(lag, 5)}, limit=1000)

    # ------------------------------------------------------------------ Berichte
    def report_text(self, mids=None) -> str:
        mids = mids or self.data.mids()
        eq = self.broker.equity(mids)
        prev = self.state.get("equity_at_report")
        start = self.cfg["paper_start_balance"] if self.cfg["mode"] == "paper" else self.state.get("start_equity")
        lines = [f"📊 Tagesbericht ({self.cfg['mode'].upper()})", f"Konto: {_usd(eq)}"]
        if prev:
            lines.append(f"Seit gestern: {eq - prev:+.2f} USD ({(eq / prev - 1) * 100:+.1f} %)")
        if start:
            lines.append(f"Seit Start: {eq - start:+.2f} USD ({(eq / start - 1) * 100:+.1f} %)")
        peak = self.state.get("peak_equity") or eq
        lines.append(f"Abstand zum Höchststand: {_pct(1 - eq / peak if peak else 0)}")
        lines.append("\nPositionen:")
        details = self.broker.position_details(mids)
        lines += [f"• {d['coin']} {'LONG' if d['szi'] > 0 else 'SHORT'} {_usd(d['value'])}  ({d['upnl']:+.2f} USD)"
                  for d in details] or ["• keine"]
        lines.append("\nGewinn je Trader (für dich):")
        for t in self.leaders:
            st = self.state["trader_stats"].get(t["address"], {})
            lines.append(f"• {t['address'][:10]}…  {st.get('pnl', 0):+.2f} USD  "
                         f"(Gewicht {self.state['weights'].get(t['address'], 1.0):.2f})")
        if self.state.get("overrides"):
            lines.append("\nSelbst gelernte Einstellungen:")
            lines += [f"• {k} = {v}" for k, v in self.state["overrides"].items()]
        if self.halted:
            lines.append("\n🚨 Bot ist gestoppt (Kill-Switch).")
        return "\n".join(lines)

    def _maybe_daily_report(self, mids):
        now = dt.datetime.now(dt.timezone.utc)
        today = now.date().isoformat()
        hour = self.cfg.get("telegram", {}).get("daily_report_hour_utc", 18)
        self.state.setdefault("start_equity", self.broker.equity(mids))
        if self.state.get("last_report") == today or now.hour < hour:
            return
        equity = self.broker.equity(mids)
        learn_notes = daily_learning(self, mids, equity)
        errors = self.healer.daily_summary_and_reset()
        log_event(self.state, "days", {"t": time.time(), "datum": today, "equity": round(equity, 2),
                                       "peak": round(self.state.get("peak_equity", equity), 2)}, limit=400)
        text = self.report_text(mids) + "\n\n🧠 Selbst-Analyse:\n" + "\n".join(
            [f"• {n}" for n in learn_notes] or ["• heute nichts angepasst (zu wenig Daten oder alles im Rahmen)"]
        ) + f"\n• {errors}"
        self.notifier.send(text)
        self.state["last_report"] = today
        self.state["equity_at_report"] = equity

    def reset_halt(self):
        mids = self.data.mids()
        self.state["halted"] = False
        self.state["peak_equity"] = self.broker.equity(mids)
        self.broker.save()
        log.info("Kill-Switch zurückgesetzt. Neuer Höchststand: %s", _usd(self.state["peak_equity"]))

    # ------------------------------------------------------------------ Dauerbetrieb
    def run(self):
        log.info("Starte Copy-Bot im Modus: %s", self.cfg["mode"].upper())
        self.notifier.send(f"▶️ Copy-Bot gestartet ({self.cfg['mode'].upper()})")
        wake = threading.Event()
        watcher = None
        if self.cfg.get("use_websocket", True):
            try:
                from .ws import LeaderWatcher
                import websocket  # noqa: F401
                watcher = LeaderWatcher(lambda: [t["address"] for t in self.leaders], lambda u: wake.set())
            except ImportError:
                log.warning("websocket-client fehlt – nur Polling")
        dcfg = self.cfg.get("dashboard", {})
        if dcfg.get("enabled", True):
            from .dashboard import start_server
            try:
                start_server(self, dcfg.get("port", 8080))
            except OSError as e:
                log.warning("Dashboard konnte nicht starten: %s", e)
        self._start_agent_thread()
        subscribed = None
        while not self.halted:
            try:
                self.step()
            except KeyboardInterrupt:
                raise
            except Exception as e:
                log.exception("Fehler im Durchlauf – nächster Versuch gleich")
                self.healer.cycle_failed(e)
                self.broker.save()
            current = {t["address"] for t in self.leaders}
            if watcher and current != subscribed:
                if subscribed is None:
                    watcher.start()
                else:
                    watcher.resubscribe()
                subscribed = current
            if wake.wait(self.cfg["poll_interval_sec"]):
                time.sleep(1.5)  # weitere Fills abwarten (Teil-Ausführungen)
                wake.clear()
                log.info("Trader-Aktivität erkannt – prüfe sofort")
        if watcher:
            watcher.stop()


    def run_agents(self, client=None) -> str:
        from .agents.team import run_team
        text = run_team(self, client=client, lock=self.lock)
        log.info(text)
        self.notifier.send(text)
        with self.lock:
            self.broker.save()
        return text

    def _start_agent_thread(self):
        acfg = self.cfg.get("agents", {})
        if not acfg.get("enabled", True):
            return

        def loop():
            while not self.halted:
                last = (self.state.get("agents") or {}).get("t", 0)
                wait = last + acfg.get("interval_hours", 8) * 3600 - time.time()
                if wait <= 0:
                    try:
                        self.run_agents()
                    except Exception:
                        log.exception("Agenten-Team fehlgeschlagen")
                        self.state.setdefault("agents", {})["t"] = time.time()  # nicht sofort erneut
                    continue
                time.sleep(min(wait, 600))

        threading.Thread(target=loop, daemon=True, name="agents").start()


def _usd(v):
    return "-" if v is None else f"${v:,.2f}"


def _pct(v):
    return "-" if v is None else f"{v * 100:.1f}%"


def _min(v):
    return "-" if v is None else (f"{v / 60:.1f} h" if v >= 60 else f"{v:.0f} min")
