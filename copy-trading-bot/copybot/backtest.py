"""Backtest: 'Was hätte es gebracht, diesen Trader zu kopieren?'

Spielt die letzten (bis zu 2000) Ausführungen des Traders nach – skaliert auf dein Kapital,
mit Gebühren und einem Preis-Aufschlag für die Kopier-Verzögerung.
Vereinfachung: Skalierung mit dem heutigen Kontowert des Traders, ohne Stop-Loss/Risiko-Limits.
"""
from __future__ import annotations

from .broker import TAKER_FEE, apply_fill
from .selector import holding_stats


def backtest_fills(fills: list[dict], scale: float, final_mids: dict, alloc: float, penalty: float = 0.001) -> dict:
    fills = sorted(fills, key=lambda f: f["time"])
    positions: dict = {}
    seen: set[str] = set()
    realized = fees = 0.0
    trades = 0
    for f in fills:
        coin, px = f["coin"], float(f["px"])
        if coin not in seen:
            seen.add(coin)
            start = float(f["startPosition"]) * scale
            if start:  # bestehende Position zum ersten bekannten Preis übernehmen
                p = px * (1 + penalty if start > 0 else 1 - penalty)
                apply_fill(positions, coin, start, p)
                fees += abs(start) * p * TAKER_FEE
        sz = float(f["sz"]) * scale * (1 if f["side"] == "B" else -1)
        p = px * (1 + penalty if sz > 0 else 1 - penalty)
        realized += apply_fill(positions, coin, sz, p)
        fees += abs(sz) * p * TAKER_FEE
        trades += 1
    unrealized = sum(pos["szi"] * (final_mids.get(c, pos["entryPx"]) - pos["entryPx"]) for c, pos in positions.items())
    pnl = realized + unrealized - fees
    days = (fills[-1]["time"] - fills[0]["time"]) / 86_400_000 if fills else 0
    return {"pnl": pnl, "pnl_pct": pnl / alloc if alloc else 0, "fees": fees, "trades": trades,
            "days": days, **holding_stats(fills)}


def run_backtest(data, addresses: list[str], cfg: dict) -> list[dict]:
    mids = data.mids()
    alloc = cfg["paper_start_balance"] * cfg["copy"]["capital_usage"] / max(1, cfg["selection"]["top_n"])
    results = []
    for addr in addresses:
        acct = data.account(addr)["accountValue"]
        if acct <= 0:
            continue
        scale = alloc * cfg["copy"]["copy_ratio"] / acct
        r = backtest_fills(data.user_fills(addr), scale, mids, alloc, cfg.get("backtest", {}).get("delay_penalty", 0.001))
        results.append({"address": addr, "alloc": alloc, **r})
    return results


def format_results(results: list[dict]) -> str:
    lines = ["Backtest (Kopieren mit Verzögerung + Gebühren):", ""]
    for r in results:
        mh = r["median_hold_min"]
        lines.append(
            f"{r['address']}\n  Zeitraum {r['days']:.1f} Tage | {r['trades']} Trades | "
            f"Haltedauer ~{'-' if mh is None else f'{mh:.0f} min'}\n"
            f"  Ergebnis {r['pnl']:+.2f} USD ({r['pnl_pct'] * 100:+.1f} % von {r['alloc']:.0f} USD), "
            f"Gebühren {r['fees']:.2f} USD"
        )
    if results:
        tot = sum(r["pnl"] for r in results)
        lines.append(f"\nGesamt: {tot:+.2f} USD")
    return "\n".join(lines)
