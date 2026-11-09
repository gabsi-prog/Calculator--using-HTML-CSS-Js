"""Öffentliche (read-only) Hyperliquid-Daten: Leaderboard, Positionen, Kurse."""
from __future__ import annotations

import logging
import time

import requests

INFO_URL = "https://api.hyperliquid.xyz/info"
LEADERBOARD_URL = "https://stats-data.hyperliquid.xyz/Mainnet/leaderboard"

log = logging.getLogger(__name__)


class HyperliquidData:
    def __init__(self, session: requests.Session | None = None, timeout: float = 15.0):
        self.s = session or requests.Session()
        self.timeout = timeout
        self._meta_cache: dict | None = None

    # -- intern -------------------------------------------------------------
    def _post(self, payload: dict, retries: int = 3):
        for attempt in range(retries):
            try:
                r = self.s.post(INFO_URL, json=payload, timeout=self.timeout)
                r.raise_for_status()
                return r.json()
            except requests.RequestException as e:
                wait = 2 ** attempt
                log.warning("API-Fehler (%s), neuer Versuch in %ss: %s", payload.get("type"), wait, e)
                time.sleep(wait)
        raise RuntimeError(f"Hyperliquid-API nicht erreichbar ({payload.get('type')})")

    # -- öffentlich ---------------------------------------------------------
    def leaderboard(self) -> list[dict]:
        r = self.s.get(LEADERBOARD_URL, timeout=60)
        r.raise_for_status()
        return r.json().get("leaderboardRows", [])

    def mids(self) -> dict[str, float]:
        return {k: float(v) for k, v in self._post({"type": "allMids"}).items()}

    def meta(self) -> dict[str, dict]:
        """coin -> {szDecimals, maxLeverage}"""
        if self._meta_cache is None:
            uni = self._post({"type": "meta"})["universe"]
            self._meta_cache = {
                a["name"]: {"szDecimals": a["szDecimals"], "maxLeverage": a.get("maxLeverage", 1)}
                for a in uni
                if not a.get("isDelisted")
            }
        return self._meta_cache

    def account(self, address: str) -> dict:
        """Kontowert + Positionen (signierte Größe szi: + long, - short)."""
        st = self._post({"type": "clearinghouseState", "user": address})
        positions = {}
        for ap in st.get("assetPositions", []):
            p = ap["position"]
            szi = float(p["szi"])
            if szi != 0:
                positions[p["coin"]] = {
                    "szi": szi,
                    "entryPx": float(p.get("entryPx") or 0),
                    "positionValue": float(p.get("positionValue") or 0),
                    "unrealizedPnl": float(p.get("unrealizedPnl") or 0),
                }
        return {
            "accountValue": float(st["marginSummary"]["accountValue"]),
            "positions": positions,
        }

    def user_fills(self, address: str) -> list[dict]:
        """Letzte (bis zu 2000) Ausführungen eines Traders, nur Perps."""
        fills = self._post({"type": "userFills", "user": address}) or []
        return [f for f in fills if not f["coin"].startswith("@") and "/" not in f["coin"]]


def round_px(px: float, sz_decimals: int) -> float:
    """Hyperliquid-Preisregeln für Perps: max. 5 signifikante Stellen, max. (6 - szDecimals) Nachkommastellen."""
    return round(float(f"{px:.5g}"), max(0, 6 - sz_decimals))
