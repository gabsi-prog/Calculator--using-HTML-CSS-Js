"""Telegram-Benachrichtigungen. Ohne TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID passiert einfach nichts."""
from __future__ import annotations

import logging
import os

import requests

log = logging.getLogger(__name__)


class Notifier:
    def __init__(self, token: str | None = None, chat_id: str | None = None):
        self.token = token or os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        self.chat_id = chat_id or os.environ.get("TELEGRAM_CHAT_ID", "").strip()
        self.sent: list[str] = []  # für Tests

    @property
    def enabled(self) -> bool:
        return bool(self.token and self.chat_id)

    def send(self, text: str) -> bool:
        self.sent.append(text)
        if not self.enabled:
            return False
        try:
            r = requests.post(
                f"https://api.telegram.org/bot{self.token}/sendMessage",
                json={"chat_id": self.chat_id, "text": text[:4000], "disable_web_page_preview": True},
                timeout=10,
            )
            if not r.ok:
                log.warning("Telegram-Fehler %s: %s", r.status_code, r.text[:200])
            return r.ok
        except requests.RequestException as e:
            log.warning("Telegram nicht erreichbar: %s", e)
            return False
