"""Technische Kennzahlen – in Python berechnet (günstig & exakt), die KI interpretiert sie nur."""
from __future__ import annotations

import statistics


def sma(xs, n):
    return sum(xs[-n:]) / n if len(xs) >= n else None


def rsi(closes, n=14):
    if len(closes) <= n:
        return None
    gains = losses = 0.0
    for a, b in zip(closes[-n - 1:-1], closes[-n:]):
        d = b - a
        gains += max(d, 0)
        losses += max(-d, 0)
    if losses == 0:
        return 100.0
    return 100 - 100 / (1 + gains / losses)


def summarize(candles: list[dict], ctx: dict | None, per_day: int = 6) -> dict:
    """candles: 4h-Kerzen. Rückgabe: kompakte Kennzahlen für einen Coin."""
    closes = [c["c"] for c in candles]
    if len(closes) < 10:
        return {"zu_wenig_daten": True}
    last = closes[-1]
    rets = [b / a - 1 for a, b in zip(closes[:-1], closes[1:]) if a]
    chg = lambda k: round((last / closes[-1 - k] - 1) * 100, 2) if len(closes) > k else None  # noqa: E731
    s20, s50 = sma(closes, 20), sma(closes, 50)
    hi, lo = max(c["h"] for c in candles), min(c["l"] for c in candles)
    out = {
        "preis": last,
        "veraenderung_24h_pct": chg(per_day),
        "veraenderung_7d_pct": chg(per_day * 7),
        "volatilitaet_tag_pct": round(statistics.pstdev(rets[-per_day * 7:]) * (per_day ** 0.5) * 100, 2) if rets else None,
        "rsi14": round(rsi(closes), 1) if rsi(closes) is not None else None,
        "ueber_sma20": last > s20 if s20 else None,
        "ueber_sma50": last > s50 if s50 else None,
        "abstand_14d_hoch_pct": round((last / hi - 1) * 100, 2),
        "abstand_14d_tief_pct": round((last / lo - 1) * 100, 2),
    }
    if ctx:
        out["funding_jahr_pct"] = round(ctx.get("funding", 0) * 24 * 365 * 100, 1)
        out["open_interest_usd"] = round(ctx.get("openInterest", 0) * ctx.get("markPx", last))
        out["volumen_24h_usd"] = round(ctx.get("dayNtlVlm", 0))
    return out
