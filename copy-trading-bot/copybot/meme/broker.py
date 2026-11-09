"""Ausführung von Memecoin-Swaps. Paper: echte Jupiter-Kurse, simuliertes Geld. Live: echte Transaktionen."""
from __future__ import annotations

import base64
import logging
import os

from .chain import LAMPORTS, SOL_MINT

log = logging.getLogger(__name__)
TX_FEE_SOL = 0.0003  # Netzwerk- + Prioritätsgebühr (Schätzung für Paper)


class ImpactTooHigh(Exception):
    pass


def _quote_out(market, in_mint, out_mint, amount_raw, slippage_bps, max_impact):
    q = market.quote(in_mint, out_mint, amount_raw, slippage_bps)
    impact = float(q.get("priceImpactPct") or 0)
    if max_impact is not None and impact > max_impact:
        raise ImpactTooHigh(f"Preiseinfluss {impact * 100:.1f} % zu hoch")
    return q, int(q["outAmount"]), impact


class PaperMemeBroker:
    def __init__(self, ms: dict, market, slippage_bps: int):
        self.ms, self.market, self.slip = ms, market, slippage_bps

    def balance_sol(self) -> float:
        return self.ms["sol"]

    def buy(self, mint: str, sol: float, decimals: int, max_impact: float | None = None) -> dict:
        if sol + TX_FEE_SOL > self.ms["sol"]:
            raise RuntimeError("nicht genug SOL")
        _, out, impact = _quote_out(self.market, SOL_MINT, mint, int(sol * LAMPORTS), self.slip, max_impact)
        tokens = out / 10 ** decimals
        self.ms["sol"] -= sol + TX_FEE_SOL
        return {"tokens": tokens, "sol": sol + TX_FEE_SOL, "impact": impact, "sig": "paper"}

    def sell(self, mint: str, tokens: float, decimals: int) -> dict:
        _, out, impact = _quote_out(self.market, mint, SOL_MINT, int(tokens * 10 ** decimals), self.slip, None)
        sol = out / LAMPORTS - TX_FEE_SOL
        self.ms["sol"] += sol
        return {"sol": sol, "impact": impact, "sig": "paper"}


class LiveMemeBroker:
    """Signiert Jupiter-Swaps mit einer eigenen Bot-Wallet. Benötigt: pip install solders"""

    def __init__(self, ms: dict, market, rpc, slippage_bps: int):
        from solders.keypair import Keypair

        key = os.environ.get("SOLANA_PRIVATE_KEY", "").strip()
        if not key:
            raise SystemExit("Für Memecoin-LIVE muss SOLANA_PRIVATE_KEY gesetzt sein (eigene Bot-Wallet!).")
        self.kp = Keypair.from_base58_string(key)
        self.address = str(self.kp.pubkey())
        self.ms, self.market, self.rpc, self.slip = ms, market, rpc, slippage_bps

    def balance_sol(self) -> float:
        return self.rpc.sol_balance(self.address)

    def _send(self, quote: dict) -> str:
        from solders.transaction import VersionedTransaction

        raw = base64.b64decode(self.market.swap_tx(quote, self.address))
        tx = VersionedTransaction.from_bytes(raw)
        signed = VersionedTransaction(tx.message, [self.kp])
        sig = self.rpc.send_raw(base64.b64encode(bytes(signed)).decode())
        if not self.rpc.confirmed(sig):
            raise RuntimeError(f"Transaktion nicht bestätigt: {sig}")
        return sig

    def buy(self, mint: str, sol: float, decimals: int, max_impact: float | None = None) -> dict:
        before_sol = self.balance_sol()
        if sol + 0.01 > before_sol:
            raise RuntimeError("nicht genug SOL in der Bot-Wallet")
        before = self.rpc.token_balances(self.address).get(mint, 0.0)
        q, _, impact = _quote_out(self.market, SOL_MINT, mint, int(sol * LAMPORTS), self.slip, max_impact)
        sig = self._send(q)
        tokens = self.rpc.token_balances(self.address).get(mint, 0.0) - before
        spent = before_sol - self.balance_sol()
        log.info("[MEME LIVE] Kauf %s: %.6g Tokens für %.4f SOL (%s)", mint, tokens, spent, sig)
        return {"tokens": tokens, "sol": spent, "impact": impact, "sig": sig}

    def sell(self, mint: str, tokens: float, decimals: int) -> dict:
        held = self.rpc.token_balances(self.address).get(mint, 0.0)
        tokens = min(tokens, held)
        before_sol = self.balance_sol()
        q, _, impact = _quote_out(self.market, mint, SOL_MINT, int(tokens * 10 ** decimals), self.slip, None)
        sig = self._send(q)
        got = self.balance_sol() - before_sol
        log.info("[MEME LIVE] Verkauf %s: %.6g Tokens -> %.4f SOL (%s)", mint, tokens, got, sig)
        return {"sol": got, "impact": impact, "sig": sig}
