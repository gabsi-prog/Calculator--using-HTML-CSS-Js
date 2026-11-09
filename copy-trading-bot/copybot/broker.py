"""Ausführung: PaperBroker (Simulation) und LiveBroker (echte Orders via Hyperliquid-SDK)."""
from __future__ import annotations

import json
import logging
import os

log = logging.getLogger(__name__)

TAKER_FEE = 0.00045  # Hyperliquid Basis-Taker-Gebühr


class PaperBroker:
    """Simuliert ein Perp-Konto: Cash + Positionen, realisierte PnL, Gebühren."""

    def __init__(self, state_file: str, start_balance: float):
        self.state_file = state_file
        self.state = {"cash": start_balance, "positions": {}, "peak_equity": start_balance, "trades": 0}
        if os.path.exists(state_file):
            with open(state_file) as f:
                self.state.update(json.load(f))
            log.info("Paper-Zustand geladen: %s", state_file)

    def save(self):
        with open(self.state_file, "w") as f:
            json.dump(self.state, f, indent=2)

    def positions(self) -> dict[str, float]:
        return {c: p["szi"] for c, p in self.state["positions"].items()}

    def equity(self, mids: dict[str, float]) -> float:
        upnl = sum(
            p["szi"] * (mids.get(c, p["entryPx"]) - p["entryPx"]) for c, p in self.state["positions"].items()
        )
        return self.state["cash"] + upnl

    def execute(self, coin: str, sz: float, px: float, sz_decimals: int, slippage: float) -> bool:
        sz = round(sz, sz_decimals)
        if sz == 0:
            return False
        fill = px * (1 + slippage / 4 if sz > 0 else 1 - slippage / 4)  # angenommene Ausführung
        fee = abs(sz) * fill * TAKER_FEE
        pos = self.state["positions"].get(coin, {"szi": 0.0, "entryPx": fill})
        cur = pos["szi"]
        new = round(cur + sz, 10)
        realized = 0.0
        if cur != 0 and (cur > 0) != (sz > 0):  # (teilweise) schließen
            closed = min(abs(sz), abs(cur))
            realized = closed * (fill - pos["entryPx"]) * (1 if cur > 0 else -1)
        if new == 0:
            self.state["positions"].pop(coin, None)
        else:
            if cur == 0 or (cur > 0) != (new > 0):
                entry = fill  # neu eröffnet oder gedreht
            elif abs(new) > abs(cur):
                entry = (pos["entryPx"] * abs(cur) + fill * abs(sz)) / abs(new)
            else:
                entry = pos["entryPx"]
            self.state["positions"][coin] = {"szi": new, "entryPx": entry}
        self.state["cash"] += realized - fee
        self.state["trades"] += 1
        log.info("[PAPER] %s %s %.6g @ %.6g  (Gebühr %.2f, realisiert %.2f)",
                 "KAUF" if sz > 0 else "VERKAUF", coin, abs(sz), fill, fee, realized)
        return True

    def close_all(self, mids, meta, slippage):
        for coin, szi in list(self.positions().items()):
            self.execute(coin, -szi, mids[coin], meta.get(coin, {}).get("szDecimals", 4), slippage)


class LiveBroker:
    """Echte Orders. Benötigt: pip install hyperliquid-python-sdk eth-account"""

    def __init__(self, state_file: str):
        from eth_account import Account
        from hyperliquid.exchange import Exchange
        from hyperliquid.info import Info
        from hyperliquid.utils import constants

        key = os.environ.get("HL_PRIVATE_KEY")
        self.address = os.environ.get("HL_ACCOUNT_ADDRESS")
        if not key or not self.address:
            raise SystemExit("Für mode: live müssen HL_PRIVATE_KEY und HL_ACCOUNT_ADDRESS gesetzt sein (.env).")
        wallet = Account.from_key(key)
        self.info = Info(constants.MAINNET_API_URL, skip_ws=True)
        self.ex = Exchange(wallet, constants.MAINNET_API_URL, account_address=self.address)
        self.state_file = state_file
        self.state = {"peak_equity": 0.0, "trades": 0}
        if os.path.exists(state_file):
            with open(state_file) as f:
                self.state.update(json.load(f))
        self._cache = None

    def save(self):
        with open(self.state_file, "w") as f:
            json.dump(self.state, f, indent=2)

    def _st(self):
        self._cache = self.info.user_state(self.address)
        return self._cache

    def positions(self) -> dict[str, float]:
        return {
            ap["position"]["coin"]: float(ap["position"]["szi"])
            for ap in self._st().get("assetPositions", [])
            if float(ap["position"]["szi"]) != 0
        }

    def equity(self, mids) -> float:
        return float(self._st()["marginSummary"]["accountValue"])

    def execute(self, coin: str, sz: float, px: float, sz_decimals: int, slippage: float) -> bool:
        sz = round(sz, sz_decimals)
        if sz == 0:
            return False
        res = self.ex.market_open(coin, sz > 0, abs(sz), None, slippage)
        ok = res.get("status") == "ok" and not any(
            "error" in s for s in res.get("response", {}).get("data", {}).get("statuses", [])
        )
        if ok:
            self.state["trades"] += 1
            log.info("[LIVE] %s %s %s -> %s", "KAUF" if sz > 0 else "VERKAUF", coin, abs(sz), res)
        else:
            log.error("[LIVE] Order fehlgeschlagen %s %s: %s", coin, sz, res)
        return ok

    def close_all(self, mids, meta, slippage):
        for coin in self.positions():
            log.warning("[LIVE] Schließe %s", coin)
            self.ex.market_close(coin, slippage=slippage)
