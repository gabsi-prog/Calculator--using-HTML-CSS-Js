# Einrichtung Schritt für Schritt (für Einsteiger)

Du brauchst **keine Programmierkenntnisse**. Alles läuft über den Browser.
Plane etwa **20 Minuten** für Phase 1 ein.

| Phase | Was | Kosten | Wann |
|---|---|---|---|
| **1** | Bot läuft auf GitHub im **Test-Modus** (Spielgeld) und schickt dir Telegram-Nachrichten | 0 € | jetzt |
| **2** | Echtes Geld (kleiner Betrag) | 0 € | nach 3–4 Wochen, **nur wenn Phase 1 im Plus ist** |
| **3** | Umzug auf einen kostenlosen Oracle-Server (schneller, rund um die Uhr) | 0 € | zusammen mit Phase 2 |

---

## Phase 1: Test-Modus auf GitHub

### Schritt 1: Den Code in `main` bringen

GitHub startet automatische Abläufe nur aus dem Haupt-Branch `main`.

1. Öffne dein Repository auf github.com.
2. Oben erscheint ein gelber Hinweis zum Branch `claude/trading-bot-copy-trading-fpwnuy` → **„Compare & pull request“** → **„Create pull request“** → **„Merge pull request“** → **„Confirm merge“**.

### Schritt 2: Telegram-Bot erstellen (dafür bekommst du Nachrichten aufs Handy)

1. Öffne Telegram und suche nach **@BotFather** (blauer Haken).
2. Schreib ihm `/newbot`.
3. Gib einen Namen ein, z. B. `Mein Copy Bot`.
4. Gib einen Benutzernamen ein, der auf `bot` endet, z. B. `gabriel_copy_123_bot`.
5. BotFather antwortet mit einem **Token**, das so aussieht: `7123456789:AAH...xyz`. **Kopier es und gib es niemandem.**
6. Klick auf den Link zu deinem neuen Bot (`t.me/...`), drück **Start** und schreib ihm irgendwas, z. B. „hallo“.
7. Öffne im Browser diese Adresse und setz dein Token ein:
   `https://api.telegram.org/bot<DEIN_TOKEN>/getUpdates`
   (also z. B. `https://api.telegram.org/bot7123456789:AAH...xyz/getUpdates`)
8. Such dort nach `"chat":{"id":` und notier die Zahl danach, z. B. `987654321`. Das ist deine **Chat-ID**.
   Steht dort nur `"result":[]`, schreib dem Bot noch eine Nachricht und lade die Seite neu.

### Schritt 3: Token und Chat-ID sicher bei GitHub hinterlegen

1. Im Repository: **Settings** (Zahnrad oben) → links **Secrets and variables** → **Actions**.
2. **„New repository secret“**:
   - Name: `TELEGRAM_BOT_TOKEN`, Secret: dein Token → **Add secret**
3. Noch einmal **„New repository secret“**:
   - Name: `TELEGRAM_CHAT_ID`, Secret: deine Chat-ID → **Add secret**

Secrets sind verschlüsselt. Niemand kann sie sehen, auch nicht in den Logs.

### Schritt 4: Den Bot zum ersten Mal starten

1. Im Repository oben auf den Tab **Actions** gehen.
   Fragt GitHub, ob Workflows aktiviert werden sollen: **„I understand…, enable them“**.
2. Links **„Copy-Trading-Bot“** anklicken → rechts **„Run workflow“** → bei *Aktion* **`telegram-test`** auswählen → grüner Button **„Run workflow“**.
3. Nach ca. 1 Minute sollte dein Handy eine Nachricht bekommen: *„✅ Telegram funktioniert!“*
4. Dasselbe mit **`trader-anzeigen`**: Du bekommst die Liste der Trader, die der Bot kopiert.
5. Dasselbe mit **`backtest`**: Du siehst, was das Kopieren dieser Trader zuletzt gebracht hätte.

Ab jetzt läuft der Bot **automatisch alle 5 Minuten** mit 1000 $ Spielgeld.
Du bekommst eine Nachricht bei jedem Trade und **jeden Abend um 19 Uhr** (Sommer: 20 Uhr) einen Tagesbericht.

> **Ein Lauf ist rot (❌)?** Klick drauf → „bot“ → „Bot ausführen“ und schick mir den Text, der dort steht.

### Gut zu wissen

- **Öffentliches Repository:** Die Logs (Trades und Kontostand) kann jeder sehen. Deine Schlüssel nicht. Im Test-Modus ist das egal.
- **Privates Repository:** Dort sind nur 2000 Gratis-Minuten pro Monat drin. Stell dann in `.github/workflows/copybot.yml` `*/5` auf `*/30` um (alle 30 Minuten).
- GitHub schaltet automatische Abläufe ab, wenn **60 Tage** lang nichts im Repository passiert. Du bekommst dann eine E-Mail und klickst auf „Enable“.
- **Einstellungen ändern** (z. B. Anzahl der Trader oder Stop-Loss): auf github.com die Datei `copy-trading-bot/config.yaml` öffnen → Stift-Symbol → ändern → **„Commit changes“**. Jede Einstellung ist dort auf Deutsch erklärt.
- **Kill-Switch ausgelöst?** Der Bot bleibt gestoppt, bis du in Actions **`kill-switch-zuruecksetzen`** ausführst. Prüf aber vorher, warum er ausgelöst hat.

### Wie lange testen?

Mindestens **3–4 Wochen**. Schau dir die Tagesberichte an:
- Ist „Seit Start“ deutlich im Plus, auch nach Gebühren?
- Wie tief ging es zwischendurch runter (Abstand zum Höchststand)? Würdest du das mit echtem Geld aushalten?

---

## Phase 2: Echtes Geld (erst nach erfolgreichem Test!)

### Schritt 1: Hyperliquid-Konto

1. Eine Wallet einrichten, z. B. **Rabby** oder **MetaMask** (Browser-Erweiterung).
   **Die Wiederherstellungswörter auf Papier aufschreiben, nie digital speichern.**
2. USDC auf das **Arbitrum**-Netzwerk bringen, z. B. über eine Börse wie Kraken oder Coinbase. Achte bei der Auszahlung auf das Netzwerk „Arbitrum“.
3. Auf **app.hyperliquid.xyz** → **Connect** → **Deposit** und einen **kleinen Betrag** einzahlen, z. B. 100–200 $.

### Schritt 2: API-Wallet erstellen (der Bot kann damit handeln, aber kein Geld abheben)

1. Auf app.hyperliquid.xyz oben **More → API**.
2. Einen Namen eingeben, z. B. `copybot` → **Generate** → **Authorize API Wallet** → in der Wallet bestätigen.
3. Den angezeigten **Private Key** kopieren. **Er wird nur einmal angezeigt.**

### Schritt 3: Bei GitHub eintragen

Unter **Settings → Secrets and variables → Actions**:
- Secret `HL_PRIVATE_KEY` = der Private Key der **API-Wallet**
- Secret `HL_ACCOUNT_ADDRESS` = die Adresse deiner **Haupt-Wallet** (beginnt mit `0x`)
- Reiter **Variables** → **New repository variable**: Name `COPYBOT_MODE`, Wert `live`

Ab dem nächsten Lauf handelt der Bot mit echtem Geld. **Gib niemals den Private Key deiner Haupt-Wallet ein.**

> Auf GitHub reagiert der Bot oft erst 5–30 Minuten später als die Trader. Mit echtem Geld ist **Phase 3** deutlich besser.
> Zurück zum Test-Modus: Variable `COPYBOT_MODE` auf `paper` setzen.

---

## Phase 3: Kostenloser Oracle-Server (Bot reagiert in Sekunden)

1. Auf **oracle.com/cloud/free** ein Konto anlegen. Eine Kreditkarte wird nur zur Prüfung verlangt, „Always Free“ kostet nichts.
   Als Region **Germany Central (Frankfurt)** wählen.
2. **Compute → Instances → Create Instance**
   - Image: **Ubuntu 22.04**
   - Shape: **VM.Standard.E2.1.Micro** oder **Ampere A1** (beide mit Label „Always Free“)
   - Bei *SSH keys*: **„Save private key“** herunterladen
   - **Create**. Danach die **Public IP** notieren.
3. Verbinden. Unter Windows **PowerShell** öffnen, auf dem Mac **Terminal**:
   ```
   ssh -i Pfad\zum\heruntergeladenen-key.key ubuntu@DEINE_IP
   ```
4. Auf dem Server nacheinander eingeben:
   ```
   git clone https://github.com/gabsi-prog/Calculator--using-HTML-CSS-Js.git
   cd Calculator--using-HTML-CSS-Js/copy-trading-bot
   bash deploy/install.sh
   nano .env
   ```
   In `nano` die vier Werte eintragen. Speichern mit `Strg+O` und `Enter`, schließen mit `Strg+X`.
   In `config.yaml` (`nano config.yaml`) `mode: live` setzen, dann:
   ```
   bash deploy/install.sh
   ```
5. **Wichtig:** Den GitHub-Bot abschalten, damit nicht zwei Bots dasselbe Konto steuern:
   GitHub → **Actions** → **Copy-Trading-Bot** → **„…“** oben rechts → **Disable workflow**.

Nützliche Befehle auf dem Server:
| Befehl | Was er macht |
|---|---|
| `journalctl -u copybot -f` | Live-Log ansehen (Beenden: `Strg+C`) |
| `sudo systemctl restart copybot` | Neu starten, z. B. nach Änderung der Einstellungen |
| `sudo systemctl stop copybot` | Bot stoppen |
| `cd ~/Calculator--using-HTML-CSS-Js && git pull && sudo systemctl restart copybot` | Updates holen |

---

## Probleme?

| Problem | Lösung |
|---|---|
| Keine Telegram-Nachricht | Token und Chat-ID prüfen; hast du deinem Bot einmal „Start“ geschrieben? |
| „0 Trader ausgewählt“ | Filter zu streng: in `config.yaml` z. B. `min_account_value` oder `min_month_roi` senken |
| Lauf ist rot ❌ | Fehlertext aus dem Log kopieren und mir schicken |
| Kill-Switch | Ursache prüfen, dann Aktion `kill-switch-zuruecksetzen` (Server: `.venv/bin/python -m copybot --reset-halt`) |
