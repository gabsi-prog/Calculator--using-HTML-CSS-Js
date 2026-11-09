"""Berechnet die Ziel-Positionen: 'Was würden die Top-Trader mit MEINEM Geld halten?'

Prinzip (Positions-Spiegelung statt Order-Spiegelung):
  Jeder Trader bekommt einen gleichen Anteil meines Kapitals.
  Hält Trader X z.B. 2x seines Kontos in BTC-Long, halte ich 2x * copy_ratio
  meines ihm zugeteilten Kapitals in BTC-Long.
  Kauft er nach -> ich kaufe nach. Verkauft/schließt er -> ich auch. Dreht er short -> ich auch.
Das ist robuster als einzelne Orders zu kopieren (keine verpassten Fills, kein Doppel-Kauf).
"""
from __future__ import annotations


def target_exposures(leaders: dict[str, dict], my_equity: float, copy_cfg: dict) -> dict[str, float]:
    """leaders: address -> {accountValue, positions{coin:{szi,...}}}, mids müssen in positions als 'px' sein.
    Rückgabe: coin -> Ziel-Notional in USD (signiert)."""
    active = {a: d for a, d in leaders.items() if d and d["accountValue"] > 0}
    if not active or my_equity <= 0:
        return {}
    per_leader = my_equity * copy_cfg["capital_usage"] / len(active)
    targets: dict[str, float] = {}
    for d in active.values():
        for coin, p in d["positions"].items():
            leader_exposure = p["szi"] * p["px"] / d["accountValue"]  # signierter Hebel des Traders auf diesen Coin
            targets[coin] = targets.get(coin, 0.0) + leader_exposure * per_leader * copy_cfg["copy_ratio"]
    return targets


def apply_risk(targets: dict[str, float], my_equity: float, risk: dict) -> dict[str, float]:
    allowed = set(risk.get("allowed_coins") or [])
    blocked = set(risk.get("blocked_coins") or [])
    out = {}
    cap = my_equity * risk["max_position_pct"]
    for coin, usd in targets.items():
        if allowed and coin not in allowed:
            continue
        if coin in blocked:
            continue
        out[coin] = max(-cap, min(cap, usd))
    gross = sum(abs(v) for v in out.values())
    max_gross = my_equity * risk["max_leverage"]
    if gross > max_gross > 0:
        f = max_gross / gross
        out = {c: v * f for c, v in out.items()}
    return out


def plan_orders(
    targets_usd: dict[str, float],
    my_positions: dict[str, float],
    mids: dict[str, float],
    copy_cfg: dict,
    close_on_leader_exit: bool = True,
) -> list[dict]:
    """Vergleicht Ziel mit Ist und erzeugt Orders. my_positions: coin -> szi."""
    orders = []
    coins = set(targets_usd) | set(my_positions)
    for coin in sorted(coins):
        px = mids.get(coin)
        if not px:
            continue
        cur_sz = my_positions.get(coin, 0.0)
        if coin not in targets_usd and not close_on_leader_exit:
            continue
        tgt_sz = targets_usd.get(coin, 0.0) / px
        delta = tgt_sz - cur_sz
        delta_usd = abs(delta) * px
        if delta_usd < copy_cfg["min_trade_usd"]:
            # Rest-Position komplett schließen, falls Ziel 0
            if tgt_sz == 0 and cur_sz != 0 and abs(cur_sz) * px > 0:
                orders.append({"coin": coin, "sz": -cur_sz, "px": px, "reason": "close"})
            continue
        # Kleine Abweichungen ignorieren (spart Gebühren), außer bei Schließen/Drehen
        flip_or_close = tgt_sz == 0 or (cur_sz != 0 and (tgt_sz > 0) != (cur_sz > 0))
        if cur_sz != 0 and not flip_or_close and abs(delta) / abs(cur_sz) < copy_cfg["rebalance_threshold"]:
            continue
        if tgt_sz == 0:
            reason = "close"
        elif cur_sz == 0:
            reason = "open"
        elif flip_or_close:
            reason = "flip"
        elif abs(tgt_sz) > abs(cur_sz):
            reason = "increase"
        else:
            reason = "reduce"
        orders.append({"coin": coin, "sz": delta, "px": px, "reason": reason})
    return orders
