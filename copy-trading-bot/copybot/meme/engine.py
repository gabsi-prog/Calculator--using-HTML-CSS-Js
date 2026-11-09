"""Memecoin-Copy-Trading: beobachtet Wallets, kopiert Käufe nach Sicherheits-Checks, steigt nach Regeln aus."""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
import threading
import time

from .broker import ImpactTooHigh, LiveMemeBroker, PaperMemeBroker
from .chain import MarketData, SolanaRPC
from .parse import parse_swap
from .safety import check_token

log = logging.getLogger("copybot.meme")


def short(a: str) -> str:
    return f"{a[:4]}…{a[-4:]}" if a else "?"


class MemeEngine:
    def __init__(self, cfg: dict, notifier, market=None, rpc=None, broker=None, overlay_fn=None,
                 state_file: str | None = None):
        self.cfg, self.c, self.notifier = cfg, cfg["meme"], notifier
        self.market = market or MarketData(self.c.get("jupiter_api", "https://lite-api.jup.ag"))
        self.rpc = rpc or SolanaRPC(self.c["rpc_url"])
        self.state_file = state_file or f"state-meme-{cfg['mode']}.json"
        self.ms = {"sol": float(self.c["paper_start_sol"]), "start_sol": float(self.c["paper_start_sol"]),
                   "positions": {}, "last_sig": {}, "leaders": {}, "benched": {}, "blocked": {},
                   "day": {}, "events": [], "closed": []}
        if os.path.exists(self.state_file):
            with open(self.state_file) as f:
                self.ms.update(json.load(f))
        self.overlay_fn = overlay_fn or (lambda: None)
        self.lock = threading.RLock()
        if broker is not None:
            self.broker = broker
        elif cfg["mode"] == "live":
            self.broker = LiveMemeBroker(self.ms, self.market, self.rpc, self.c["slippage_bps"])
        else:
            self.broker = PaperMemeBroker(self.ms, self.market, self.c["slippage_bps"])
        self._sol_usd = (0.0, 0.0)

    # ------------------------------------------------------------------ Hilfen
    def save(self):
        with self.lock:
            tmp = self.state_file + ".tmp"
            with open(tmp, "w") as f:
                json.dump(self.ms, f)
            os.replace(tmp, self.state_file)

    def sol_usd(self) -> float:
        if time.time() - self._sol_usd[0] > 60:
            try:
                self._sol_usd = (time.time(), self.market.sol_usd())
            except Exception as e:
                log.warning("SOL-Preis nicht verfügbar: %s", e)
        return self._sol_usd[1]

    def _event(self, kind: str, **kw):
        self.ms["events"].append({"t": time.time(), "kind": kind, **kw})
        del self.ms["events"][:-400]

    def _day(self) -> dict:
        today = dt.datetime.now(dt.timezone.utc).date().isoformat()
        if self.ms["day"].get("date") != today:
            self.ms["day"] = {"date": today, "pnl_sol": 0.0, "buys": 0}
        return self.ms["day"]

    def _leader(self, w: str) -> dict:
        return self.ms["leaders"].setdefault(w, {"pnl_sol": 0.0, "trades": 0, "wins": 0, "copied": 0, "skipped": 0})

    def _agent_factor(self) -> float:
        ov = self.overlay_fn()
        return 1.0 if not ov else float(ov.get("meme", 1.0))

    # ------------------------------------------------------------------ Hauptschleife
    def tick(self):
        with self.lock:
            self._day()
            now = time.time()
            self.ms["blocked"] = {m: u for m, u in self.ms["blocked"].items() if u > now}
            for w in self.c.get("wallets") or []:
                try:
                    self._poll_wallet(w)
                except Exception as e:
                    log.warning("Wallet %s nicht lesbar: %s", short(w), e)
            try:
                self._manage_exits()
            except Exception as e:
                log.warning("Ausstiegs-Prüfung fehlgeschlagen: %s", e)
            self.save()

    def _poll_wallet(self, w: str):
        last = self.ms["last_sig"].get(w)
        sigs = self.rpc.signatures(w, until=last, limit=15)
        if not sigs:
            return
        self.ms["last_sig"][w] = sigs[0]["signature"]
        if last is None:
            log.info("Beobachte Wallet %s (alte Trades werden nicht kopiert)", short(w))
            return
        for s in reversed(sigs):
            if s.get("err"):
                continue
            ev = parse_swap(self.rpc.transaction(s["signature"]), w, self.sol_usd())
            if ev:
                self.on_event(w, ev)

    def on_event(self, w: str, ev: dict):
        log.info("Wallet %s: %s %s für %.3f SOL", short(w), ev["side"], short(ev["mint"]), ev["quote_sol"])
        if ev["side"] == "buy":
            self._copy_buy(w, ev)
        elif self.c.get("follow_leader_sells", True):
            self._copy_sell(w, ev)

    # ------------------------------------------------------------------ Kaufen
    def _buy_blocker(self, w: str, ev: dict) -> str | None:
        c, day, now = self.c, self._day(), time.time()
        if self.ms["benched"].get(w, 0) > now:
            return "Wallet ist gesperrt (hat dir zu viel verloren)"
        if self._agent_factor() <= 0:
            return "KI-Risiko-Chef hat Memecoin-Käufe pausiert"
        if ev["mint"] in self.ms["positions"]:
            return "Token schon im Bestand"
        if ev["mint"] in self.ms["blocked"]:
            return "Token kürzlich als unsicher eingestuft"
        if ev.get("time") and now - ev["time"] > c["max_signal_age_sec"]:
            return f"Signal zu alt ({now - ev['time']:.0f} s) – nicht hinterherlaufen"
        if ev["quote_sol"] < c["min_leader_buy_sol"]:
            return f"Kauf des Traders zu klein ({ev['quote_sol']:.2f} SOL)"
        if len(self.ms["positions"]) >= c["max_open_positions"]:
            return "maximale Anzahl offener Positionen erreicht"
        if day["buys"] >= c["max_buys_per_day"]:
            return "Tageslimit für Käufe erreicht"
        if day["pnl_sol"] <= -c["daily_loss_limit_sol"]:
            return "Tages-Verlustlimit erreicht – Pause bis morgen"
        return None

    def _copy_buy(self, w: str, ev: dict):
        L = self._leader(w)
        reason = self._buy_blocker(w, ev)
        ok, reasons, info = (False, [reason], {}) if reason else check_token(
            ev["mint"], self.market, self.rpc, self.c, ev["price_sol"])
        symbol = info.get("symbol") or short(ev["mint"])
        if not ok:
            L["skipped"] += 1
            if not reason:  # Token unsicher -> 10 min nicht erneut prüfen
                self.ms["blocked"][ev["mint"]] = time.time() + 600
            self._event("skip", wallet=w, mint=ev["mint"], symbol=symbol, reasons=reasons)
            log.info("Nicht kopiert %s: %s", symbol, "; ".join(reasons))
            return
        size = round(self.c["sol_per_trade"] * min(1.0, self._agent_factor()), 4)
        decimals = info.get("decimals") if info.get("decimals") is not None else ev["decimals"]
        try:
            fill = self.broker.buy(ev["mint"], size, decimals, self.c["max_price_impact_pct"])
        except ImpactTooHigh as e:
            self._event("skip", wallet=w, mint=ev["mint"], symbol=symbol, reasons=[str(e)])
            return
        except Exception as e:
            self._event("error", wallet=w, mint=ev["mint"], symbol=symbol, text=f"Kauf fehlgeschlagen: {e}")
            log.warning("Kauf %s fehlgeschlagen: %s", symbol, e)
            return
        if fill["tokens"] <= 0:
            return
        price = fill["sol"] / fill["tokens"]
        self.ms["positions"][ev["mint"]] = {
            "mint": ev["mint"], "symbol": symbol, "decimals": decimals, "tokens": fill["tokens"],
            "cost_sol": fill["sol"], "entry_price_sol": price, "high_price_sol": price, "last_price_sol": price,
            "opened": time.time(), "leader": w, "tp_done": False, "realized_sol": 0.0, "sell_fails": 0,
            "leader_price_sol": ev["price_sol"]}
        self._day()["buys"] += 1
        L["copied"] += 1
        lag = price / ev["price_sol"] - 1 if ev["price_sol"] else None
        self._event("buy", wallet=w, mint=ev["mint"], symbol=symbol, sol=fill["sol"], lag=lag, sig=fill["sig"])
        self.notifier.send(f"🟢 Memecoin gekauft: {symbol}\n{fill['sol']:.3f} SOL · kopiert von {short(w)}"
                           + (f"\nEinstieg {lag * 100:+.1f} % vs. Trader" if lag is not None else "")
                           + (f"\n{info['url']}" if info.get("url") else ""))

    # ------------------------------------------------------------------ Verkaufen
    def _copy_sell(self, w: str, ev: dict):
        pos = self.ms["positions"].get(ev["mint"])
        if not pos or pos["leader"] != w:
            return
        frac = ev["tokens"] / ev["pre_tokens"] if ev["pre_tokens"] > 0 else 1.0
        self._sell(ev["mint"], 1.0 if frac > 0.9 else frac, f"Trader hat {min(frac, 1) * 100:.0f} % verkauft")

    def _sell(self, mint: str, frac: float, reason: str):
        pos = self.ms["positions"][mint]
        tokens = pos["tokens"] * frac
        try:
            fill = self.broker.sell(mint, tokens, pos["decimals"])
        except Exception as e:
            pos["sell_fails"] += 1
            log.warning("Verkauf %s fehlgeschlagen (%d.): %s", pos["symbol"], pos["sell_fails"], e)
            if pos["sell_fails"] == 5:
                self.notifier.send(f"⚠️ {pos['symbol']} lässt sich nicht verkaufen (evtl. Honeypot/keine Liquidität). "
                                   "Der Bot versucht es weiter.")
                self._event("error", mint=mint, symbol=pos["symbol"], text=f"Verkauf scheitert: {e}")
            return
        cost = pos["cost_sol"] * frac
        pnl = fill["sol"] - cost
        pos["tokens"] -= tokens
        pos["cost_sol"] -= cost
        pos["realized_sol"] += pnl
        self._day()["pnl_sol"] += pnl
        L = self._leader(pos["leader"])
        L["pnl_sol"] += pnl
        done = frac >= 0.999 or pos["tokens"] * pos.get("last_price_sol", 0) < 0.001
        pct = fill["sol"] / cost - 1 if cost else 0
        self._event("sell", wallet=pos["leader"], mint=mint, symbol=pos["symbol"], sol=fill["sol"], pnl_sol=pnl,
                    pct=pct, reason=reason, sig=fill["sig"])
        self.notifier.send(f"{'🟢' if pnl >= 0 else '🔴'} {pos['symbol']} {'verkauft' if done else f'{frac * 100:.0f} % verkauft'}"
                           f" ({reason})\n{pnl:+.4f} SOL ({pct * 100:+.0f} %)")
        if done:
            total = pos["realized_sol"]
            L["trades"] += 1
            L["wins"] += total > 0
            self.ms["closed"].append({"t": time.time(), "symbol": pos["symbol"], "mint": mint, "leader": pos["leader"],
                                      "pnl_sol": total, "held_h": (time.time() - pos["opened"]) / 3600})
            del self.ms["closed"][:-200]
            del self.ms["positions"][mint]
        self._check_bench(pos["leader"])

    def _check_bench(self, w: str):
        if self._leader(w)["pnl_sol"] <= -self.c["drop_leader_loss_sol"] and self.ms["benched"].get(w, 0) < time.time():
            self.ms["benched"][w] = time.time() + self.c["bench_days"] * 86400
            self._leader(w)["pnl_sol"] = 0.0  # nach der Pause neu bewerten
            self.notifier.send(f"🚫 Wallet {short(w)} hat dir zu viel verloren – {self.c['bench_days']} Tage nicht kopieren.")

    def _manage_exits(self):
        if not self.ms["positions"]:
            return
        sol_usd = self.sol_usd()
        prices = {}
        try:
            usd = self.market.prices_usd(list(self.ms["positions"]))
            prices = {m: p / sol_usd for m, p in usd.items() if sol_usd}
        except Exception as e:
            log.debug("Jupiter-Preise fehlen: %s", e)
        c, now = self.c, time.time()
        for mint, pos in list(self.ms["positions"].items()):
            price = prices.get(mint)
            if not price:
                try:
                    price = (self.market.token_info(mint) or {}).get("price_sol")
                except Exception:
                    price = None
            if not price:
                continue
            pos["last_price_sol"] = price
            pos["high_price_sol"] = max(pos["high_price_sol"], price)
            pnl = price / pos["entry_price_sol"] - 1
            if pnl <= -c["stop_loss_pct"]:
                self._sell(mint, 1.0, f"Stop-Loss {pnl * 100:.0f} %")
            elif not pos["tp_done"] and pnl >= c["take_profit_pct"]:
                pos["tp_done"] = True
                self._sell(mint, 0.5, f"Take-Profit +{pnl * 100:.0f} % – Einsatz gesichert")
            elif pos["tp_done"] and price <= pos["high_price_sol"] * (1 - c["trailing_stop_pct"]):
                self._sell(mint, 1.0, "Trailing-Stop")
            elif now - pos["opened"] > c["max_hold_hours"] * 3600:
                self._sell(mint, 1.0, "Zeitlimit erreicht")

    # ------------------------------------------------------------------ Übersicht
    def summary(self) -> dict:
        with self.lock:
            positions = [{**p, "value_sol": p["tokens"] * p.get("last_price_sol", 0),
                          "pnl_pct": p.get("last_price_sol", 0) / p["entry_price_sol"] - 1 if p["entry_price_sol"] else 0}
                         for p in self.ms["positions"].values()]
            try:
                bal = self.broker.balance_sol()
            except Exception:
                bal = self.ms.get("sol", 0)
            return {"aktiv": True, "sol": bal, "start_sol": self.ms.get("start_sol"),
                    "wert_sol": bal + sum(p["value_sol"] for p in positions), "sol_usd": self._sol_usd[1],
                    "positionen": positions, "wallets": [{"adresse": w, **self._leader(w),
                                                          "gesperrt": self.ms["benched"].get(w, 0) > time.time()}
                                                         for w in self.c.get("wallets") or []],
                    "tag": self._day(), "ereignisse": self.ms["events"][-80:], "geschlossen": self.ms["closed"][-50:]}

    def run_forever(self, stop=lambda: False):
        log.info("Memecoin-Bot startet (%s) – beobachte %d Wallets", self.cfg["mode"].upper(), len(self.c.get("wallets") or []))
        while not stop():
            t0 = time.time()
            try:
                self.tick()
            except Exception:
                log.exception("Memecoin-Durchlauf fehlgeschlagen")
            time.sleep(max(0.5, self.c["poll_sec"] - (time.time() - t0)))
