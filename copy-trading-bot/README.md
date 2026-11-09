# Copy-Trading-Bot (Hyperliquid)

Der Bot sucht die **besten Trader auf Hyperliquid** und **kopiert automatisch ihre Positionen**:
Kaufen sie, kauft der Bot. Kaufen sie nach, kauft er nach. Verkaufen, schließen oder drehen sie (Long ↔ Short), macht er das auch, angepasst an **deine** Kontogröße.

> **Warum Hyperliquid?** Dort sind alle Positionen aller Trader öffentlich on-chain sichtbar und es gibt ein offenes Leaderboard.
> Bei Binance, Bybit, eToro usw. gibt es dafür **keine offizielle API**. Dort kann man nur die eingebaute Copy-Funktion nutzen.

## So funktioniert er

1. **Trader-Auswahl** (alle 24 h): Das Leaderboard wird gefiltert, damit nicht nur der „Glückspilz der Woche“ kopiert wird:
   - Konto ≥ 100k USD (eigenes Geld im Spiel)
   - Monat ≥ +5 %, aber nicht > 500 % (extreme Ausreißer sind meist Zocker mit Riesenhebel)
   - Gesamtgewinn ≥ 100k USD, letzte Woche positiv, aktiv (Volumen)
   - Ranking nach Konsistenz (Tag, Woche, Monat und Gesamt im Plus) und gedämpftem ROI
2. **Positions-Spiegelung** (alle 30 s): Jeder Top-Trader bekommt einen gleichen Teil deines Kapitals.
   Hat Trader X 2× seines Kontos in BTC-Long, hältst du `2× · copy_ratio` deines Anteils in BTC-Long.
   Der Bot vergleicht Ziel und Ist und handelt nur die Differenz. Kopiert werden Positionen, nicht einzelne Orders: Verpasste Fills und doppelte Käufe gibt es so nicht.
3. **Risiko-Management**
   - Maximaler Gesamthebel (Standard 3×) und maximaler Anteil pro Coin (35 %)
   - **Kill-Switch:** bei −25 % vom Höchststand wird alles geschlossen und der Bot stoppt
   - Coin-Whitelist und -Blacklist (z. B. Memecoins sperren)
   - Kleine Abweichungen (< 10 % oder < 12 USD) werden ignoriert, das spart Gebühren

## Installation

```bash
cd copy-trading-bot
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp config.example.yaml config.yaml
```

## Benutzen

```bash
python -m copybot --leaders   # nur anzeigen, wen der Bot kopieren würde
python -m copybot --once      # einen Durchlauf machen
python -m copybot             # Dauerbetrieb (Strg+C zum Beenden)
```

Standard ist **`mode: paper`**: echte Live-Kurse und echte Trader-Positionen, aber **simuliertes Geld** (1000 USD).
Der Kontostand wird in `state.json` gespeichert, das Log steht in `bot.log`.
**Lass den Bot erst einige Wochen im Paper-Modus laufen** und prüf, ob er wirklich Gewinn macht.

### Live-Modus (echtes Geld)

1. Auf hyperliquid.xyz unter **More → API** eine **API-Wallet** erstellen. Sie kann handeln, aber **kein Geld abheben**. Deinen Haupt-Private-Key nie verwenden!
2. `cp .env.example .env` und `HL_PRIVATE_KEY` (der API-Wallet) sowie `HL_ACCOUNT_ADDRESS` (dein Hauptkonto) eintragen.
3. In `config.yaml` den Wert `mode: live` setzen und mit **kleinem Betrag** starten.

Damit er rund um die Uhr läuft, brauchst du einen kleinen VPS (z. B. Hetzner) und startest ihn dort mit `tmux`, `screen` oder als systemd-Dienst.

## Wichtige Stellschrauben (`config.yaml`)

| Parameter | Bedeutung |
|---|---|
| `selection.top_n` | Wie vielen Tradern gefolgt wird (mehr = mehr Streuung) |
| `copy.copy_ratio` | 0.5 = halb so viel Hebel wie die Trader |
| `copy.capital_usage` | Anteil des Kapitals im Einsatz |
| `risk.max_leverage` | Obergrenze für den Gesamthebel |
| `risk.max_drawdown_pct` | Kill-Switch-Schwelle |
| `selection.pinned_traders` | Adressen, die du immer kopieren willst |

## Tests

```bash
pip install pytest && python -m pytest -q tests
```

## ⚠️ Ehrliche Risiken

- **Vergangene Gewinne garantieren nichts.** Leaderboards sind voller Survivorship-Bias: Viele Top-Trader von heute sind nächsten Monat pleite.
- **Verzögerung:** Du steigst immer etwas später und zu schlechteren Kursen ein. Scalper und High-Frequency-Trader lassen sich praktisch nicht profitabel kopieren.
- **Kontext fehlt:** Ein „Top-Trader“ kann eine Absicherung (Hedge) für Positionen woanders halten. Für dich ist das dann eine nackte Wette.
- **Perps mit Hebel** können schnell liquidiert werden. Setz nur Geld ein, dessen Verlust du verkraften kannst.
- Gewinne sind steuerpflichtig (in Deutschland meist als private Veräußerungsgeschäfte bzw. Termingeschäfte; im Zweifel Steuerberater fragen).

Dies ist Software, keine Anlageberatung. Nutzung auf eigenes Risiko.
