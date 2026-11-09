"""Datenquellen: Solana-RPC (Wallet-Aktivität), Jupiter (Preise, Swaps), DexScreener (Liquidität), RugCheck."""
from __future__ import annotations

import logging
import time

import requests

log = logging.getLogger(__name__)

SOL_MINT = "So11111111111111111111111111111111111111112"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
USDT_MINT = "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"
QUOTE_MINTS = {SOL_MINT, USDC_MINT, USDT_MINT}
LAMPORTS = 1_000_000_000


class SolanaRPC:
    def __init__(self, url: str, session: requests.Session | None = None):
        self.url, self.s = url, session or requests.Session()
        self._id = 0

    def call(self, method: str, params: list, retries: int = 3):
        for attempt in range(retries):
            self._id += 1
            try:
                r = self.s.post(self.url, json={"jsonrpc": "2.0", "id": self._id, "method": method, "params": params},
                                timeout=20)
                if r.status_code == 429:
                    raise requests.RequestException("429 rate limit")
                r.raise_for_status()
                d = r.json()
                if "error" in d:
                    raise RuntimeError(f"RPC {method}: {d['error']}")
                return d["result"]
            except requests.RequestException as e:
                if attempt == retries - 1:
                    raise
                time.sleep(1.5 * (attempt + 1))
                log.debug("RPC-Wiederholung %s: %s", method, e)

    def signatures(self, address: str, until: str | None = None, limit: int = 15) -> list[dict]:
        opts = {"limit": limit, "commitment": "confirmed"}
        if until:
            opts["until"] = until
        return self.call("getSignaturesForAddress", [address, opts]) or []

    def transaction(self, sig: str) -> dict | None:
        return self.call("getTransaction", [sig, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0,
                                                  "commitment": "confirmed"}])

    def mint_info(self, mint: str) -> dict:
        v = (self.call("getAccountInfo", [mint, {"encoding": "jsonParsed"}]) or {}).get("value") or {}
        info = (((v.get("data") or {}).get("parsed") or {}).get("info")) or {}
        return {"decimals": info.get("decimals"), "mintAuthority": info.get("mintAuthority"),
                "freezeAuthority": info.get("freezeAuthority")}

    def sol_balance(self, owner: str) -> float:
        return (self.call("getBalance", [owner, {"commitment": "confirmed"}]) or {}).get("value", 0) / LAMPORTS

    def token_balances(self, owner: str) -> dict[str, float]:
        out = {}
        for program in ("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA", "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"):
            res = self.call("getTokenAccountsByOwner", [owner, {"programId": program}, {"encoding": "jsonParsed"}]) or {}
            for acc in res.get("value", []):
                info = acc["account"]["data"]["parsed"]["info"]
                amt = float(info["tokenAmount"]["uiAmount"] or 0)
                if amt:
                    out[info["mint"]] = out.get(info["mint"], 0) + amt
        return out

    def send_raw(self, tx_b64: str) -> str:
        return self.call("sendTransaction", [tx_b64, {"encoding": "base64", "skipPreflight": False, "maxRetries": 3,
                                                      "preflightCommitment": "confirmed"}], retries=1)

    def confirmed(self, sig: str, timeout: float = 45) -> bool:
        end = time.time() + timeout
        while time.time() < end:
            st = (self.call("getSignatureStatuses", [[sig]]) or {}).get("value", [None])[0]
            if st and st.get("err"):
                raise RuntimeError(f"Transaktion fehlgeschlagen: {st['err']}")
            if st and st.get("confirmationStatus") in ("confirmed", "finalized"):
                return True
            time.sleep(1.5)
        return False


class MarketData:
    """Preise & Token-Infos. Alles öffentlich, ohne Key."""

    def __init__(self, jupiter: str = "https://lite-api.jup.ag", session: requests.Session | None = None):
        self.jup, self.s = jupiter.rstrip("/"), session or requests.Session()
        self._cache: dict[str, tuple[float, object]] = {}

    def _get(self, url, params=None, ttl=0):
        key = url + str(params)
        if ttl and key in self._cache and time.time() - self._cache[key][0] < ttl:
            return self._cache[key][1]
        r = self.s.get(url, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
        if ttl:
            self._cache[key] = (time.time(), data)
        return data

    def prices_usd(self, mints: list[str]) -> dict[str, float]:
        if not mints:
            return {}
        d = self._get(f"{self.jup}/price/v3", {"ids": ",".join(mints[:50])})
        out = {}
        for m, v in (d.get("data", d) or {}).items():
            if isinstance(v, dict):
                p = v.get("usdPrice", v.get("price"))
                if p is not None:
                    out[m] = float(p)
        return out

    def sol_usd(self) -> float:
        return self.prices_usd([SOL_MINT]).get(SOL_MINT, 0.0)

    def token_info(self, mint: str) -> dict | None:
        """Bester Handelsplatz laut DexScreener: Symbol, Preis, Liquidität, Alter."""
        d = self._get(f"https://api.dexscreener.com/latest/dex/tokens/{mint}", ttl=20)
        pairs = [p for p in (d.get("pairs") or []) if p.get("chainId") == "solana"
                 and p.get("baseToken", {}).get("address") == mint]
        if not pairs:
            return None
        p = max(pairs, key=lambda x: (x.get("liquidity") or {}).get("usd") or 0)
        return {"symbol": p["baseToken"].get("symbol", "?"), "name": p["baseToken"].get("name", ""),
                "price_usd": float(p.get("priceUsd") or 0), "price_sol": float(p.get("priceNative") or 0),
                "liquidity_usd": float((p.get("liquidity") or {}).get("usd") or 0), "fdv": float(p.get("fdv") or 0),
                "volume_24h": float((p.get("volume") or {}).get("h24") or 0), "dex": p.get("dexId"),
                "created_ms": p.get("pairCreatedAt"), "url": p.get("url")}

    def rugcheck(self, mint: str) -> dict:
        d = self._get(f"https://api.rugcheck.xyz/v1/tokens/{mint}/report/summary", ttl=300)
        risks = d.get("risks") or []
        return {"score": d.get("score_normalised", d.get("score")),
                "danger": [r.get("name") for r in risks if str(r.get("level")).lower() == "danger"],
                "warn": [r.get("name") for r in risks if str(r.get("level")).lower() == "warn"]}

    def quote(self, input_mint: str, output_mint: str, amount_raw: int, slippage_bps: int) -> dict:
        return self._get(f"{self.jup}/swap/v1/quote", {"inputMint": input_mint, "outputMint": output_mint,
                                                        "amount": str(int(amount_raw)), "slippageBps": slippage_bps})

    def swap_tx(self, quote: dict, user: str) -> str:
        r = self.s.post(f"{self.jup}/swap/v1/swap", json={
            "quoteResponse": quote, "userPublicKey": user, "wrapAndUnwrapSol": True,
            "dynamicComputeUnitLimit": True,
            "prioritizationFeeLamports": {"priorityLevelWithMaxLamports": {"maxLamports": 1_000_000,
                                                                           "priorityLevel": "veryHigh"}}},
            timeout=20)
        r.raise_for_status()
        return r.json()["swapTransaction"]
