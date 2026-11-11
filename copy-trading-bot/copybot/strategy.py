"""Berechnet die Ziel-Positionen: 'Was würden die Top-Trader mit MEINEM Geld halten?'

Positions-Spiegelung: Jeder Trader bekommt einen gleichen Anteil meines Kapitals.
Hält Trader X 2x seines Kontos in BTC-Long, halte ich 2x * copy_ratio seines Anteils in BTC-Long.
Kauft er nach -> ich auch. Schließt/dreht er -> ich auch.
"""
from __future__ import annotations


def target_exposures(leaders: dict[str, dict], my_equity: float, copy_cfg: dict, weights: dict | None = None,
                     trust: dict | None = None):
    """leaders: address -> {accountValue, positions{coin:{szi, px}}}
    weights: address -> Gewicht (gelernt; Standard 1.0 = gleich viel Kapital für jeden Trader)
    trust:   address -> 0..1 Vertrauen (vom Agenten-Team; verkleinert nur, verteilt nicht um)
    Rückgabe: (coin -> Ziel-Notional USD signiert, coin -> {address -> Beitrag USD})"""
    active = {a: d for a, d in leaders.items() if d and d["accountValue"] > 0}
    if not active or my_equity <= 0:
        return {}, {}
    w = {a: (weights or {}).get(a, 1.0) for a in active}
    total_w = sum(w.values()) or 1.0
    targets: dict[str, float] = {}
    contrib: dict[str, dict[str, float]] = {}
    for addr, d in active.items():
        per_leader = my_equity * copy_cfg["capital_usage"] * w[addr] / total_w * (trust or {}).get(addr, 1.0)
        for coin, p in d["positions"].items():
            usd = p["szi"] * p["px"] / d["accountValue"] * per_leader * copy_cfg["copy_ratio"]
            targets[coin] = targets.get(coin, 0.0) + usd
            contrib.setdefault(coin, {})[addr] = usd
    return targets, contrib


def apply_risk(targets: dict[str, float], my_equity: float, risk: dict) -> dict[str, float]:
    allowed = set(risk.get("allowed_coins") or [])
    blocked = set(risk.get("blocked_coins") or [])
    cap = my_equity * risk["max_position_pct"]
    out = {
        c: max(-cap, min(cap, v))
        for c, v in targets.items()
        if (not allowed or c in allowed) and c not in blocked
    }
    gross = sum(abs(v) for v in out.values())
    max_gross = my_equity * risk["max_leverage"]
    if gross > max_gross > 0:
        out = {c: v * max_gross / gross for c, v in out.items()}
    return out


def plan_orders(targets_usd, my_positions, mids, copy_cfg, close_on_leader_exit=True) -> list[dict]:
    """Vergleicht Ziel mit Ist und erzeugt Orders. my_positions: coin -> szi."""
    orders = []
    for coin in sorted(set(targets_usd) | set(my_positions)):
        px = mids.get(coin)
        if not px:
            continue
        if coin not in targets_usd and not close_on_leader_exit:
            continue
        cur = my_positions.get(coin, 0.0)
        tgt = targets_usd.get(coin, 0.0) / px
        delta = tgt - cur
        if abs(delta) * px < copy_cfg["min_trade_usd"]:
            if tgt == 0 and cur != 0:  # Rest komplett schließen
                orders.append({"coin": coin, "sz": -cur, "px": px, "reason": "close"})
            continue
        flip_or_close = tgt == 0 or (cur != 0 and (tgt > 0) != (cur > 0))
        if cur != 0 and not flip_or_close and abs(delta) / abs(cur) < copy_cfg["rebalance_threshold"]:
            continue
        if tgt == 0:
            reason = "close"
        elif cur == 0:
            reason = "open"
        elif flip_or_close:
            reason = "flip"
        else:
            reason = "increase" if abs(tgt) > abs(cur) else "reduce"
        orders.append({"coin": coin, "sz": delta, "px": px, "reason": reason})
    return orders
