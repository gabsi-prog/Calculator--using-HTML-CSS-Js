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

### Schritt 5 (optional): Wöchentliche KI-Analyse einschalten

Einmal pro Woche (sonntags früh) liest Claude das Tagebuch des Bots, also alle Trades, Stop-Losses und Fehler.
Claude erklärt dir auf Deutsch, was gut und was schlecht lief, und passt Einstellungen innerhalb fester Grenzen an.
Die Kosten liegen bei wenigen Cent pro Woche.

1. Auf **console.anthropic.com** ein Konto anlegen und unter **Billing** z. B. 5 $ Guthaben aufladen.
2. **API Keys** → **Create Key** → Namen eingeben, z. B. `copybot` → Key kopieren (beginnt mit `sk-ant-`).
3. Bei GitHub wie in Schritt 3 ein neues Secret anlegen: Name `ANTHROPIC_API_KEY`, Wert der Key.
4. Test: In **Actions** die Aktion **`ki-analyse`** ausführen. Die Analyse kommt per Telegram.

Ohne diesen Key lernt der Bot trotzdem täglich selbst. Nur die KI-Analyse fällt dann weg.

### Schritt 6: Dein Dashboard (Website) einschalten

Der Bot veröffentlicht alle ~15 Minuten eine Website mit Kontostand, Kurve, KI-Team, Positionen und Aktivität.

1. Ein Passwort ausdenken. Das Dashboard liegt öffentlich im Netz, die Daten sind aber damit verschlüsselt.
2. Bei GitHub ein neues Secret anlegen: Name `DASHBOARD_PASSWORD`, Wert dein Passwort.
3. **Settings → Pages**: Bei *Source* muss **„GitHub Actions“** stehen. Das ist schon so, weil dein Taschenrechner darüber läuft.
4. In **Actions** die Aktion **`dashboard-aktualisieren`** ausführen.
5. Öffnen: **`https://gabsi-prog.github.io/Calculator--using-HTML-CSS-Js/bot/`**, Passwort eingeben, fertig.
   Tipp fürs Handy: im Browser „Zum Startbildschirm hinzufügen“, dann sieht es aus wie eine App.

Dein Taschenrechner bleibt unter der normalen Adresse erreichbar.

### Schritt 7: KI-Agenten-Team

Mit dem `ANTHROPIC_API_KEY` aus Schritt 5 arbeitet automatisch alle 8 Stunden ein Team aus vier KI-Agenten:

| Agent | Aufgabe |
|---|---|
| **Markt-Analyst** | Trend, Volatilität, Funding und Open Interest der gehandelten Coins |
| **Nachrichten-Analyst** | Sucht im Internet nach aktuellen Meldungen: Hacks, Regulierung, Termine, Stimmung |
| **Trader-Analyst** | Prüft die kopierten Trader auf Warnsignale wie Verluste nachkaufen oder zu viel Hebel |
| **Risiko-Chef** | Liest alle Berichte und entscheidet: normale Größe, kleiner oder Coin sperren |

Der Risiko-Chef kann den Bot **nur bremsen, nie aggressiver machen**. Seine Entscheidung gilt höchstens 24 Stunden.
Die Berichte siehst du im Dashboard und per Telegram. Sofort starten: Aktion **`agenten`**.

**Kosten:** ca. 0,20–0,40 $ pro Runde, also ca. 20–35 $ im Monat. In `config.yaml` begrenzt `agents.monthly_budget_usd` (Standard 30 $) die Kosten hart.
Günstiger wird es, wenn du `agents.interval_hours` z. B. auf `12` oder `24` setzt.

### Gut zu wissen

- **Öffentliches Repository:** Die Logs (Trades und Kontostand) kann jeder sehen. Deine Schlüssel nicht. Im Test-Modus ist das egal.
- **Privates Repository:** Dort sind nur 2000 Gratis-Minuten pro Monat drin. Stell dann in `.github/workflows/copybot.yml` `*/5` auf `*/30` um (alle 30 Minuten).
- GitHub schaltet automatische Abläufe ab, wenn **60 Tage** lang nichts im Repository passiert. Du bekommst dann eine E-Mail und klickst auf „Enable“.
- **Einstellungen ändern** (z. B. Anzahl der Trader oder Stop-Loss): auf github.com die Datei `copy-trading-bot/config.yaml` öffnen → Stift-Symbol → ändern → **„Commit changes“**. Jede Einstellung ist dort auf Deutsch erklärt.
- **Was hat der Bot gelernt?** In Actions die Aktion **`lernstand`** ausführen und das Log ansehen.
  Gefällt dir etwas nicht, setzt **`gelerntes-zuruecksetzen`** alles auf die Werte aus `config.yaml` zurück.
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

**Dashboard auf dem Server ansehen** (sicherster Weg, ohne einen Port zu öffnen):
```
ssh -i Pfad\zum\key.key -L 8080:localhost:8080 ubuntu@DEINE_IP
```
Solange dieses Fenster offen ist, im Browser **http://localhost:8080** öffnen. Auf dem Server reagiert alles in Echtzeit.

Nützliche Befehle auf dem Server:
| Befehl | Was er macht |
|---|---|
| `journalctl -u copybot -f` | Live-Log ansehen (Beenden: `Strg+C`) |
| `sudo systemctl restart copybot` | Neu starten, z. B. nach Änderung der Einstellungen |
| `sudo systemctl stop copybot` | Bot stoppen |
| `cd ~/Calculator--using-HTML-CSS-Js && git pull && sudo systemctl restart copybot` | Updates holen |

---

## Memecoins (Solana) mit FOMO und Axiom

FOMO und Axiom haben **keine offizielle Schnittstelle** für Bots. Darum arbeitet der Bot so:
- **Du** findest in FOMO oder Axiom gute Trader und kopierst ihre **Wallet-Adresse**.
- **Der Bot** beobachtet diese Wallets direkt auf der Solana-Blockchain. Jeder Kauf dort ist öffentlich sichtbar.
- Kauft eine Wallet einen Memecoin, prüft der Bot den Token und kauft über **Jupiter** mit einer **eigenen Bot-Wallet** nach.

> ⚠️ **Ehrlich:** Memecoins sind das riskanteste, was man traden kann. Die meisten Tokens fallen auf null.
> Viele „Top-Wallets“ sind Insider, die verkaufen, sobald Nachahmer kaufen. Beim Kopieren bist du immer ein paar Sekunden später dran.
> Setz nur Geld ein, das du komplett verlieren kannst, und lass den Bot zuerst einige Wochen im Paper-Modus laufen.

### Schritt M1: Gute Wallets finden

**In FOMO:** Auf das Profil eines Traders tippen und die Wallet-Adresse kopieren.
**In Axiom:** Unter *Wallet Tracker* bzw. im Profil eines Traders die Adresse kopieren.

Worauf du achten solltest:
- Seit **Wochen** im Plus, nicht nur ein Glückstreffer
- Kauft Beträge ab ca. 0,5 SOL, also echte Überzeugung statt Spielerei
- Hält Tokens **Minuten bis Stunden**, nicht nur Sekunden. Sekunden-Trader sind Bots, die kann man nicht kopieren.

Prüfen, was der Bot bei einer Wallet erkennen würde:
```
python -m copybot --meme-wallet ADRESSE
```

### Schritt M2: Kostenlosen schnellen Solana-Zugang holen (empfohlen)

Der öffentliche Solana-Zugang ist langsam und begrenzt. Hol dir einen kostenlosen Zugang:
1. Auf **helius.dev** registrieren (Free-Plan).
2. Die **RPC-URL** kopieren (sieht aus wie `https://mainnet.helius-rpc.com/?api-key=...`).
3. In `config.yaml` bei `meme.rpc_url` eintragen. Auf dem Server liegt die Datei dort; teile die URL mit niemandem.

### Schritt M3: Einstellen und im Paper-Modus testen

In `config.yaml` unter `meme:`
```yaml
meme:
  enabled: true
  wallets:
    - "ErsteWalletAdresse..."
    - "ZweiteWalletAdresse..."
```
Alle anderen Werte (Einsatz, Stop-Loss, Sicherheits-Checks) sind dort auf Deutsch erklärt.

**Wichtig:** Memecoins brauchen **Dauerbetrieb**, also den Oracle-Server aus Phase 3 oder einen PC, der durchläuft.
Bei Memecoins zählen Sekunden. GitHub Actions läuft nur alle 5 Minuten, das ist dafür viel zu langsam.

Starten:
```
python -m copybot          # Hyperliquid-Bot + Memecoin-Bot + Dashboard
python -m copybot --meme   # nur Memecoins + Dashboard
```

Einen einzelnen Token prüfen:
```
python -m copybot --meme-check TOKENADRESSE
```

### Schritt M4: Live (erst nach erfolgreichem Test!)

1. In **Phantom** oder **Solflare** ein **neues, separates Konto** nur für den Bot anlegen. Nie deine Haupt-Wallet benutzen!
2. Nur einen kleinen Betrag SOL darauf überweisen, z. B. 0,5 SOL.
3. Den **Private Key** dieses Kontos exportieren (Phantom: Einstellungen → Konto → Private Key anzeigen).
4. Auf dem Server in `.env` eintragen: `SOLANA_PRIVATE_KEY=...`
5. `mode: live` setzen und den Bot neu starten.

Was der Bot kauft, siehst du im Dashboard, per Telegram und in Phantom/Solflare. In FOMO oder Axiom kannst du die Bot-Wallet-Adresse wie jede andere Wallet beobachten.

### Was der Bot zu deinem Schutz macht

| Schutz | Wirkung |
|---|---|
| Mint/Freeze-Check | Kauft nicht, wenn der Entwickler neue Tokens drucken oder deine Tokens einfrieren kann |
| RugCheck | Kauft nicht bei „danger“-Warnungen (z. B. ein Halter besitzt fast alles) |
| Liquidität | Mindestens 15.000 $, damit du auch wieder verkaufen kannst |
| Nicht hinterherlaufen | Signal älter als 45 s oder Kurs schon +25 % → kein Kauf |
| Preiseinfluss | Kauf würde den Preis um mehr als 5 % bewegen → kein Kauf |
| Ausstieg | −35 % Stop-Loss · bei +100 % die Hälfte verkaufen (Einsatz gesichert) · danach Trailing-Stop 30 % · max. 24 h halten |
| Trader folgen | Verkauft der Trader, verkaufst du anteilig mit |
| Limits | max. 8 offene Positionen, 25 Käufe pro Tag, Tagesverlust-Limit 0,5 SOL |
| Selbstkontrolle | Wallets, die dir Verlust bringen, werden 14 Tage pausiert. Der KI-Risiko-Chef kann Memecoin-Käufe stoppen. |

## Probleme?

| Problem | Lösung |
|---|---|
| Keine Telegram-Nachricht | Token und Chat-ID prüfen; hast du deinem Bot einmal „Start“ geschrieben? |
| „0 Trader ausgewählt“ | Filter zu streng: in `config.yaml` z. B. `min_account_value` oder `min_month_roi` senken |
| Lauf ist rot ❌ | Fehlertext aus dem Log kopieren und mir schicken |
| Kill-Switch | Ursache prüfen, dann Aktion `kill-switch-zuruecksetzen` (Server: `.venv/bin/python -m copybot --reset-halt`) |
