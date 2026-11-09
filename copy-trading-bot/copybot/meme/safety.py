"""Sicherheits-Checks vor jedem Memecoin-Kauf. Lieber 10 gute Chancen verpassen als 1 Rug-Pull kaufen."""
from __future__ import annotations



def check_token(mint: str, market, rpc, cfg: dict,
                leader_price_sol: float | None = None) -> tuple[bool, list[str], dict]:
    """Prüft den TOKEN selbst. Rückgabe: (ok, Gründe dagegen, Infos)."""
    reasons: list[str] = []
    info: dict = {"mint": mint}
    try:
        ti = market.token_info(mint)
    except Exception as e:
        ti = None
        reasons.append(f"keine Marktdaten ({type(e).__name__})")
    if ti:
        info.update(ti)
        if ti["liquidity_usd"] < cfg["min_liquidity_usd"]:
            reasons.append(f"zu wenig Liquidität ({ti['liquidity_usd']:,.0f} $)")
        if leader_price_sol and ti["price_sol"] and ti["price_sol"] > leader_price_sol * (1 + cfg["max_chase_pct"]):
            reasons.append(f"Kurs schon +{(ti['price_sol'] / leader_price_sol - 1) * 100:.0f} % seit Kauf des Traders")
    elif not reasons:
        reasons.append("Token auf keiner Börse gefunden")
    try:
        mi = rpc.mint_info(mint)
        info["decimals"] = mi["decimals"]
        if cfg.get("require_mint_revoked", True) and mi["mintAuthority"]:
            reasons.append("Entwickler kann neue Tokens drucken (Mint Authority aktiv)")
        if cfg.get("require_freeze_revoked", True) and mi["freezeAuthority"]:
            reasons.append("Entwickler kann Tokens einfrieren (Freeze Authority aktiv)")
    except Exception as e:
        reasons.append(f"Token-Daten nicht lesbar ({type(e).__name__})")
    if cfg.get("block_rugcheck_danger", True):
        try:
            rc = market.rugcheck(mint)
            info["rugcheck"] = rc
            if rc["danger"]:
                reasons.append("RugCheck-Gefahr: " + ", ".join(rc["danger"][:3]))
        except Exception:
            info["rugcheck"] = None  # RugCheck nicht erreichbar -> andere Checks reichen
    return not reasons, reasons, info
