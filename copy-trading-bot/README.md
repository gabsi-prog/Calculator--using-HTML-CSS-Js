# Copy-Trading-Bot (Hyperliquid)

> 👉 **Neu hier? Folge der [Schritt-für-Schritt-Anleitung](ANLEITUNG.md).** Du brauchst keine Programmierkenntnisse.

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
   - **Stop-Loss direkt an der Börse** (Standard 8 %). Er greift auch, wenn der Bot aus ist. Danach 12 h Pause für diesen Coin
4. **Selbstkontrolle**
   - **Scalper-Filter:** Trader mit mittlerer Haltedauer unter 60 Minuten werden nicht kopiert
   - **Gewinn je Trader:** Der Bot misst, wie viel *du* mit jedem Trader verdienst. Verlierer fliegen 14 Tage raus
   - **Backtest:** `--backtest` rechnet nach, was das Kopieren zuletzt gebracht hätte
5. **Telegram:** Nachricht bei jedem Trade, Stop-Loss und Kill-Switch sowie ein Tagesbericht
6. **WebSocket:** Im Dauerbetrieb reagiert der Bot sofort, sobald ein Trader handelt

## 🐸 Memecoin-Bot (Solana)

Kopiert Solana-Wallets, die du in **FOMO** oder **Axiom** gefunden hast. Beide Apps haben keine offizielle Bot-Schnittstelle, deshalb handelt der Bot direkt on-chain (`copybot/meme/`):
- **Erkennen:** Solana-RPC → neue Transaktionen der Wallets → Kauf/Verkauf aus den Token- und SOL-Salden (SOL, WSOL und USDC/USDT als Gegenwährung)
- **Prüfen:** DexScreener (Liquidität, Kurs-Jagd), Mint-/Freeze-Authority per RPC, RugCheck, Jupiter-Preiseinfluss, Signal-Alter, Tages- und Positionslimits
- **Handeln:** Jupiter-Swap, signiert mit einer eigenen Bot-Wallet (`solders`). Im Paper-Modus mit echten Jupiter-Kursen.
- **Aussteigen:** Stop-Loss, halber Take-Profit, Trailing-Stop, Zeitlimit, anteiliges Mitverkaufen mit dem Trader
- **Lernen:** Wallets mit Verlust werden pausiert. Das KI-Team bekommt die Memecoin-Daten und kann über `memecoin_faktor` Käufe drosseln oder stoppen.

Läuft nur im Dauerbetrieb (`python -m copybot` oder `--meme`), weil bei Memecoins Sekunden zählen. Hilfen: `--meme-wallet ADRESSE`, `--meme-check MINT`.

## 🧑‍💼 KI-Agenten-Team

Alle 8 Stunden (einstellbar) arbeitet ein Team aus Claude-Agenten:

| Agent | Daten | Ergebnis |
|---|---|---|
| **Markt-Analyst** | Kerzen, Funding, Open Interest von Hyperliquid. Die Kennzahlen (RSI, SMA, Volatilität) rechnet Python, die KI interpretiert sie. | Marktlage und Warnsignale je Coin |
| **Nachrichten-Analyst** | Websuche (Claude `web_search`) | Stimmung, wichtige Meldungen, Termine, akute Risiken |
| **Trader-Analyst** | Positionen und Verhalten der kopierten Trader | Warnsignale wie Martingale, Hebel oder Klumpenrisiko |
| **Risiko-Chef** | Alle Berichte + Konto | Verbindliche JSON-Entscheidung: Gesamtgröße, Faktor je Coin, Sperren, Vertrauen je Trader |

Die drei Analysten laufen parallel. Der Risiko-Chef kann **nur bremsen**: Alle Faktoren liegen zwischen 0 und 1, Sperren dauern höchstens 72 h, und die Entscheidung verfällt nach 24 h.
Fällt ein Agent aus, entscheidet der Chef mit den übrigen Berichten. Fällt das ganze Team aus, handelt der Bot normal weiter.
Ein Monatsbudget (`agents.monthly_budget_usd`) begrenzt die Kosten hart. Code: `copybot/agents/`.

## 🖥 Dashboard „Copy-Desk“

Eine Weboberfläche (HTML/CSS/JS, ohne Build-Schritt) in `dashboard/`. Sie zeigt Kontowert mit Verlaufskurve, Drawdown bis zum Kill-Switch, KI-Team mit Markt-Ampel, Positionen, Trader mit gelernten Gewichten, Lernstand und eine filterbare Aktivitäts-Chronik.
- **Server/PC:** startet automatisch mit dem Bot unter `http://localhost:8080`
- **GitHub:** wird alle ~15 min auf GitHub Pages unter `/bot/` veröffentlicht
- **Verschlüsselt:** Mit `DASHBOARD_PASSWORD` wird `data.json` mit AES-256-GCM verschlüsselt und erst im Browser entschlüsselt
- Ohne Daten zeigt es markierte Demo-Daten

## 🧠 Selbstverbesserung

Der Bot lernt auf drei Ebenen aus seinen eigenen Ergebnissen:

| Wann | Was | Wie |
|---|---|---|
| **Jede Sekunde / jeder Durchlauf** | **Selbstheilung** | Fehlgeschlagene Orders werden erkannt und automatisch korrigiert: zu wenig Margin → halbe Größe, Preisfehler → mehr Slippage, Rundungsfehler → gröber runden, Rate-Limit → Pause. Ein Coin, der 3× in einer Stunde scheitert, kommt 6 h in Quarantäne. Fehlende Stop-Losses werden nachgesetzt. |
| | **Risikobremse** | Bei Verlusten werden die Positionen automatisch kleiner: 50 % bei halbem Weg zum Kill-Switch, mindestens 30 %. |
| **Täglich** | **Trader-Gewichte** | Trader, die *dir* Geld bringen, bekommen mehr Kapital, Verlierer weniger (Faktor 0,25 bis 2,5). |
| | **Stop-Loss lernen** | 24 h nach jedem Stop prüft der Bot: Lief der Kurs danach wieder über den Einstieg (unnötiger Stop)? Viele unnötige Stops → Stop weiter. Kaum welche → enger. Grenzen: 4–15 %. |
| | **Verzögerungs-Kosten** | Er misst, wie viel schlechter er einsteigt als der Trader. Zu teuer → kopiert nur noch Trader mit längerer Haltedauer. |
| **Wöchentlich** | **KI-Analyse (Claude)** | Liest das Tagebuch, erklärt die Woche auf Deutsch, findet Fehlerquellen und passt bis zu 3 Einstellungen an. Probleme, die Code brauchen, werden separat gemeldet. |

**Sicherheitsregel:** Gelernte Änderungen dürfen den Bot nur **vorsichtiger** machen, nie riskanter als in `config.yaml` eingestellt. Ausnahme ist der Stop-Abstand (4–15 %).
Jede Änderung landet im Tagebuch und im Telegram-Tagesbericht. `--lernstand` zeigt den aktuellen Stand, `--reset-lernen` macht alles rückgängig.

## Befehle (eigener Rechner/Server)

```bash
cd copy-trading-bot
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env              # Telegram/Keys eintragen

python -m copybot --leaders       # wen würde der Bot kopieren?
python -m copybot --backtest      # was hätte das gebracht?
python -m copybot --telegram-test # Telegram prüfen
python -m copybot --once          # ein Durchlauf
python -m copybot                 # Dauerbetrieb
python -m copybot --report        # Tagesbericht jetzt
python -m copybot --reset-halt    # nach Kill-Switch fortsetzen
python -m copybot --ki-analyse    # KI-Analyse jetzt
python -m copybot --lernstand     # was hat der Bot gelernt?
python -m copybot --reset-lernen  # Gelerntes vergessen
python -m copybot --agenten       # KI-Team jetzt analysieren lassen
python -m copybot --dashboard     # nur das Dashboard starten
python -m copybot --meme          # nur Memecoin-Bot + Dashboard
python -m copybot --meme-wallet A # erkannte Swaps einer Wallet anzeigen
python -m copybot --meme-check M  # Sicherheits-Check eines Tokens
```

Ohne eigenen Rechner läuft der Bot über **GitHub Actions** (`.github/workflows/copybot.yml`) alle 5 Minuten.
Auf einem Linux-Server richtet `bash deploy/install.sh` ihn als Dienst ein. Siehe [ANLEITUNG.md](ANLEITUNG.md).

Standard ist **`mode: paper`** mit echten Kursen, echten Trader-Positionen und **simuliertem Geld** (1000 USD).

## Wichtige Stellschrauben (`config.yaml`)

| Parameter | Bedeutung |
|---|---|
| `selection.top_n` | Wie vielen Tradern gefolgt wird (mehr = mehr Streuung) |
| `copy.copy_ratio` | 0.5 = halb so viel Hebel wie die Trader |
| `copy.capital_usage` | Anteil des Kapitals im Einsatz |
| `risk.max_leverage` | Obergrenze für den Gesamthebel |
| `risk.max_drawdown_pct` | Kill-Switch-Schwelle |
| `risk.stop_loss_pct` | Stop-Loss-Abstand vom Einstiegspreis |
| `selection.min_median_hold_minutes` | Scalper-Filter |
| `selection.drop_trader_loss_pct` | Ab welchem Verlust ein Trader rausfliegt |
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
