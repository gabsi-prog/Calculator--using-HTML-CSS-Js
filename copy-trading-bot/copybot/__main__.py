"""Start: python -m copybot [--config config.yaml] [--once] [--leaders]"""
import argparse
import logging
import os
import sys

import yaml

from .bot import CopyBot


def load_env(path=".env"):
    if os.path.exists(path):
        for line in open(path):
            line = line.split("#", 1)[0].strip()
            if "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def main():
    ap = argparse.ArgumentParser(description="Hyperliquid Copy-Trading-Bot")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--once", action="store_true", help="nur einen Durchlauf ausführen")
    ap.add_argument("--leaders", action="store_true", help="nur die ausgewählten Top-Trader anzeigen")
    args = ap.parse_args()

    path = args.config if os.path.exists(args.config) else "config.example.yaml"
    with open(path) as f:
        cfg = yaml.safe_load(f)
    load_env()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler(cfg.get("log_file", "bot.log"))],
    )
    if cfg["mode"] == "live":
        logging.warning("!!! LIVE-MODUS: Es werden echte Orders mit echtem Geld platziert !!!")

    bot = CopyBot(cfg)
    if args.leaders:
        bot.refresh_leaders(force=True)
    elif args.once:
        bot.step()
    else:
        bot.run()


if __name__ == "__main__":
    main()
