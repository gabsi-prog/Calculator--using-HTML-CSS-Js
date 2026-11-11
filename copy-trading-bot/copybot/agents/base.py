"""Gemeinsame Basis für alle Agenten: Claude-Aufruf, Kostenmessung, Budget."""
from __future__ import annotations

import datetime as dt
import json
import logging
import time

log = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-opus-5-5"
# USD pro 1 Mio. Tokens (Eingabe, Ausgabe) und pro Websuche – zur Kostenkontrolle
PRICES = {"claude-opus-5-5": (4.0, 20.0)}
WEB_SEARCH_USD = 0.01


class BudgetExceeded(Exception):
    pass


class CostTracker:
    def __init__(self, state: dict, monthly_budget: float):
        self.state, self.budget = state, monthly_budget
        month = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m")
        c = state.setdefault("agent_costs", {})
        if c.get("month") != month:
            c.clear()
            c.update({"month": month, "usd": 0.0, "calls": 0})
        self.c = c

    def check(self):
        if self.c["usd"] >= self.budget:
            raise BudgetExceeded(f"Monatsbudget für Agenten erreicht ({self.c['usd']:.2f} / {self.budget:.2f} USD)")

    def add(self, model: str, usage) -> float:
        pin, pout = PRICES.get(model, (4.0, 20.0))
        inp = (getattr(usage, "input_tokens", 0) or 0) + (getattr(usage, "cache_creation_input_tokens", 0) or 0)
        out = getattr(usage, "output_tokens", 0) or 0
        searches = getattr(getattr(usage, "server_tool_use", None), "web_search_requests", 0) or 0
        usd = inp / 1e6 * pin + out / 1e6 * pout + searches * WEB_SEARCH_USD
        self.c["usd"] = round(self.c["usd"] + usd, 4)
        self.c["calls"] += 1
        return usd


class Agent:
    """Ein Spezialist. Unterklassen setzen key/name/emoji/role/system und implementieren build_input()."""

    key = "agent"
    name = "Agent"
    emoji = "🤖"
    role = ""
    system = ""
    effort = "medium"
    tools: list = []
    schema: dict | None = None  # gesetzt -> strukturierte JSON-Antwort

    def __init__(self, client, model: str, costs: CostTracker):
        self.client, self.model, self.costs = client, model, costs

    def build_input(self, ctx: dict) -> str:
        raise NotImplementedError

    def run(self, ctx: dict) -> dict:
        self.costs.check()
        started = time.time()
        messages = [{"role": "user", "content": self.build_input(ctx)}]
        output_config = {"effort": self.effort}
        if self.schema:
            output_config["format"] = {"type": "json_schema", "schema": self.schema}
        resp = None
        for _ in range(4):  # pause_turn bei langen Websuchen fortsetzen
            kwargs = dict(model=self.model, max_tokens=16000, system=self.system, messages=messages,
                          output_config=output_config, betas=["server-side-fallback-2026-07-01"], fallbacks="default")
            if self.tools:
                kwargs["tools"] = self.tools
            resp = self.client.beta.messages.create(**kwargs)
            self.costs.add(self.model, resp.usage)
            if resp.stop_reason == "pause_turn":
                messages.append({"role": "assistant", "content": resp.content})
                continue
            break
        if resp.stop_reason == "refusal":
            raise RuntimeError(f"{self.name}: Anfrage abgelehnt")
        text = "\n".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()
        report = {"key": self.key, "name": self.name, "emoji": self.emoji, "role": self.role,
                  "t": time.time(), "dauer_s": round(time.time() - started, 1), "ok": True}
        if self.schema:
            report["data"] = json.loads(text)
            report["text"] = report["data"].get("zusammenfassung", "")
        else:
            report["text"] = text
        return report


def compact(obj, max_chars: int = 60_000) -> str:
    s = json.dumps(obj, ensure_ascii=False, default=str, separators=(",", ":"))
    return s[:max_chars]
