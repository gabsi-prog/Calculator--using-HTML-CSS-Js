import copy
import time

import pytest
import yaml

from copybot.backtest import backtest_fills
from copybot.bot import CopyBot
from copybot.broker import PaperBroker
from copybot.hl_api import round_px
from copybot.notify import Notifier
from copybot.selector import holding_stats, is_scalper, rank_traders
from copybot.strategy import apply_risk, plan_orders

CFG = yaml.safe_load(open("config.yaml"))
H = 3_600_000  # 1 Stunde in ms


def lb_row(addr, acct, month_roi, week_pnl=1000, alltime=500_000, vlm=5_000_000):
    return {"ethAddress": addr, "accountValue": str(acct), "displayName": None, "windowPerformances": [
        ["day", {"pnl": "10", "roi": "0.01", "vlm": "1"}],
        ["week", {"pnl": str(week_pnl), "roi": "0.02", "vlm": "1"}],
        ["month", {"pnl": "1000", "roi": str(month_roi), "vlm": str(vlm)}],
        ["allTime", {"pnl": str(alltime), "roi": "1", "vlm": "1"}]]}


def fill(coin, side, sz, px, start, t):
    return {"coin": coin, "side": side, "sz": str(sz), "px": str(px), "startPosition": str(start), "time": t}


SWING = [fill("BTC", "B", 1, 100, 0, 0), fill("BTC", "A", 1, 110, 1, 10 * H)]           # 10 h gehalten
SCALP = [fill("ETH", "B", 1, 100, 0, i * 120_000) if i % 2 == 0 else
         fill("ETH", "A", 1, 100, 1, i * 120_000) for i in range(20)]                    # 2 min gehalten


class FakeData:
    def __init__(self):
        self.rows = [lb_row("0xA", 500_000, 0.30), lb_row("0xB", 1_000_000, 0.15),
                     lb_row("0xSCALP", 800_000, 0.40),
                     lb_row("0xLUCKY", 200_000, 50.0), lb_row("0xSMALL", 5_000, 0.5),
                     lb_row("0xLOSER", 500_000, 0.2, week_pnl=-5)]
        self.prices = {"BTC": 100_000.0, "ETH": 4_000.0, "SOL": 200.0}
        self.accts = {
            "0xa": {"accountValue": 500_000, "positions": {"BTC": {"szi": 5.0, "entryPx": 95_000}}},
            "0xb": {"accountValue": 1_000_000, "positions": {"ETH": {"szi": -250.0, "entryPx": 4_100}}},
        }
        self.fills = {"0xa": SWING, "0xb": SWING, "0xscalp": SCALP}

    def leaderboard(self): return self.rows
    def mids(self): return dict(self.prices)
    def meta(self): return {"BTC": {"szDecimals": 5}, "ETH": {"szDecimals": 4}, "SOL": {"szDecimals": 2}}
    def user_fills(self, a): return self.fills.get(a, [])
    def account(self, a): return copy.deepcopy(self.accts.get(a, {"accountValue": 1, "positions": {}}))


@pytest.fixture
def bot(tmp_path):
    cfg = copy.deepcopy(CFG)
    cfg["state_file"] = str(tmp_path / "state.json")
    cfg["telegram"]["daily_report_hour_utc"] = 24  # Tagesbericht in Tests aus
    data = FakeData()
    return CopyBot(cfg, data=data, broker=PaperBroker(cfg["state_file"], 1000), notifier=Notifier("", "")), data


def test_ranking_filters_bad_traders():
    assert [c["address"] for c in rank_traders(FakeData().rows, CFG["selection"])] == ["0xscalp", "0xa", "0xb"]


def test_scalper_is_skipped(bot):
    b, _ = bot
    b.refresh_leaders(force=True)
    assert [t["address"] for t in b.leaders] == ["0xa", "0xb"]


def test_holding_stats():
    assert holding_stats(SWING)["median_hold_min"] == 600
    s = holding_stats(SCALP)
    assert s["median_hold_min"] == 2 and is_scalper(s, CFG["selection"])
    assert not is_scalper(holding_stats(SWING), CFG["selection"])


def test_copies_buy_sell_flip_and_close(bot):
    b, data = bot
    orders = b.step()
    pos = b.broker.positions()
    assert pos["BTC"] > 0 and pos["ETH"] < 0
    # 1000 * 0.8 / 2 Trader * 1x Hebel * 0.5 = 200 USD je Position
    assert pos["BTC"] * 100_000 == pytest.approx(200, rel=0.01)
    assert {o["reason"] for o in orders} == {"open"}
    assert any("Eröffnet BTC LONG" in m for m in b.notifier.sent)

    data.accts["0xa"]["positions"]["BTC"]["szi"] = 10.0
    assert [o["reason"] for o in b.step() if o["coin"] == "BTC"] == ["increase"]

    data.accts["0xb"]["positions"]["ETH"]["szi"] = 250.0
    assert [o["reason"] for o in b.step() if o["coin"] == "ETH"] == ["flip"]
    assert b.broker.positions()["ETH"] > 0

    data.accts["0xa"]["positions"] = {}
    b.step()
    assert "BTC" not in b.broker.positions()
    assert b.step() == []


def test_stop_loss_and_cooldown(bot):
    b, data = bot
    b.step()
    sl = b.broker.state["positions"]["BTC"]["sl"]
    assert sl == pytest.approx(b.broker.state["positions"]["BTC"]["entryPx"] * 0.92)
    data.prices["BTC"] = 90_000  # -10 % -> Stop-Loss
    b.step()
    assert "BTC" not in b.broker.positions()          # geschlossen
    assert "BTC" in b.state["cooldown"]               # und nicht sofort wieder gekauft
    assert any("Stop-Loss" in m for m in b.notifier.sent)
    b.state["cooldown"]["BTC"]["until"] = time.time() - 1  # Pause vorbei
    b.step()
    assert b.broker.positions().get("BTC", 0) > 0


def test_losing_trader_gets_benched(bot):
    b, data = bot
    b.step()
    data.prices["ETH"] = 4_250  # ETH-Short von Trader B verliert, aber noch kein Stop
    b.step()
    assert b.state["trader_stats"]["0xb"]["pnl"] < 0 and b.state["trader_stats"]["0xa"]["pnl"] == 0
    data.prices["ETH"] = 4_300
    b.cfg["selection"]["drop_trader_loss_pct"] = 0.02
    b.step()
    assert "0xb" in b.state["benched"]
    assert "0xb" not in [t["address"] for t in b.leaders]
    assert "ETH" not in b.broker.positions()


def test_kill_switch_persists(bot):
    b, _ = bot
    b.step()
    b.state["peak_equity"] = 2000
    b.step()
    assert b.halted and b.broker.positions() == {}
    assert b.step() == []          # bleibt gestoppt
    b.reset_halt()
    assert not b.halted


def test_risk_caps():
    t = apply_risk({"BTC": 900, "ETH": -900, "DOGE": 50}, 1000, {**CFG["risk"], "blocked_coins": ["DOGE"]})
    assert t == {"BTC": 350, "ETH": -350}


def test_small_changes_ignored():
    assert plan_orders({"BTC": 205}, {"BTC": 0.002}, {"BTC": 100_000}, CFG["copy"]) == []


def test_paper_pnl(tmp_path):
    br = PaperBroker(str(tmp_path / "s.json"), 1000)
    br.execute("BTC", 0.01, 100_000, 5, 0)
    assert br.equity({"BTC": 110_000}) == pytest.approx(1000 + 100 - 0.45, rel=1e-3)
    br.execute("BTC", -0.01, 110_000, 5, 0)
    assert br.positions() == {}


def test_backtest():
    r = backtest_fills(SWING, scale=1.0, final_mids={}, alloc=100, penalty=0)
    assert r["pnl"] == pytest.approx(10 - 210 * 0.00045)
    assert r["trades"] == 2 and r["median_hold_min"] == 600


def test_report(bot):
    b, _ = bot
    b.step()
    txt = b.report_text()
    assert "BTC LONG" in txt and "Gewinn je Trader" in txt


def test_round_px():
    assert round_px(97123.456, 5) == 97123.0
    assert round_px(0.000123456, 0) == 0.000123
