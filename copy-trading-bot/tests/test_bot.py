import copy
import logging

import pytest
import yaml

from copybot.bot import CopyBot
from copybot.broker import PaperBroker
from copybot.selector import select_traders
from copybot.strategy import apply_risk, plan_orders, target_exposures

CFG = yaml.safe_load(open("config.example.yaml"))


def lb_row(addr, acct, month_roi, week_pnl=1000, alltime=500_000, vlm=5_000_000, day_pnl=10):
    return {
        "ethAddress": addr,
        "accountValue": str(acct),
        "displayName": None,
        "windowPerformances": [
            ["day", {"pnl": str(day_pnl), "roi": "0.01", "vlm": "1"}],
            ["week", {"pnl": str(week_pnl), "roi": "0.02", "vlm": "1"}],
            ["month", {"pnl": "1000", "roi": str(month_roi), "vlm": str(vlm)}],
            ["allTime", {"pnl": str(alltime), "roi": "1", "vlm": "1"}],
        ],
    }


class FakeData:
    def __init__(self):
        self.rows = [
            lb_row("0xA", 500_000, 0.30),
            lb_row("0xB", 1_000_000, 0.15),
            lb_row("0xLUCKY", 200_000, 50.0),       # zu hoher ROI -> Glück
            lb_row("0xSMALL", 5_000, 0.5),          # zu kleines Konto
            lb_row("0xLOSER", 500_000, 0.2, week_pnl=-5),  # Woche negativ
        ]
        self.prices = {"BTC": 100_000.0, "ETH": 4_000.0, "SOL": 200.0}
        self.accts = {
            "0xa": {"accountValue": 500_000, "positions": {"BTC": {"szi": 5.0, "entryPx": 95_000}}},   # 1x long BTC
            "0xb": {"accountValue": 1_000_000, "positions": {"ETH": {"szi": -250.0, "entryPx": 4_100}}},  # 1x short ETH
        }

    def leaderboard(self):
        return self.rows

    def mids(self):
        return dict(self.prices)

    def meta(self):
        return {"BTC": {"szDecimals": 5}, "ETH": {"szDecimals": 4}, "SOL": {"szDecimals": 2}}

    def account(self, addr):
        return copy.deepcopy(self.accts.get(addr, {"accountValue": 1, "positions": {}}))


@pytest.fixture
def bot(tmp_path):
    cfg = copy.deepcopy(CFG)
    cfg["state_file"] = str(tmp_path / "state.json")
    data = FakeData()
    return CopyBot(cfg, data=data, broker=PaperBroker(cfg["state_file"], 1000)), data


def test_selection_filters_bad_traders():
    picked = select_traders(FakeData().rows, CFG["selection"])
    assert [p["address"] for p in picked] == ["0xa", "0xb"]


def test_copies_buy_sell_flip_and_close(bot, caplog):
    caplog.set_level(logging.INFO)
    b, data = bot
    # 1) Trader halten Positionen -> Bot eröffnet: BTC long, ETH short
    orders = b.step()
    pos = b.broker.positions()
    assert pos["BTC"] > 0 and pos["ETH"] < 0
    # 1000 * 0.8 / 2 Trader * 1x Hebel * 0.5 copy_ratio = 200 USD je Position
    assert pos["BTC"] * 100_000 == pytest.approx(200, rel=0.01)
    assert {o["reason"] for o in orders} == {"open"}

    # 2) Trader A kauft nach (verdoppelt) -> Bot kauft nach
    data.accts["0xa"]["positions"]["BTC"]["szi"] = 10.0
    orders = b.step()
    assert [o["reason"] for o in orders if o["coin"] == "BTC"] == ["increase"]

    # 3) Trader B dreht ETH auf long -> Bot dreht auch
    data.accts["0xb"]["positions"]["ETH"]["szi"] = 250.0
    orders = b.step()
    assert [o["reason"] for o in orders if o["coin"] == "ETH"] == ["flip"]
    assert b.broker.positions()["ETH"] > 0

    # 4) Trader A verkauft alles -> Bot schließt BTC
    data.accts["0xa"]["positions"] = {}
    orders = b.step()
    assert "BTC" not in b.broker.positions()

    # 5) Nichts ändert sich -> keine Orders (keine unnötigen Gebühren)
    assert b.step() == []


def test_risk_caps():
    t = apply_risk({"BTC": 900, "ETH": -900, "DOGE": 50}, 1000,
                   {**CFG["risk"], "blocked_coins": ["DOGE"]})
    assert "DOGE" not in t
    assert t["BTC"] == 350 and t["ETH"] == -350  # max_position_pct 35 %


def test_kill_switch(bot):
    b, data = bot
    b.step()
    b.broker.state["peak_equity"] = 2000  # simuliert: -50 % vom Hoch
    b.step()
    assert b.halted and b.broker.positions() == {}


def test_small_changes_ignored():
    orders = plan_orders({"BTC": 205}, {"BTC": 0.002}, {"BTC": 100_000}, CFG["copy"])
    assert orders == []


def test_paper_pnl(tmp_path):
    br = PaperBroker(str(tmp_path / "s.json"), 1000)
    br.execute("BTC", 0.01, 100_000, 5, 0)
    assert br.equity({"BTC": 110_000}) == pytest.approx(1000 + 100 - 0.45, rel=1e-3)
    br.execute("BTC", -0.01, 110_000, 5, 0)
    assert br.positions() == {}
    assert br.state["cash"] == pytest.approx(1000 + 100 - 0.45 - 0.495, rel=1e-3)
