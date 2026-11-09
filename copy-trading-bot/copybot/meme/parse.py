"""Erkennt in einer Solana-Transaktion, ob eine Wallet einen Token gekauft oder verkauft hat."""
from __future__ import annotations

from .chain import LAMPORTS, QUOTE_MINTS, SOL_MINT, USDC_MINT, USDT_MINT

STABLES = {USDC_MINT, USDT_MINT}


def _token_changes(meta: dict, wallet: str) -> dict[str, dict]:
    """mint -> {pre, post, decimals} für Token-Konten, die der Wallet gehören."""
    out: dict[str, dict] = {}
    for key, field in (("preTokenBalances", "pre"), ("postTokenBalances", "post")):
        for b in meta.get(key) or []:
            if b.get("owner") != wallet:
                continue
            ui = b.get("uiTokenAmount") or {}
            amt = float(ui.get("uiAmountString") or ui.get("uiAmount") or 0)
            e = out.setdefault(b["mint"], {"pre": 0.0, "post": 0.0, "decimals": ui.get("decimals", 0)})
            e[field] += amt
    return out


def parse_swap(tx: dict, wallet: str, sol_usd: float = 0.0) -> dict | None:
    """Rückgabe: {side: buy/sell, mint, tokens, pre_tokens, quote_sol, price_sol, decimals, time, sig} oder None."""
    if not tx or (tx.get("meta") or {}).get("err") is not None:
        return None
    meta = tx["meta"]
    keys = [k["pubkey"] if isinstance(k, dict) else k for k in tx["transaction"]["message"]["accountKeys"]]
    if wallet not in keys:
        return None
    i = keys.index(wallet)
    fee = meta.get("fee", 0) if i == 0 else 0
    sol_delta = (meta["postBalances"][i] - meta["preBalances"][i] + fee) / LAMPORTS  # Gebühr nicht als Handel zählen
    changes = _token_changes(meta, wallet)
    wsol = changes.pop(SOL_MINT, None)
    if wsol:
        sol_delta += wsol["post"] - wsol["pre"]
    stable_delta = 0.0
    for m in list(changes):
        if m in STABLES:
            c = changes.pop(m)
            stable_delta += c["post"] - c["pre"]
    quote_sol = sol_delta + (stable_delta / sol_usd if sol_usd and stable_delta else 0.0)
    moved = {m: c for m, c in changes.items() if abs(c["post"] - c["pre"]) > 0 and m not in QUOTE_MINTS}
    if len(moved) != 1:  # kein oder mehrdeutiger Swap (z. B. Token->Token) -> ignorieren
        return None
    mint, c = next(iter(moved.items()))
    d_tok = c["post"] - c["pre"]
    if d_tok > 0 and quote_sol < 0:
        side = "buy"
    elif d_tok < 0 and quote_sol > 0:
        side = "sell"
    else:
        return None  # Transfer/Airdrop statt Handel
    return {"side": side, "mint": mint, "tokens": abs(d_tok), "pre_tokens": c["pre"], "post_tokens": c["post"],
            "quote_sol": abs(quote_sol), "price_sol": abs(quote_sol) / abs(d_tok), "decimals": c["decimals"],
            "time": tx.get("blockTime"), "sig": (tx["transaction"].get("signatures") or [None])[0]}
