"""Daten für das Web-Dashboard + eingebauter Webserver.

Ist DASHBOARD_PASSWORD gesetzt, wird data.json verschlüsselt (AES-256-GCM, Schlüssel per PBKDF2 aus dem
Passwort). Das Dashboard entschlüsselt erst im Browser – so kann es sogar öffentlich (GitHub Pages) liegen.
"""
from __future__ import annotations

import base64
import functools
import http.server
import json
import logging
import os
import shutil
import threading
import time

from .tuning import TUNABLE, param

log = logging.getLogger(__name__)
STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dashboard")
PBKDF2_ITER = 200_000


def build_data(bot) -> dict:
    st, cfg = bot.state, bot.cfg
    mids = bot.data.mids()
    equity = bot.broker.equity(mids)
    peak = st.get("peak_equity") or equity
    start = cfg["paper_start_balance"] if cfg["mode"] == "paper" else st.get("start_equity", equity)
    j = st.get("journal", {})
    agents = st.get("agents", {})
    return {
        "generiert": time.time(),
        "modus": cfg["mode"],
        "gestoppt": st.get("halted", False),
        "konto": {"wert": equity, "start": start, "hoechststand": peak,
                  "drawdown": 1 - equity / peak if peak else 0, "kill_switch_bei": cfg["risk"]["max_drawdown_pct"],
                  "risikobremse": st.get("throttle", 1.0), "trades": st.get("trades", 0)},
        "kurve": st.get("equity_curve", [])[-1500:],
        "positionen": bot.broker.position_details(mids),
        "trader": [{**{k: t.get(k) for k in ("address", "name", "monthRoi", "median_hold_min", "accountValue", "pinned")},
                    "gewicht": st.get("weights", {}).get(t["address"], 1.0),
                    "gewinn": st["trader_stats"].get(t["address"], {}).get("pnl", 0.0),
                    "vertrauen": (st.get("agent_overlay") or {}).get("trader", {}).get(t["address"], 1.0)}
                   for t in bot.leaders],
        "agenten": {"t": agents.get("t"), "model": agents.get("model"),
                    "berichte": list(agents.get("reports", {}).values()),
                    "entscheidung": st.get("agent_overlay"), "kosten": st.get("agent_costs", {}),
                    "intervall_h": cfg.get("agents", {}).get("interval_hours", 8)},
        "ki_wochenanalyse": (j.get("reviews") or [None])[-1],
        "lernen": {"parameter": {k: {"wert": param(cfg, st, k), "config": cfg[k.split(".")[0]][k.split(".")[1]]}
                                 for k in TUNABLE},
                   "aenderungen": j.get("changes", [])[-30:]},
        "aktivitaet": {"trades": j.get("trades", [])[-60:], "stops": j.get("stops", [])[-20:],
                       "fehler": j.get("errors", [])[-30:]},
        "meme": bot.meme.summary() if getattr(bot, "meme", None) else {"aktiv": False},
        "sperren": {"cooldown": st.get("cooldown", {}), "quarantaene": st.get("quarantine", {}),
                    "aussortiert": st.get("benched", {})},
    }


def encrypt(payload: dict, password: str) -> dict:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    salt, iv = os.urandom(16), os.urandom(12)
    key = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=PBKDF2_ITER).derive(password.encode())
    ct = AESGCM(key).encrypt(iv, json.dumps(payload, default=str).encode(), None)
    b64 = lambda b: base64.b64encode(b).decode()  # noqa: E731
    return {"verschluesselt": True, "iter": PBKDF2_ITER, "salt": b64(salt), "iv": b64(iv), "daten": b64(ct)}


def write_data(bot, path: str):
    data = build_data(bot)
    pw = os.environ.get("DASHBOARD_PASSWORD", "").strip()
    out = encrypt(data, pw) if pw else data
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(out, f, default=str)
    os.replace(tmp, path)


def export_site(bot, out_dir: str):
    """Statische Dateien + data.json in einen Ordner (für GitHub Pages)."""
    shutil.copytree(STATIC_DIR, out_dir, dirs_exist_ok=True)
    write_data(bot, os.path.join(out_dir, "data.json"))


class _Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, data_path=None, **kw):
        self.data_path = data_path
        super().__init__(*a, directory=STATIC_DIR, **kw)

    def do_GET(self):
        if self.path.split("?")[0] == "/data.json":
            try:
                body = open(self.data_path, "rb").read()
            except OSError:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

    def log_message(self, *a):
        pass


def start_server(bot, port: int, refresh_sec: int = 15):
    data_path = os.path.abspath(f"dashboard-data-{bot.cfg['mode']}.json")

    def refresher():
        while True:
            try:
                with bot.lock:
                    write_data(bot, data_path)
            except Exception as e:
                log.warning("Dashboard-Daten nicht aktualisiert: %s", e)
            time.sleep(refresh_sec)

    threading.Thread(target=refresher, daemon=True, name="dash-data").start()
    handler = functools.partial(_Handler, data_path=data_path)
    srv = http.server.ThreadingHTTPServer(("0.0.0.0", port), handler)
    threading.Thread(target=srv.serve_forever, daemon=True, name="dash-http").start()
    log.info("Dashboard läuft: http://localhost:%d  (auf dem Server: http://DEINE_IP:%d)", port, port)
    return srv
