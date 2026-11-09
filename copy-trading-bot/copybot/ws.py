"""WebSocket-Wächter: meldet sofort, wenn einer der kopierten Trader etwas ausführt."""
from __future__ import annotations

import json
import logging
import threading
import time

WS_URL = "wss://api.hyperliquid.xyz/ws"
log = logging.getLogger(__name__)


class LeaderWatcher:
    def __init__(self, get_addresses, on_activity):
        self.get_addresses = get_addresses
        self.on_activity = on_activity
        self.ws = None
        self._stop = False

    def start(self):
        threading.Thread(target=self._run, daemon=True, name="ws").start()

    def stop(self):
        self._stop = True
        self.resubscribe()

    def resubscribe(self):
        """Verbindung schließen -> wird mit der aktuellen Trader-Liste neu aufgebaut."""
        if self.ws:
            try:
                self.ws.close()
            except Exception:
                pass

    def _run(self):
        import websocket

        while not self._stop:
            addrs = list(self.get_addresses())
            alive = {"on": True}

            def on_open(ws):
                for a in addrs:
                    ws.send(json.dumps({"method": "subscribe", "subscription": {"type": "userFills", "user": a}}))
                log.info("WebSocket verbunden, beobachte %d Trader", len(addrs))

                def pinger():  # Hyperliquid trennt nach 60 s ohne Nachricht
                    while alive["on"]:
                        time.sleep(50)
                        try:
                            ws.send(json.dumps({"method": "ping"}))
                        except Exception:
                            return
                threading.Thread(target=pinger, daemon=True).start()

            def on_message(ws, msg):
                try:
                    d = json.loads(msg)
                except ValueError:
                    return
                if d.get("channel") == "userFills" and not d.get("data", {}).get("isSnapshot"):
                    self.on_activity(d["data"].get("user"))

            self.ws = websocket.WebSocketApp(WS_URL, on_open=on_open, on_message=on_message,
                                             on_error=lambda ws, e: log.warning("WebSocket-Fehler: %s", e))
            try:
                self.ws.run_forever()
            finally:
                alive["on"] = False
            if not self._stop:
                time.sleep(5)
