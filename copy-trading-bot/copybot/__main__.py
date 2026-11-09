"""Start:
  python -m copybot                 Dauerbetrieb
  python -m copybot --once          ein Durchlauf (für GitHub Actions)
  python -m copybot --leaders       zeigt die ausgewählten Top-Trader
  python -m copybot --backtest      Backtest der ausgewählten Trader (oder: --backtest 0xADRESSE ...)
  python -m copybot --report        Tagesbericht jetzt senden
  python -m copybot --telegram-test Testnachricht an Telegram
  python -m copybot --reset-halt    Kill-Switch zurücksetzen
"""
import argparse
import logging
import os
import sys

import yaml

from .backtest import format_results, run_backtest
from .bot import CopyBot
from .notify import Notifier


def load_env(path=".env"):
    if os.path.exists(path):
        for line in open(path):
            line = line.split("#", 1)[0].strip()
            if "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def load_config(path: str) -> dict:
    with open(path) as f:
        cfg = yaml.safe_load(f)
    cfg["mode"] = (os.environ.get("COPYBOT_MODE") or cfg.get("mode") or "paper").strip().lower()
    if cfg["mode"] not in ("paper", "live"):
        raise SystemExit(f"Unbekannter Modus: {cfg['mode']} (erlaubt: paper, live)")
    cfg["state_file"] = cfg.get("state_file", "state-{mode}.json").format(mode=cfg["mode"])
    return cfg


def main():
    ap = argparse.ArgumentParser(description="Hyperliquid Copy-Trading-Bot")
    ap.add_argument("--config", default="config.yaml")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--once", action="store_true")
    g.add_argument("--leaders", action="store_true")
    g.add_argument("--backtest", nargs="*", metavar="ADRESSE")
    g.add_argument("--report", action="store_true")
    g.add_argument("--telegram-test", action="store_true")
    g.add_argument("--reset-halt", action="store_true")
    args = ap.parse_args()

    load_env()
    cfg = load_config(args.config)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s",
                        handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler(cfg.get("log_file", "bot.log"))])

    if args.telegram_test:
        n = Notifier()
        if not n.enabled:
            raise SystemExit("TELEGRAM_BOT_TOKEN und TELEGRAM_CHAT_ID sind nicht gesetzt.")
        ok = n.send("✅ Telegram funktioniert! Dein Copy-Bot kann dir jetzt Nachrichten schicken.")
        raise SystemExit(0 if ok else "Senden fehlgeschlagen – Token/Chat-ID prüfen (Log oben).")

    if cfg["mode"] == "live":
        logging.warning("!!! LIVE-MODUS: Es werden echte Orders mit echtem Geld platziert !!!")
    bot = CopyBot(cfg)

    if args.leaders:
        bot.refresh_leaders(force=True)
        bot.broker.save()
    elif args.backtest is not None:
        addrs = [a.lower() for a in args.backtest]
        if not addrs:
            bot.refresh_leaders()
            addrs = [t["address"] for t in bot.leaders]
        text = format_results(run_backtest(bot.data, addrs, cfg))
        print(text)
        bot.notifier.send("🧪 " + text)
    elif args.report:
        text = bot.report_text()
        print(text)
        bot.notifier.send(text)
    elif args.reset_halt:
        bot.reset_halt()
        bot.notifier.send("🔓 Kill-Switch zurückgesetzt – Bot handelt wieder.")
    elif args.once:
        try:
            bot.step()
        except Exception as e:
            bot.notifier.send(f"⚠️ Fehler im Bot: {e}")
            raise
    else:
        bot.run()


if __name__ == "__main__":
    main()
