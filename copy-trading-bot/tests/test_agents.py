import base64
import json
import time
from types import SimpleNamespace

import pytest

from copybot.agents.base import BudgetExceeded, CostTracker
from copybot.agents.indicators import summarize
from copybot.agents.team import active_overlay, apply_decision, run_team
from copybot.dashboard import build_data, encrypt
from tests.test_bot import bot  # noqa: F401

DECISION = {
    "zusammenfassung": "Vorsichtig wegen Inflationsdaten.", "marktampel": "gelb", "global_faktor": 0.5,
    "coin_faktoren": [{"coin": "BTC", "faktor": 0.0, "grund": "Test"}],
    "sperren": [{"coin": "SOL", "stunden": 999, "grund": "Hack"}],
    "trader_vertrauen": [{"adresse": "0xB", "faktor": 1.7, "grund": "zu hoch -> wird auf 1 begrenzt"}],
    "warnungen": ["CPI morgen"],
}


def candles(n=60, start=100.0, step=0.5):
    return [{"t": i, "o": start + i * step, "h": start + i * step + 1, "l": start + i * step - 1,
             "c": start + i * step, "v": 1} for i in range(n)]


class FakeClient:
    def __init__(self, fail=None):
        self.calls, self.fail = [], fail
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

    def create(self, **kw):
        self.calls.append(kw)
        if self.fail and self.fail in kw["system"]:
            raise RuntimeError("API kaputt")
        usage = SimpleNamespace(input_tokens=10_000, output_tokens=1_000, cache_creation_input_tokens=0,
                                server_tool_use=SimpleNamespace(web_search_requests=3 if kw.get("tools") else 0))
        text = json.dumps(DECISION) if "Risiko-Chef" in kw["system"] else "**Lage:** ruhig\n- BTC stabil"
        return SimpleNamespace(stop_reason="end_turn", usage=usage, content=[SimpleNamespace(type="text", text=text)])


@pytest.fixture
def team_bot(bot):  # noqa: F811
    b, data = bot
    data.market_contexts = lambda: {"BTC": {"funding": 0.0001, "openInterest": 100, "markPx": 100_000, "dayNtlVlm": 5e9}}
    data.candles = lambda coin, interval="4h", days=14: candles()
    b.cfg["agents"] = {"enabled": True, "monthly_budget_usd": 30, "interval_hours": 8, "model": "claude-opus-5-5"}
    return b, data


def test_indicators():
    s = summarize(candles(), {"funding": 0.0001, "openInterest": 10, "markPx": 129.5, "dayNtlVlm": 1})
    assert s["ueber_sma20"] and s["rsi14"] == 100.0 and s["funding_jahr_pct"] == pytest.approx(87.6)


def test_team_runs_all_agents_and_applies_decision(team_bot):
    b, _ = team_bot
    client = FakeClient()
    text = run_team(b, client=client)
    assert len(client.calls) == 4
    assert all(c["model"] == "claude-opus-5-5" and c["fallbacks"] == "default" for c in client.calls)
    news_call = next(c for c in client.calls if c.get("tools"))
    assert news_call["tools"][0]["type"] == "web_search_20260209"
    assert "format" in next(c for c in client.calls if "Risiko-Chef" in c["system"])["output_config"]
    ov = b.state["agent_overlay"]
    assert ov["global"] == 0.5 and ov["coins"]["BTC"] == 0.0 and ov["trader"]["0xb"] == 1.0  # auf 1 begrenzt
    assert ov["sperren"]["SOL"] - time.time() <= 72 * 3600 + 5                               # max 72 h
    assert "GELB" in text and "CPI morgen" in text
    assert set(b.state["agents"]["reports"]) == {"markt", "news", "trader", "chef"}
    assert b.state["agent_costs"]["usd"] > 0


def test_overlay_only_brakes_trading(team_bot):
    b, _ = team_bot
    b.step()
    full_eth = abs(b.broker.positions()["ETH"])
    apply_decision(b.state, DECISION)
    b.step()
    pos = b.broker.positions()
    assert "BTC" not in pos                                        # Faktor 0 -> geschlossen
    assert abs(pos["ETH"]) == pytest.approx(full_eth * 0.5, rel=0.1)  # global 50 %


def test_overlay_expires():
    st = {}
    apply_decision(st, DECISION)
    assert active_overlay(st)
    st["agent_overlay"]["t"] -= 25 * 3600
    assert active_overlay(st) is None


def test_failed_specialist_does_not_stop_team(team_bot):
    b, _ = team_bot
    text = run_team(b, client=FakeClient(fail="Nachrichten-Analyst"))
    assert "Ausgefallen: Nachrichten-Analyst" in text
    assert b.state["agent_overlay"]["global"] == 0.5


def test_budget_guard():
    st = {}
    c = CostTracker(st, monthly_budget=0.01)
    c.add("claude-opus-5-5", SimpleNamespace(input_tokens=1_000_000, output_tokens=0))
    with pytest.raises(BudgetExceeded):
        c.check()


def test_team_without_key(team_bot, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    b, _ = team_bot
    assert "übersprungen" in run_team(b)


def test_dashboard_data_and_encryption(team_bot):
    b, _ = team_bot
    b.step()
    run_team(b, client=FakeClient())
    d = build_data(b)
    json.dumps(d, default=str)
    assert d["konto"]["wert"] > 0 and d["positionen"] and len(d["agenten"]["berichte"]) == 4
    enc = encrypt(d, "geheim")
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    raw = lambda k: base64.b64decode(enc[k])  # noqa: E731
    key = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=raw("salt"), iterations=enc["iter"]).derive(b"geheim")
    assert json.loads(AESGCM(key).decrypt(raw("iv"), raw("daten"), None))["modus"] == "paper"
