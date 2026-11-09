import copy
import time

import pytest

from copybot.meme.broker import PaperMemeBroker
from copybot.meme.chain import LAMPORTS, SOL_MINT, USDC_MINT
from copybot.meme.engine import MemeEngine
from copybot.meme.parse import parse_swap
from copybot.meme.safety import check_token
from copybot.notify import Notifier
from tests.test_bot import CFG

W = "Leader1111111111111111111111111111111111111"
MINT = "Meme111111111111111111111111111111111111pump"


def tb(owner, mint, amount, dec=6):
    return {"owner": owner, "mint": mint, "uiTokenAmount": {"uiAmountString": str(amount), "decimals": dec}}


def tx(sol_before, sol_after, pre_tok, post_tok, mint=MINT, wallet=W, err=None, extra_pre=(), extra_post=(), t=None):
    return {"blockTime": t or int(time.time()), "transaction": {"signatures": ["sig"], "message": {
        "accountKeys": [{"pubkey": wallet}, {"pubkey": "Pool"}]}},
        "meta": {"err": err, "fee": 5000, "preBalances": [int(sol_before * LAMPORTS), 0],
                 "postBalances": [int(sol_after * LAMPORTS) - 5000, 0],
                 "preTokenBalances": [tb(wallet, mint, pre_tok)] + list(extra_pre),
                 "postTokenBalances": [tb(wallet, mint, post_tok)] + list(extra_post)}}


# ---------------------------------------------------------------- Erkennen von Swaps
def test_parse_buy_and_sell():
    b = parse_swap(tx(10, 9, 0, 1_000_000), W)
    assert b["side"] == "buy" and b["quote_sol"] == pytest.approx(1) and b["price_sol"] == pytest.approx(1e-6)
    s = parse_swap(tx(9, 9.5, 1_000_000, 250_000), W)
    assert s["side"] == "sell" and s["tokens"] == 750_000 and s["pre_tokens"] == 1_000_000


def test_parse_usdc_buy_and_ignored_cases():
    usdc = tx(10, 10, 0, 500, extra_pre=[tb(W, USDC_MINT, 300)], extra_post=[tb(W, USDC_MINT, 100)])
    ev = parse_swap(usdc, W, sol_usd=200)
    assert ev["side"] == "buy" and ev["quote_sol"] == pytest.approx(1.0)
    assert parse_swap(tx(10, 9, 0, 100, err={"x": 1}), W) is None             # fehlgeschlagen
    assert parse_swap(tx(10, 10, 0, 100), W) is None                          # Airdrop, kein Kauf
    other = tx(10, 10, 0, 100, extra_pre=[tb(W, "Other", 50)], extra_post=[tb(W, "Other", 0)])
    assert parse_swap(other, W) is None                                       # Token->Token mehrdeutig
    assert parse_swap(tx(10, 9, 0, 100), "AndereWallet") is None


# ---------------------------------------------------------------- Fakes
class FakeMarket:
    def __init__(self):
        self.price_sol = {MINT: 1e-6}
        self.liq, self.danger, self.sol = 50_000, [], 200.0

    def token_info(self, mint):
        return {"symbol": "PEPE2", "price_sol": self.price_sol[mint], "price_usd": self.price_sol[mint] * self.sol,
                "liquidity_usd": self.liq, "fdv": 1e6, "url": "https://dexscreener.com/solana/x"}

    def rugcheck(self, mint):
        return {"score": 1, "danger": self.danger, "warn": []}

    def prices_usd(self, mints):
        return {m: self.price_sol[m] * self.sol for m in mints if m in self.price_sol}

    def sol_usd(self):
        return self.sol

    def quote(self, i, o, amount, slip):
        if i == SOL_MINT:  # SOL -> Token (6 Dezimalen)
            return {"outAmount": str(int(amount / LAMPORTS / self.price_sol[o] * 1e6)), "priceImpactPct": "0.01"}
        return {"outAmount": str(int(amount / 1e6 * self.price_sol[i] * LAMPORTS)), "priceImpactPct": "0.01"}


class FakeRPC:
    def __init__(self):
        self.sigs, self.txs, self.mint = [], {}, {"decimals": 6, "mintAuthority": None, "freezeAuthority": None}

    def signatures(self, address, until=None, limit=15):
        out = []
        for s in self.sigs:  # neueste zuerst
            if s["signature"] == until:
                break
            out.append(s)
        return out[:limit]

    def transaction(self, sig):
        return self.txs[sig]

    def mint_info(self, mint):
        return self.mint

    def push(self, sig, t):
        self.sigs.insert(0, {"signature": sig, "err": None})
        self.txs[sig] = t


@pytest.fixture
def engine(tmp_path):
    cfg = copy.deepcopy(CFG)
    cfg["meme"]["wallets"] = [W]
    market, rpc = FakeMarket(), FakeRPC()
    rpc.push("old", tx(10, 9, 0, 1))
    e = MemeEngine(cfg, Notifier("", ""), market=market, rpc=rpc, state_file=str(tmp_path / "meme.json"))
    e.broker = PaperMemeBroker(e.ms, market, 300)
    e.tick()  # erster Durchlauf: nur merken, nichts kopieren
    return e, market, rpc


def buy_signal(rpc, sig="b1", sol=1.0, tokens=1_000_000):
    rpc.push(sig, tx(10, 10 - sol, 0, tokens))


# ---------------------------------------------------------------- Engine
def test_history_not_copied_then_buy_copied(engine):
    e, m, rpc = engine
    assert e.ms["positions"] == {}
    buy_signal(rpc)
    e.tick()
    pos = e.ms["positions"][MINT]
    assert pos["symbol"] == "PEPE2" and pos["cost_sol"] == pytest.approx(0.05 + 0.0003)
    assert e.ms["sol"] == pytest.approx(2.0 - 0.0503)
    assert any("Memecoin gekauft" in x for x in e.notifier.sent)


@pytest.mark.parametrize("setup,reason", [
    (lambda m, r: setattr(m, "liq", 1000), "Liquidität"),
    (lambda m, r: r.mint.update(mintAuthority="Dev"), "drucken"),
    (lambda m, r: r.mint.update(freezeAuthority="Dev"), "einfrieren"),
    (lambda m, r: setattr(m, "danger", ["Single holder ownership"]), "RugCheck"),
    (lambda m, r: m.price_sol.update({MINT: 1.5e-6}), "seit Kauf"),
])
def test_unsafe_tokens_are_not_bought(engine, setup, reason):
    e, m, rpc = engine
    setup(m, rpc)
    buy_signal(rpc)
    e.tick()
    assert MINT not in e.ms["positions"]
    skip = e.ms["events"][-1]
    assert skip["kind"] == "skip" and any(reason in r for r in skip["reasons"])


def test_old_and_small_signals_ignored(engine):
    e, m, rpc = engine
    rpc.push("late", tx(10, 9, 0, 1_000_000, t=int(time.time()) - 600))
    e.tick()
    assert "zu alt" in e.ms["events"][-1]["reasons"][0]
    buy_signal(rpc, "tiny", sol=0.05)
    e.tick()
    assert "zu klein" in e.ms["events"][-1]["reasons"][0]


def test_follow_partial_leader_sell(engine):
    e, m, rpc = engine
    buy_signal(rpc)
    e.tick()
    held = e.ms["positions"][MINT]["tokens"]
    rpc.push("s1", tx(9, 9.5, 1_000_000, 500_000))   # Trader verkauft 50 %
    e.tick()
    assert e.ms["positions"][MINT]["tokens"] == pytest.approx(held / 2)
    rpc.push("s2", tx(9.5, 10, 500_000, 0))          # Rest
    e.tick()
    assert MINT not in e.ms["positions"]
    assert e.ms["leaders"][W]["trades"] == 1


def test_stop_loss(engine):
    e, m, rpc = engine
    buy_signal(rpc)
    e.tick()
    m.price_sol[MINT] = 0.6e-6
    e.tick()
    assert MINT not in e.ms["positions"]
    assert e.ms["day"]["pnl_sol"] < 0 and "Stop-Loss" in e.ms["events"][-1]["reason"]


def test_take_profit_then_trailing(engine):
    e, m, rpc = engine
    buy_signal(rpc)
    e.tick()
    m.price_sol[MINT] = 2.2e-6
    e.tick()
    pos = e.ms["positions"][MINT]
    assert pos["tp_done"] and e.ms["events"][-1]["reason"].startswith("Take-Profit")
    m.price_sol[MINT] = 4e-6
    e.tick()
    assert MINT in e.ms["positions"]                    # läuft weiter mit
    m.price_sol[MINT] = 2.7e-6                          # >30 % unter Hoch
    e.tick()
    assert MINT not in e.ms["positions"] and e.ms["closed"][-1]["pnl_sol"] > 0.05


def test_time_limit(engine):
    e, m, rpc = engine
    buy_signal(rpc)
    e.tick()
    e.ms["positions"][MINT]["opened"] -= 25 * 3600
    e.tick()
    assert "Zeitlimit" in e.ms["events"][-1]["reason"]


def test_losing_wallet_gets_benched(engine):
    e, m, rpc = engine
    e.c["drop_leader_loss_sol"] = 0.01
    buy_signal(rpc)
    e.tick()
    m.price_sol[MINT] = 0.5e-6
    e.tick()
    assert e.ms["benched"][W] > time.time()
    m.price_sol[MINT] = 1e-6
    buy_signal(rpc, "b2")
    e.tick()
    assert "gesperrt" in e.ms["events"][-1]["reasons"][0]


def test_limits_and_agent_pause(engine):
    e, m, rpc = engine
    e.ms["day"]["pnl_sol"] = -1
    buy_signal(rpc)
    e.tick()
    assert "Verlustlimit" in e.ms["events"][-1]["reasons"][0]
    e.ms["day"]["pnl_sol"] = 0
    e.overlay_fn = lambda: {"meme": 0.0}
    buy_signal(rpc, "b2")
    e.tick()
    assert "pausiert" in e.ms["events"][-1]["reasons"][0]
    e.overlay_fn = lambda: {"meme": 0.5}
    buy_signal(rpc, "b3")
    e.tick()
    assert e.ms["positions"][MINT]["cost_sol"] == pytest.approx(0.025 + 0.0003)


def test_state_survives_restart(engine, tmp_path):
    e, m, rpc = engine
    buy_signal(rpc)
    e.tick()
    e2 = MemeEngine(e.cfg, Notifier("", ""), market=m, rpc=rpc, state_file=e.state_file)
    assert MINT in e2.ms["positions"] and e2.ms["last_sig"][W] == "b1"
    s = e2.summary()
    assert s["positionen"][0]["symbol"] == "PEPE2" and s["wallets"][0]["copied"] == 1


def test_safety_direct():
    m, r = FakeMarket(), FakeRPC()
    ok, reasons, info = check_token(MINT, m, r, CFG["meme"], leader_price_sol=1e-6)
    assert ok and info["symbol"] == "PEPE2"


def test_live_broker_signs_jupiter_transaction(monkeypatch):
    """Baut eine Transaktion wie Jupiter (unsigniert), lässt den LiveBroker signieren und prüft die Signatur."""
    import base64

    from solders.hash import Hash
    from solders.keypair import Keypair
    from solders.message import MessageV0
    from solders.system_program import TransferParams, transfer
    from solders.transaction import VersionedTransaction

    from copybot.meme.broker import LiveMemeBroker

    kp = Keypair()
    monkeypatch.setenv("SOLANA_PRIVATE_KEY", str(kp))
    msg = MessageV0.try_compile(kp.pubkey(), [transfer(TransferParams(from_pubkey=kp.pubkey(), to_pubkey=Keypair().pubkey(),
                                                                     lamports=1))], [], Hash.default())
    unsigned = VersionedTransaction.populate(msg, [Keypair().sign_message(b"x")])  # Platzhalter-Signatur
    sent = {}

    class M:
        def swap_tx(self, quote, user):
            assert user == str(kp.pubkey())
            return base64.b64encode(bytes(unsigned)).decode()

    class R:
        def send_raw(self, b64):
            sent["tx"] = VersionedTransaction.from_bytes(base64.b64decode(b64))
            return "SIG"

        def confirmed(self, sig):
            return True

    br = LiveMemeBroker({}, M(), R(), 300)
    assert br.address == str(kp.pubkey())
    assert br._send({"q": 1}) == "SIG"
    tx = sent["tx"]
    from solders.message import to_bytes_versioned
    assert tx.signatures[0] == kp.sign_message(to_bytes_versioned(tx.message))  # echte Signatur der Bot-Wallet
