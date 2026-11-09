"""Ausführung: PaperBroker (Simulation) und LiveBroker (echte Orders via Hyperliquid-SDK)."""
from __future__ import annotations

import json
import logging
import os

from .hl_api import round_px

log = logging.getLogger(__name__)

TAKER_FEE = 0.00045  # Hyperliquid Basis-Taker-Gebühr


def apply_fill(positions: dict, coin: str, sz: float, px: float) -> float:
    """Bucht einen Fill auf ein Positions-Dict {coin: {szi, entryPx}}. Gibt realisierte PnL zurück."""
    pos = positions.get(coin, {"szi": 0.0, "entryPx": px})
    cur = pos["szi"]
    new = round(cur + sz, 10)
    realized = 0.0
    if cur != 0 and (cur > 0) != (sz > 0):
        closed = min(abs(sz), abs(cur))
        realized = closed * (px - pos["entryPx"]) * (1 if cur > 0 else -1)
    if new == 0:
        positions.pop(coin, None)
    else:
        if cur == 0 or (cur > 0) != (new > 0):
            entry = px
        elif abs(new) > abs(cur):
            entry = (pos["entryPx"] * abs(cur) + px * abs(sz)) / abs(new)
        else:
            entry = pos["entryPx"]
        positions[coin] = {**pos, "szi": new, "entryPx": entry}
    return realized


def _load(path: str, default: dict) -> dict:
    if os.path.exists(path):
        with open(path) as f:
            default.update(json.load(f))
        log.info("Zustand geladen: %s", path)
    return default


class PaperBroker:
    """Simuliert ein Perp-Konto: Cash + Positionen, realisierte PnL, Gebühren, Stop-Loss."""

    def __init__(self, state_file: str, start_balance: float):
        self.state_file = state_file
        self.state = _load(state_file, {"cash": start_balance, "positions": {}, "peak_equity": start_balance,
                                         "trades": 0})

    def save(self):
        with open(self.state_file, "w") as f:
            json.dump(self.state, f, indent=2)

    def positions(self) -> dict[str, float]:
        return {c: p["szi"] for c, p in self.state["positions"].items()}

    def position_details(self, mids) -> list[dict]:
        out = []
        for c, p in self.state["positions"].items():
            px = mids.get(c, p["entryPx"])
            out.append({"coin": c, "szi": p["szi"], "entryPx": p["entryPx"], "value": abs(p["szi"]) * px,
                        "upnl": p["szi"] * (px - p["entryPx"]), "sl": p.get("sl")})
        return out

    def equity(self, mids: dict[str, float]) -> float:
        return self.state["cash"] + sum(d["upnl"] for d in self.position_details(mids))

    def execute(self, coin, sz, px, sz_decimals=None, slippage=0.0) -> bool:
        if sz_decimals is not None:
            sz = round(sz, sz_decimals)
        if sz == 0:
            return False
        fill = px * (1 + slippage / 4 if sz > 0 else 1 - slippage / 4)
        fee = abs(sz) * fill * TAKER_FEE
        realized = apply_fill(self.state["positions"], coin, sz, fill)
        self.state["cash"] += realized - fee
        self.state["trades"] += 1
        log.info("[PAPER] %s %s %.6g @ %.6g  (Gebühr %.2f, realisiert %.2f)",
                 "KAUF" if sz > 0 else "VERKAUF", coin, abs(sz), fill, fee, realized)
        return True

    def ensure_stops(self, sl_pct: float, meta: dict):
        for p in self.state["positions"].values():
            p["sl"] = p["entryPx"] * (1 - sl_pct if p["szi"] > 0 else 1 + sl_pct)

    def check_stops(self, mids) -> list[str]:
        """Simuliert die Stop-Loss-Orders der Börse."""
        hit = []
        for coin, p in list(self.state["positions"].items()):
            sl, m = p.get("sl"), mids.get(coin)
            if sl and m and ((p["szi"] > 0 and m <= sl) or (p["szi"] < 0 and m >= sl)):
                log.warning("[PAPER] Stop-Loss %s ausgelöst bei %.6g", coin, m)
                self.execute(coin, -p["szi"], m)
                hit.append(coin)
        return hit

    def close_all(self, mids, meta, slippage):
        for coin, szi in list(self.positions().items()):
            self.execute(coin, -szi, mids[coin], None, slippage)


class LiveBroker:
    """Echte Orders. Benötigt: pip install hyperliquid-python-sdk eth-account"""

    def __init__(self, state_file: str):
        from eth_account import Account
        from hyperliquid.exchange import Exchange
        from hyperliquid.info import Info
        from hyperliquid.utils import constants

        key = os.environ.get("HL_PRIVATE_KEY", "").strip()
        self.address = os.environ.get("HL_ACCOUNT_ADDRESS", "").strip()
        if not key or not self.address:
            raise SystemExit("Für mode: live müssen HL_PRIVATE_KEY und HL_ACCOUNT_ADDRESS gesetzt sein.")
        self.info = Info(constants.MAINNET_API_URL, skip_ws=True)
        self.ex = Exchange(Account.from_key(key), constants.MAINNET_API_URL, account_address=self.address)
        self.state_file = state_file
        self.state = _load(state_file, {"peak_equity": 0.0, "trades": 0})

    def save(self):
        with open(self.state_file, "w") as f:
            json.dump(self.state, f, indent=2)

    def _raw_positions(self) -> list[dict]:
        self._us = self.info.user_state(self.address)
        return [ap["position"] for ap in self._us.get("assetPositions", []) if float(ap["position"]["szi"]) != 0]

    def positions(self) -> dict[str, float]:
        return {p["coin"]: float(p["szi"]) for p in self._raw_positions()}

    def position_details(self, mids) -> list[dict]:
        return [{"coin": p["coin"], "szi": float(p["szi"]), "entryPx": float(p["entryPx"]),
                 "value": float(p["positionValue"]), "upnl": float(p["unrealizedPnl"]), "sl": None}
                for p in self._raw_positions()]

    def equity(self, mids) -> float:
        return float(self.info.user_state(self.address)["marginSummary"]["accountValue"])

    def execute(self, coin, sz, px, sz_decimals=None, slippage=0.01) -> bool:
        if sz_decimals is not None:
            sz = round(sz, sz_decimals)
        if sz == 0:
            return False
        res = self.ex.market_open(coin, sz > 0, abs(sz), None, slippage)
        statuses = (res.get("response") or {}).get("data", {}).get("statuses", []) if isinstance(res, dict) else []
        ok = isinstance(res, dict) and res.get("status") == "ok" and not any("error" in s for s in statuses)
        if ok:
            self.state["trades"] += 1
            log.info("[LIVE] %s %s %s -> %s", "KAUF" if sz > 0 else "VERKAUF", coin, abs(sz), statuses)
        else:
            log.error("[LIVE] Order fehlgeschlagen %s %s: %s", coin, sz, res)
        return ok

    def ensure_stops(self, sl_pct: float, meta: dict):
        """Legt für jede Position eine Stop-Loss-Order direkt an der Börse an (reduce-only).
        Sie greift auch, wenn der Bot/Rechner aus ist."""
        positions = {p["coin"]: p for p in self._raw_positions()}
        orders = [o for o in self.info.frontend_open_orders(self.address)
                  if o.get("isTrigger") and o.get("reduceOnly")]
        for coin, p in positions.items():
            szi, entry = float(p["szi"]), float(p["entryPx"])
            dec = meta.get(coin, {}).get("szDecimals", 4)
            want = round_px(entry * (1 - sl_pct if szi > 0 else 1 + sl_pct), dec)
            mine = [o for o in orders if o["coin"] == coin]
            if (len(mine) == 1 and abs(float(mine[0]["sz"]) - abs(szi)) < 10 ** -dec
                    and abs(float(mine[0]["triggerPx"]) - want) / want < 0.002):
                continue  # passt schon
            for o in mine:
                self.ex.cancel(coin, o["oid"])
            res = self.ex.order(coin, szi < 0, abs(szi), want,
                                {"trigger": {"triggerPx": want, "isMarket": True, "tpsl": "sl"}}, reduce_only=True)
            log.info("[LIVE] Stop-Loss %s @ %s gesetzt: %s", coin, want, res)
        for o in orders:  # verwaiste Stops (Position existiert nicht mehr) löschen
            if o["coin"] not in positions:
                self.ex.cancel(o["coin"], o["oid"])

    def check_stops(self, mids) -> list[str]:
        return []  # erledigt die Börse selbst

    def close_all(self, mids, meta, slippage):
        for coin in self.positions():
            log.warning("[LIVE] Schließe %s", coin)
            self.ex.market_close(coin, slippage=slippage)
