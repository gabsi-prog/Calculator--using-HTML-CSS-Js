import json
import time
from types import SimpleNamespace

import pytest

from copybot.ai_review import run_review
from copybot.healer import Healer, classify_exception, classify_order_error
from copybot.learner import adapt_stop_loss, daily_learning, risk_throttle, update_trader_weights
from copybot.notify import Notifier
from copybot.tuning import effective_cfg, set_param
from tests.test_bot import CFG, bot  # noqa: F401  (Fixture)


class FlakyBroker:
    """Erste Order scheitert mit gegebenem Fehler, danach klappt es."""
    def __init__(self, error, fail_times=1):
        self.error, self.fail_times, self.calls, self.last_error = error, fail_times, [], ""

    def execute(self, coin, sz, px, dec, slip):
        self.calls.append((coin, sz, dec, slip))
        if len(self.calls) <= self.fail_times:
            self.last_error = self.error
            return False
        return True


def healer():
    return Healer({}, Notifier("", ""))


def test_classify():
    assert classify_order_error("Insufficient margin to place order")[0] == "zu_wenig_margin"
    assert classify_order_error("Order must have minimum value of $10")[1] == "skip"
    assert classify_exception(TimeoutError("read timed out")) == "netzwerk"
    assert classify_exception(KeyError("marginSummary")) == "datenformat"


def test_heals_insufficient_margin_with_half_size():
    h, br = healer(), FlakyBroker("Insufficient margin")
    assert h.execute_with_healing(br, "BTC", 0.02, 100_000, 5, 0.01)
    assert br.calls[1][1] == 0.01                          # halbe Größe
    assert h.state["journal"]["errors"][-1]["behoben"]


def test_heals_price_error_with_wider_slippage():
    h, br = healer(), FlakyBroker("Price must be divisible by tick size")
    assert h.execute_with_healing(br, "ETH", 1, 4000, 4, 0.01)
    assert br.calls[1][3] == 0.02


def test_quarantine_after_repeated_failures():
    h = healer()
    for _ in range(3):
        h.execute_with_healing(FlakyBroker("weird error", fail_times=99), "XYZ", 1, 10, 2, 0.01)
    assert "XYZ" in h.quarantined()
    assert any("Quarantäne" in m for m in h.notifier.sent)


def test_alert_after_5_failed_cycles():
    h = healer()
    for _ in range(5):
        h.cycle_failed(ConnectionError("connection reset"))
    assert any("5 Durchläufe" in m for m in h.notifier.sent)
    h.cycle_ok()
    assert h.state["consecutive_failures"] == 0


def test_risk_throttle():
    assert risk_throttle(0, 0.25) == 1
    assert risk_throttle(0.125, 0.25) == pytest.approx(0.5)
    assert risk_throttle(0.24, 0.25) == 0.3


def test_never_riskier_than_config():
    st = {}
    ch = set_param(CFG, st, "copy.copy_ratio", 5.0, "test", "ki")    # will höher als config (0.5)
    assert ch is None or st["overrides"]["copy.copy_ratio"] <= CFG["copy"]["copy_ratio"]
    set_param(CFG, st, "copy.copy_ratio", 0.3, "vorsichtiger", "ki")
    assert effective_cfg(CFG, st)["copy"]["copy_ratio"] == 0.3
    set_param(CFG, st, "risk.stop_loss_pct", 0.5, "test", "ki")
    assert st["overrides"]["risk.stop_loss_pct"] == 0.15           # harte Obergrenze


def test_good_trader_gets_more_weight():
    st = {"trader_stats": {"0xa": {"pnl": 40.0}, "0xb": {"pnl": -40.0}}}
    update_trader_weights(st, [{"address": "0xa"}, {"address": "0xb"}], 1000, CFG)
    assert st["weights"]["0xa"] > 1 > st["weights"]["0xb"]


def test_weights_shift_capital(bot):  # noqa: F811
    b, _ = bot
    b.state["weights"] = {"0xa": 2.0, "0xb": 1.0}
    b.step()
    pos = b.broker.positions()
    btc_usd, eth_usd = pos["BTC"] * 100_000, abs(pos["ETH"]) * 4_000
    assert btc_usd / eth_usd == pytest.approx(2, rel=0.05)


def test_unnecessary_stops_widen_stop_loss():
    now = time.time()
    st = {"journal": {"stops": [{"t": now, "coin": "BTC", "whipsaw": True}] * 4}}
    ch = adapt_stop_loss(st, CFG)
    assert ch and ch["new"] == pytest.approx(0.09)
    st = {"journal": {"stops": [{"t": now, "coin": "BTC", "whipsaw": False}] * 4}}
    assert adapt_stop_loss(st, CFG)["new"] == pytest.approx(0.075)


def test_stop_is_journaled_and_evaluated(bot):  # noqa: F811
    b, data = bot
    b.step()
    data.prices["BTC"] = 90_000
    b.step()
    stop = b.state["journal"]["stops"][-1]
    assert stop["coin"] == "BTC" and stop["entry"] > 90_000
    stop["t"] -= 2 * 86400                    # 2 Tage später: Kurs wieder über Einstieg
    data.prices["BTC"] = 120_000
    daily_learning(b, data.mids(), 1000)
    assert stop["whipsaw"] is True


def test_lag_cost_is_measured(bot):  # noqa: F811
    b, data = bot
    data.accts["0xa"]["positions"]["BTC"]["entryPx"] = 99_000   # Trader stieg 1 % günstiger ein
    b.step()
    trade = next(t for t in b.state["journal"]["trades"] if t["coin"] == "BTC")
    assert trade["lag"] == pytest.approx(1_000 / 99_000, rel=1e-3)
    assert b.state["trader_stats"]["0xa"]["lag_n"] == 1


def test_daily_report_contains_self_analysis(bot):  # noqa: F811
    b, _ = bot
    b.cfg["telegram"]["daily_report_hour_utc"] = 0
    b.step()
    assert any("Selbst-Analyse" in m for m in b.notifier.sent)
    assert b.state["journal"]["days"]


def test_ai_review_applies_bounded_suggestions(bot):  # noqa: F811
    b, _ = bot
    b.step()
    answer = {"zusammenfassung": "Ruhige Woche.", "probleme": ["Stops zu eng"], "code_probleme": [],
              "vorschlaege": [{"parameter": "risk.stop_loss_pct", "neuer_wert": 0.1, "begruendung": "zu eng"},
                              {"parameter": "copy.copy_ratio", "neuer_wert": 3.0, "begruendung": "mehr Risiko"}]}
    calls = {}

    def create(**kw):
        calls.update(kw)
        return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=json.dumps(answer))])

    client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=create)))
    text = run_review(b, client=client)
    assert calls["model"] == "claude-opus-5-5"
    assert b.state["overrides"]["risk.stop_loss_pct"] == 0.1
    assert "copy.copy_ratio" not in b.state["overrides"]       # riskanter als config -> abgelehnt
    assert "Ruhige Woche" in text and "Stops zu eng" in text


def test_ai_review_without_key(bot, monkeypatch):  # noqa: F811
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    b, _ = bot
    assert "übersprungen" in run_review(b)
