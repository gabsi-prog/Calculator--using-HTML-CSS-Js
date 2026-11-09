/* Copy-Desk – lädt data.json vom Bot (optional verschlüsselt) und zeigt alles live an.
   Ohne data.json läuft die Seite mit klar markierten Demo-Daten. */
(() => {
  "use strict";
  const REFRESH_MS = 20000;
  const ui = { range: "30d", filter: "alle", open: {}, password: null, demo: false, data: null };
  const $app = document.getElementById("app");

  // ---------- Helfer ----------
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const usdFmt = new Intl.NumberFormat("de-DE", { style: "currency", currency: "USD", maximumFractionDigits: 2 });
  const usd = (v) => (v == null || isNaN(v) ? "–" : usdFmt.format(v));
  const signedUsd = (v) => (v > 0 ? "+" : "") + usd(v);
  const pct = (v, d = 1) => (v == null || isNaN(v) ? "–" : (v * 100).toFixed(d).replace(".", ",") + " %");
  const signedPct = (v, d = 1) => (v > 0 ? "+" : "") + pct(v, d);
  const cls = (v) => (v > 0 ? "pos" : v < 0 ? "neg" : "muted");
  const short = (a) => (a ? a.slice(0, 6) + "…" + a.slice(-4) : "–");
  const pad = (n) => String(n).padStart(2, "0");
  const fmtTime = (t) => { const d = new Date(t * 1000); return `${pad(d.getDate())}.${pad(d.getMonth() + 1)} ${pad(d.getHours())}:${pad(d.getMinutes())}`; };
  const ago = (t) => {
    if (!t) return "noch nie";
    const s = Math.max(0, Date.now() / 1000 - t);
    if (s < 60) return "gerade eben";
    if (s < 3600) return `vor ${Math.round(s / 60)} Min.`;
    if (s < 86400) return `vor ${Math.round(s / 3600)} Std.`;
    return `vor ${Math.round(s / 86400)} Tagen`;
  };
  const holdTxt = (m) => (m == null ? "–" : m >= 60 ? (m / 60).toFixed(1).replace(".", ",") + " h" : Math.round(m) + " min");
  const store = { get: (k) => { try { return sessionStorage.getItem(k); } catch { return null; } },
                  set: (k, v) => { try { sessionStorage.setItem(k, v); } catch { /* egal */ } } };

  // Mini-Markdown für Agenten-Texte (erst escapen, dann formatieren)
  function md(text) {
    const lines = esc(text).split(/\r?\n/);
    let html = "", inList = false;
    for (let raw of lines) {
      const line = raw.trim();
      const bullet = /^([-•*]|\d+\.)\s+/.test(line);
      if (bullet && !inList) { html += "<ul>"; inList = true; }
      if (!bullet && inList) { html += "</ul>"; inList = false; }
      if (!line) continue;
      let body = line.replace(/^([-•*]|\d+\.)\s+/, "").replace(/^#{1,4}\s*/, "");
      body = body.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
      html += bullet ? `<li>${body}</li>` : /^#{1,4}\s/.test(line) ? `<p><strong>${body}</strong></p>` : `<p>${body}</p>`;
    }
    return html + (inList ? "</ul>" : "");
  }

  // ---------- Daten laden ----------
  const b64 = (s) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));
  async function decrypt(enc, pw) {
    const base = await crypto.subtle.importKey("raw", new TextEncoder().encode(pw), "PBKDF2", false, ["deriveKey"]);
    const key = await crypto.subtle.deriveKey({ name: "PBKDF2", salt: b64(enc.salt), iterations: enc.iter, hash: "SHA-256" },
      base, { name: "AES-GCM", length: 256 }, false, ["decrypt"]);
    const plain = await crypto.subtle.decrypt({ name: "AES-GCM", iv: b64(enc.iv) }, key, b64(enc.daten));
    return JSON.parse(new TextDecoder().decode(plain));
  }

  async function load() {
    let raw;
    try {
      const r = await fetch("data.json?ts=" + Date.now(), { cache: "no-store" });
      if (!r.ok) throw new Error(r.status);
      raw = await r.json();
    } catch {
      if (ui.data && !ui.demo) return render(); // kurzer Ausfall: letzte echten Daten weiter zeigen
      ui.demo = true;
      ui.data = ui.data || demoData();
      return render();
    }
    ui.demo = false;
    if (raw.verschluesselt) {
      ui.password = ui.password || store.get("copydesk-pw");
      if (!ui.password) return renderLock();
      try { ui.data = await decrypt(raw, ui.password); }
      catch { ui.password = null; return renderLock("Passwort falsch – bitte erneut eingeben."); }
    } else {
      ui.data = raw;
    }
    render();
  }

  function renderLock(err = "") {
    $app.innerHTML = `
      <div class="wrap lock"><form class="panel" id="lockform">
        <div class="brand"><div class="brand-mark">CD</div><div><h1>Copy-Desk</h1><small>Geschützter Bereich</small></div></div>
        <label for="pw">Dashboard-Passwort</label>
        <input id="pw" type="password" autocomplete="current-password" required autofocus>
        <p class="err">${esc(err)}</p>
        <button type="submit">Entsperren</button>
        <small class="muted">Die Daten werden erst in deinem Browser entschlüsselt.</small>
      </form></div>`;
    document.getElementById("lockform").addEventListener("submit", (e) => {
      e.preventDefault();
      ui.password = document.getElementById("pw").value;
      store.set("copydesk-pw", ui.password);
      load();
    });
  }

  // ---------- Rendern ----------
  function render() {
    const d = ui.data;
    const k = d.konto, now = Date.now() / 1000;
    const age = now - d.generiert;
    const fresh = d.gestoppt ? "off" : age < 600 ? "live" : age < 1500 ? "stale" : "off";
    const pnl = k.wert - k.start;
    const ov = d.agenten.entscheidung;
    const agentFactor = ov ? ov.global : 1;

    $app.innerHTML = `
    <header class="top"><div class="wrap">
      <div class="brand"><div class="brand-mark">CD</div><div><h1>Copy-Desk</h1><small>Hyperliquid Copy-Trading · KI-Team</small></div></div>
      <div class="chips">
        <span class="chip mode-${esc(d.modus)}">Modus <b>${d.modus === "live" ? "LIVE" : "PAPER"}</b></span>
        <span class="chip"><i class="dot ${fresh === "live" ? "live" : fresh}"></i><b>${d.gestoppt ? "Gestoppt" : fresh === "off" ? "Keine Daten" : "Läuft"}</b> · ${ago(d.generiert)}</span>
        <span class="chip">Trades <b class="num">${k.trades}</b></span>
      </div>
    </div></header>
    <div class="wrap">
      ${ui.demo ? `<div class="banner"><strong>Demo-Daten</strong> So sieht dein Leitstand aus, sobald der Bot läuft. Alle Zahlen hier sind Beispiele.</div>` : ""}
      ${d.gestoppt ? `<div class="banner alert"><strong>Kill-Switch ausgelöst</strong> Alle Positionen wurden geschlossen. Der Bot handelt erst wieder nach „Kill-Switch zurücksetzen“.</div>` : ""}
    </div>
    <main class="wrap">
      ${accountSection(d, pnl, agentFactor)}
      ${agentSection(d)}
      ${memeSection(d)}
      <section class="two">
        ${positionsPanel(d)}
        ${tradersPanel(d)}
      </section>
      <section class="two">
        ${learnPanel(d)}
        ${feedPanel(d)}
      </section>
      ${reviewPanel(d)}
    </main>
    <footer class="wrap">
      <span>Daten vom ${fmtTime(d.generiert)} · aktualisiert sich alle ${REFRESH_MS / 1000} s</span>
      <span>KI-Kosten diesen Monat: ${usd(d.agenten.kosten?.usd ?? 0)} · ${d.agenten.kosten?.calls ?? 0} Aufrufe</span>
    </footer>`;
    drawChart();
    bind();
  }

  function accountSection(d, pnl, agentFactor) {
    const k = d.konto;
    const ddShare = Math.min(1, k.drawdown / k.kill_switch_bei);
    const ddClass = ddShare < 0.4 ? "good" : ddShare < 0.75 ? "warn" : "bad";
    const effective = k.risikobremse * agentFactor;
    return `
    <section class="account" aria-label="Konto">
      <div class="panel">
        <div class="equity-head">
          <div><div class="eyebrow">Kontowert</div><div class="equity-value">${usd(k.wert)}</div></div>
          <span class="delta ${pnl >= 0 ? "up" : "down"}">${signedUsd(pnl)} · ${signedPct(pnl / k.start)} seit Start</span>
          <div class="range" role="group" aria-label="Zeitraum">
            ${[["1d", "24 h"], ["7d", "7 T"], ["30d", "30 T"], ["all", "Alles"]].map(([v, l]) =>
              `<button data-range="${v}" aria-pressed="${ui.range === v}">${l}</button>`).join("")}
          </div>
        </div>
        <div class="chart" id="chart"></div>
      </div>
      <div class="gauges">
        <div class="panel gauge">
          <div class="row"><span class="eyebrow">Abstand zum Höchststand</span><span class="val">${pct(k.drawdown)}</span></div>
          <div class="meter ${ddClass}"><i style="width:${(ddShare * 100).toFixed(1)}%"></i></div>
          <div class="hint">Kill-Switch bei ${pct(k.kill_switch_bei, 0)} · Höchststand ${usd(k.hoechststand)}</div>
        </div>
        <div class="panel gauge">
          <div class="row"><span class="eyebrow">Positionsgröße aktuell</span><span class="val">${pct(effective, 0)}</span></div>
          <div class="meter ${effective > 0.8 ? "good" : effective > 0.5 ? "warn" : "bad"}"><i style="width:${(effective * 100).toFixed(1)}%"></i></div>
          <div class="hint">Risikobremse ${pct(k.risikobremse, 0)} × KI-Team ${pct(agentFactor, 0)}</div>
        </div>
        <div class="panel gauge">
          <div class="row"><span class="eyebrow">Offene Positionen</span><span class="val">${d.positionen.length}</span></div>
          <div class="hint">Unrealisiert: <span class="${cls(sum(d.positionen, "upnl"))} num">${signedUsd(sum(d.positionen, "upnl"))}</span></div>
        </div>
      </div>
    </section>`;
  }
  const sum = (arr, key) => arr.reduce((a, x) => a + (x[key] || 0), 0);

  const AGENT_LOOK = {
    markt: { initials: "MA", color: "var(--info)" },
    news: { initials: "NA", color: "var(--accent)" },
    trader: { initials: "TA", color: "var(--up)" },
    chef: { initials: "RC", color: "var(--warn)" },
  };

  function agentSection(d) {
    const a = d.agenten;
    const reports = a.berichte || [];
    const specialists = reports.filter((r) => r.key !== "chef");
    const chief = reports.find((r) => r.key === "chef");
    const next = a.t ? a.t + a.intervall_h * 3600 : null;
    if (!reports.length) {
      return `<section><div class="section-head"><h2>KI-Team</h2></div>
        <div class="panel empty">Das Team hat noch nicht analysiert. Es startet automatisch, sobald ein ANTHROPIC_API_KEY hinterlegt ist.</div></section>`;
    }
    return `
    <section aria-label="KI-Team">
      <div class="section-head"><h2>KI-Team</h2>
        <p>Letzte Analyse ${ago(a.t)}${next ? ` · nächste ca. ${fmtTime(next)}` : ""} · ${esc(a.model || "")}</p></div>
      ${chief ? chiefPanel(chief, a.entscheidung) : ""}
      <div class="agents" style="margin-top:14px">${specialists.map(agentCard).join("")}</div>
    </section>`;
  }

  function agentCard(r) {
    const look = AGENT_LOOK[r.key] || { initials: "KI", color: "var(--accent)" };
    const open = ui.open[r.key];
    return `
    <article class="panel agent">
      <div class="agent-head">
        <div class="avatar" style="--c:${look.color}">${look.initials}</div>
        <div><h3>${esc(r.name)}</h3><p>${esc(r.role)}</p></div>
        <span class="agent-state"><i class="dot ${r.ok ? "" : "off"}"></i>${r.ok ? "fertig" : "Fehler"}</span>
      </div>
      <div class="agent-body ${open ? "" : "clamped"}">${md(r.text)}</div>
      <div class="agent-foot">
        <button class="link-btn" data-toggle="${esc(r.key)}" aria-expanded="${!!open}">${open ? "Weniger anzeigen" : "Ganzen Bericht lesen"}</button>
        <small>${ago(r.t)}${r.dauer_s ? ` · ${r.dauer_s} s` : ""}</small>
      </div>
    </article>`;
  }

  function chiefPanel(r, ov) {
    const data = r.data || {};
    const amp = (ov && ov.ampel) || data.marktampel || "gruen";
    const factor = ov ? ov.global : data.global_faktor ?? 1;
    // angezeigt werden die tatsächlich geltenden (begrenzten) Werte
    const c01 = (v) => Math.max(0, Math.min(1, Number(v)));
    const coinCuts = (data.coin_faktoren || []).map((c) => ({ ...c, faktor: c01(c.faktor) }));
    const locks = (data.sperren || []).map((s) => ({ ...s, stunden: Math.max(1, Math.min(72, Number(s.stunden))) }));
    const trust = (data.trader_vertrauen || []).map((t) => ({ ...t, faktor: c01(t.faktor) })).filter((t) => t.faktor < 1);
    const items = [
      ...coinCuts.map((c) => `<span class="decision ${c.faktor < 1 ? "cut" : ""}"><b>${esc(c.coin)}</b> ${pct(c.faktor, 0)} <span>${esc(c.grund)}</span></span>`),
      ...locks.map((s) => `<span class="decision block"><b>${esc(s.coin)}</b> gesperrt ${Math.round(s.stunden)} h <span>${esc(s.grund)}</span></span>`),
      ...trust.map((t) => `<span class="decision cut"><b>${short(t.adresse)}</b> Vertrauen ${pct(t.faktor, 0)} <span>${esc(t.grund)}</span></span>`),
    ];
    return `
    <article class="panel chief">
      <div class="chief-side">
        <div class="agent-head" style="padding:0;border:0">
          <div class="avatar" style="--c:var(--warn)">RC</div>
          <div><h3>Risiko-Chef</h3><p>entscheidet</p></div>
        </div>
        <div class="lamp" role="img" aria-label="Markt-Ampel ${esc(amp)}">
          <i class="r ${amp === "rot" ? "on" : ""}"></i><i class="y ${amp === "gelb" ? "on" : ""}"></i><i class="g ${amp === "gruen" ? "on" : ""}"></i>
        </div>
        <div><div class="eyebrow">Positionsgröße</div><div class="big-factor">${pct(factor, 0)}</div></div>
      </div>
      <div class="chief-main">
        <p class="chief-summary">${esc(data.zusammenfassung || r.text)}</p>
        ${items.length ? `<div><div class="eyebrow" style="margin-bottom:8px">Entscheidungen</div><div class="decisions">${items.join("")}</div></div>`
                       : `<div class="muted">Keine Einschränkungen – der Bot kopiert normal.</div>`}
        ${(data.warnungen || []).length ? `<div><div class="eyebrow" style="margin-bottom:6px">Warnungen</div><ul class="warnings">${data.warnungen.map((w) => `<li>${esc(w)}</li>`).join("")}</ul></div>` : ""}
      </div>
    </article>`;
  }

  function positionsPanel(d) {
    const rows = d.positionen.map((p) => `
      <tr><td class="coin">${esc(p.coin)}</td>
        <td><span class="side ${p.szi > 0 ? "long" : "short"}">${p.szi > 0 ? "LONG" : "SHORT"}</span></td>
        <td class="r num">${usd(p.value)}</td>
        <td class="r num muted">${p.entryPx.toLocaleString("de-DE", { maximumSignificantDigits: 6 })}</td>
        <td class="r num muted">${p.sl ? p.sl.toLocaleString("de-DE", { maximumSignificantDigits: 6 }) : "Börse"}</td>
        <td class="r num ${cls(p.upnl)}">${signedUsd(p.upnl)}</td></tr>`).join("");
    return `
    <div class="panel">
      <div class="section-head pad" style="margin:0;padding-bottom:6px"><h2>Positionen</h2><p>Stop-Loss liegt direkt an der Börse</p></div>
      ${rows ? `<div class="table-scroll"><table><thead><tr><th>Coin</th><th>Richtung</th><th class="r">Wert</th><th class="r">Einstieg</th><th class="r">Stop</th><th class="r">Ergebnis</th></tr></thead><tbody>${rows}</tbody></table></div>`
             : `<div class="empty">Keine offenen Positionen – die Trader halten gerade nichts, oder alles ist gebremst.</div>`}
    </div>`;
  }

  function tradersPanel(d) {
    const maxW = Math.max(2.5, ...d.trader.map((t) => t.gewicht));
    const rows = d.trader.map((t) => `
      <tr><td class="mono" title="${esc(t.address)}">${short(t.address)}</td>
        <td class="r num">${t.monthRoi == null ? "–" : signedPct(t.monthRoi, 0)}</td>
        <td class="r num muted">${holdTxt(t.median_hold_min)}</td>
        <td><div class="weight"><span class="bar"><i style="width:${(t.gewicht / maxW * 100).toFixed(0)}%"></i></span><span class="num">${t.gewicht.toFixed(2).replace(".", ",")}</span></div></td>
        <td class="r num ${t.vertrauen < 1 ? "neg" : "muted"}">${pct(t.vertrauen, 0)}</td>
        <td class="r num ${cls(t.gewinn)}">${signedUsd(t.gewinn)}</td></tr>`).join("");
    return `
    <div class="panel">
      <div class="section-head pad" style="margin:0;padding-bottom:6px"><h2>Kopierte Trader</h2><p>Gewicht lernt der Bot täglich</p></div>
      ${rows ? `<div class="table-scroll"><table><thead><tr><th>Adresse</th><th class="r">Monat</th><th class="r">Haltedauer</th><th>Gewicht</th><th class="r">Vertrauen</th><th class="r">Für dich</th></tr></thead><tbody>${rows}</tbody></table></div>`
             : `<div class="empty">Noch keine Trader ausgewählt.</div>`}
    </div>`;
  }

  // ---------- Memecoins ----------
  const sol = (v, dg = 3) => (v == null || isNaN(v) ? "–" : v.toLocaleString("de-DE", { minimumFractionDigits: dg, maximumFractionDigits: dg }) + " SOL");
  const signedSol = (v, dg = 4) => (v > 0 ? "+" : "") + sol(v, dg);

  function memeSection(d) {
    const m = d.meme;
    if (!m) return "";
    if (!m.aktiv) {
      return `<section><div class="section-head"><h2>Memecoins · Solana</h2></div>
        <div class="panel empty">Der Memecoin-Bot ist aus. Trag in <code>config.yaml</code> unter <code>meme.wallets</code> Trader-Wallets aus FOMO oder Axiom ein,
        setz <code>meme.enabled: true</code> und starte den Bot auf einem Server oder PC. Für Memecoins ist GitHub Actions zu langsam.</div></section>`;
    }
    const startSol = m.start_sol || m.wert_sol;
    const since = startSol ? m.wert_sol / startSol - 1 : 0;
    const pos = m.positionen.map((p) => `
      <tr><td><a class="coin" href="https://dexscreener.com/solana/${encodeURIComponent(p.mint)}" target="_blank" rel="noopener">${esc(p.symbol)}</a></td>
        <td class="r num">${sol(p.cost_sol)}</td><td class="r num">${sol(p.value_sol)}</td>
        <td class="r num ${cls(p.pnl_pct)}">${signedPct(p.pnl_pct, 0)}</td>
        <td>${p.tp_done ? `<span class="side long">EINSATZ GESICHERT</span>` : `<span class="muted">läuft</span>`}</td>
        <td class="mono muted">${short(p.leader)}</td><td class="muted">${ago(p.opened)}</td></tr>`).join("");
    const wallets = m.wallets.map((w) => `
      <tr><td class="mono" title="${esc(w.adresse)}">${short(w.adresse)}</td>
        <td class="r num">${w.copied}</td><td class="r num muted">${w.skipped}</td>
        <td class="r num">${w.trades ? Math.round(w.wins / w.trades * 100) + " %" : "–"}</td>
        <td class="r num ${cls(w.pnl_sol)}">${signedSol(w.pnl_sol)}</td>
        <td>${w.gesperrt ? `<span class="side short">PAUSE</span>` : `<span class="side long">AKTIV</span>`}</td></tr>`).join("");
    return `
    <section aria-label="Memecoins">
      <div class="section-head"><h2>Memecoins · Solana</h2><p>Kopiert Wallets aus FOMO und Axiom · Stop-Loss, Take-Profit und Trailing-Stop automatisch</p></div>
      <div class="kpis panel">
        <div><div class="eyebrow">Wert</div><div class="kpi">${sol(m.wert_sol)}</div><small class="muted">${m.sol_usd ? usd(m.wert_sol * m.sol_usd) : ""}</small></div>
        <div><div class="eyebrow">Seit Start</div><div class="kpi ${cls(since)}">${signedPct(since)}</div><small class="muted">Start ${sol(startSol, 2)}</small></div>
        <div><div class="eyebrow">Heute</div><div class="kpi ${cls(m.tag.pnl_sol)}">${signedSol(m.tag.pnl_sol || 0, 3)}</div><small class="muted">${m.tag.buys || 0} Käufe</small></div>
        <div><div class="eyebrow">Frei verfügbar</div><div class="kpi">${sol(m.sol)}</div><small class="muted">${m.positionen.length} offene Positionen</small></div>
      </div>
      <div class="meme-grid">
        <div class="panel">
          <div class="section-head pad" style="margin:0;padding-bottom:6px"><h2>Offene Memecoins</h2><p>Klick öffnet den Chart</p></div>
          ${pos ? `<div class="table-scroll"><table><thead><tr><th>Token</th><th class="r">Einsatz</th><th class="r">Wert</th><th class="r">Ergebnis</th><th>Status</th><th>Wallet</th><th>Seit</th></tr></thead><tbody>${pos}</tbody></table></div>`
                : `<div class="empty">Gerade keine Memecoins im Bestand.</div>`}
        </div>
        <div class="panel">
          <div class="section-head pad" style="margin:0;padding-bottom:6px"><h2>Kopierte Wallets</h2><p>Verlierer pausieren automatisch</p></div>
          ${wallets ? `<div class="table-scroll"><table><thead><tr><th>Wallet</th><th class="r">Kopiert</th><th class="r">Übersprungen</th><th class="r">Treffer</th><th class="r">Für dich</th><th>Status</th></tr></thead><tbody>${wallets}</tbody></table></div>`
                    : `<div class="empty">Noch keine Wallets eingetragen.</div>`}
        </div>
      </div>
    </section>`;
  }

  const PARAM_NAMES = {
    "risk.stop_loss_pct": ["Stop-Loss-Abstand", "pct"], "copy.copy_ratio": ["Kopier-Faktor", "x"],
    "risk.max_leverage": ["Max. Hebel gesamt", "x"], "risk.max_position_pct": ["Max. pro Coin", "pct"],
    "selection.top_n": ["Anzahl Trader", "n"], "selection.min_median_hold_minutes": ["Min. Haltedauer", "min"],
    "selection.drop_trader_loss_pct": ["Aussortieren ab Verlust", "pct"],
  };
  const fmtParam = (v, kind) => kind === "pct" ? pct(v, 1) : kind === "min" ? holdTxt(v) : kind === "x" ? String(v).replace(".", ",") + "×" : String(v);

  function learnPanel(d) {
    const params = Object.entries(d.lernen.parameter).map(([key, p]) => {
      const [name, kind] = PARAM_NAMES[key] || [key, "n"];
      const changed = Math.abs(p.wert - p.config) > 1e-9;
      return `<div class="param ${changed ? "changed" : ""}"><div class="k">${esc(name)}</div>
        <div class="v">${changed ? `<s>${fmtParam(p.config, kind)}</s>` : ""}${fmtParam(p.wert, kind)}</div></div>`;
    }).join("");
    return `
    <div class="panel">
      <div class="section-head pad" style="margin:0;padding-bottom:0"><h2>Was der Bot gelernt hat</h2><p>Durchgestrichen = Wert aus config.yaml</p></div>
      <div class="learn-grid">${params}</div>
    </div>`;
  }

  function feedItems(d) {
    const a = d.aktivitaet, items = [];
    const reasons = { open: "eröffnet", increase: "nachgekauft", reduce: "reduziert", close: "geschlossen", flip: "gedreht" };
    for (const t of a.trades) items.push({ t: t.t, kind: "trade", html: `<b>${esc(t.coin)}</b> ${reasons[t.reason] || esc(t.reason)} ${t.reason === "close" ? "" : esc(t.side)} <span>· ${usd(t.usd)}${t.lag != null ? ` · Verzögerung ${signedPct(t.lag, 2)}` : ""}</span>` });
    for (const s of a.stops) items.push({ t: s.t, kind: "stop", html: `<b>${esc(s.coin)}</b> per Stop-Loss geschlossen${s.whipsaw === true ? " <span>· später unnötig gewesen</span>" : s.whipsaw === false ? " <span>· war berechtigt</span>" : ""}` });
    for (const e of a.fehler) items.push({ t: e.t, kind: "error", html: `${e.coin ? `<b>${esc(e.coin)}</b> ` : ""}${esc(e.kategorie)} <span>· ${e.behoben ? "selbst behoben (" + esc(e.korrektur) + ")" : esc(e.korrektur || "übersprungen")}</span>` });
    for (const c of d.lernen.aenderungen) items.push({ t: c.t, kind: "learn", html: `<b>${esc((PARAM_NAMES[c.param] || [c.param])[0])}</b> ${esc(c.old)} → ${esc(c.new)} <span>· ${c.source === "ki" ? "KI" : "gelernt"}: ${esc(c.reason)}</span>` });
    for (const e of (d.meme && d.meme.ereignisse) || []) {
      const s = `<b>${esc(e.symbol || short(e.mint))}</b>`;
      if (e.kind === "buy") items.push({ t: e.t, kind: "meme", html: `${s} gekauft <span>· ${sol(e.sol)} · von ${short(e.wallet)}${e.lag != null ? ` · Einstieg ${signedPct(e.lag)} vs. Trader` : ""}</span>` });
      else if (e.kind === "sell") items.push({ t: e.t, kind: "meme", html: `${s} verkauft <span class="${cls(e.pnl_sol)}">${signedSol(e.pnl_sol)} (${signedPct(e.pct, 0)})</span> <span>· ${esc(e.reason)}</span>` });
      else if (e.kind === "skip") items.push({ t: e.t, kind: "skip", html: `${s} nicht kopiert <span>· ${esc((e.reasons || []).join("; "))}</span>` });
      else items.push({ t: e.t, kind: "error", html: `${s} <span>· ${esc(e.text)}</span>` });
    }
    return items.sort((x, y) => y.t - x.t);
  }

  function feedPanel(d) {
    const map = { alle: null, trades: "trade", memes: ["meme", "skip"], stops: "stop", fehler: "error", lernen: "learn" };
    const want = map[ui.filter];
    const items = feedItems(d).filter((i) => !want || (Array.isArray(want) ? want.includes(i.kind) : i.kind === want)).slice(0, 80);
    return `
    <div class="panel">
      <div class="section-head pad" style="margin:0;padding-bottom:6px"><h2>Aktivität</h2>
        <div class="filters" role="group" aria-label="Filter">${Object.keys(map).map((f) =>
          `<button data-filter="${f}" aria-pressed="${ui.filter === f}">${f[0].toUpperCase() + f.slice(1)}</button>`).join("")}</div></div>
      ${items.length ? `<ul class="feed">${items.map((i) => `<li><time>${fmtTime(i.t)}</time><i class="k ${i.kind}"></i><p>${i.html}</p></li>`).join("")}</ul>`
                     : `<div class="empty">Noch keine Einträge.</div>`}
    </div>`;
  }

  function reviewPanel(d) {
    const r = d.ki_wochenanalyse;
    if (!r) return "";
    const e = r.ergebnis || {};
    return `
    <section class="panel review" aria-label="Wochen-Analyse">
      <div class="section-head" style="margin:0"><h2>Wochen-Coach</h2><p>${ago(r.t)}</p></div>
      <p>${esc(e.zusammenfassung)}</p>
      ${(e.probleme || []).length ? `<ul class="warnings">${e.probleme.map((p) => `<li>${esc(p)}</li>`).join("")}</ul>` : ""}
      ${(r.angewendet || []).length ? `<div class="decisions">${r.angewendet.map((a) => `<span class="decision">${esc(a)}</span>`).join("")}</div>` : ""}
    </section>`;
  }

  // ---------- Chart ----------
  function niceTicks(lo, hi, n = 4) {
    const span = hi - lo || 1, raw = span / n, mag = 10 ** Math.floor(Math.log10(raw));
    const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw);
    const ticks = [];
    for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) ticks.push(+v.toFixed(10));
    return ticks;
  }

  function drawChart() {
    const box = document.getElementById("chart");
    if (!box) return;
    const all = ui.data.kurve;
    const spans = { "1d": 86400, "7d": 7 * 86400, "30d": 30 * 86400, all: Infinity };
    const lastT = all.length ? all[all.length - 1][0] : 0;
    let pts = all.filter((p) => p[0] >= lastT - spans[ui.range]);
    if (pts.length < 2) { box.innerHTML = `<div class="empty">Die Kurve erscheint nach den ersten Durchläufen.</div>`; return; }
    const W = Math.max(320, box.clientWidth - 16), H = box.clientWidth < 560 ? 210 : 260;
    const m = { l: 62, r: 14, t: 12, b: 26 };
    const start = ui.data.konto.start;
    let lo = Math.min(...pts.map((p) => p[1])), hi = Math.max(...pts.map((p) => p[1]));
    if (start >= lo - (hi - lo) * 0.5 && start <= hi + (hi - lo) * 0.5) { lo = Math.min(lo, start); hi = Math.max(hi, start); }
    const padY = (hi - lo) * 0.12 || hi * 0.01;
    lo -= padY; hi += padY;
    const t0 = pts[0][0], t1 = pts[pts.length - 1][0];
    const x = (t) => m.l + (t - t0) / (t1 - t0 || 1) * (W - m.l - m.r);
    const y = (v) => m.t + (1 - (v - lo) / (hi - lo)) * (H - m.t - m.b);
    const yt = niceTicks(lo, hi, 4);
    const xt = [0, 0.33, 0.66, 1].map((f) => t0 + f * (t1 - t0));
    const line = pts.map((p, i) => `${i ? "L" : "M"}${x(p[0]).toFixed(1)},${y(p[1]).toFixed(1)}`).join("");
    const area = `${line}L${x(t1).toFixed(1)},${H - m.b}L${x(t0).toFixed(1)},${H - m.b}Z`;
    const last = pts[pts.length - 1];
    const dateLbl = (t) => { const d = new Date(t * 1000); return spans[ui.range] <= 86400 ? `${pad(d.getHours())}:${pad(d.getMinutes())}` : `${pad(d.getDate())}.${pad(d.getMonth() + 1)}.`; };
    const yLbl = (v) => v >= 10000 ? (v / 1000).toLocaleString("de-DE", { maximumFractionDigits: 1 }) + "k" : v.toLocaleString("de-DE", { maximumFractionDigits: v < 100 ? 2 : 0 });
    box.innerHTML = `
      <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Verlauf des Kontowerts">
        <defs><linearGradient id="eqfill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" style="stop-color:var(--accent);stop-opacity:.28"></stop>
          <stop offset="1" style="stop-color:var(--accent);stop-opacity:0"></stop></linearGradient></defs>
        <g class="grid">${yt.map((v) => `<line x1="${m.l}" x2="${W - m.r}" y1="${y(v)}" y2="${y(v)}"></line>`).join("")}</g>
        <g class="axis">${yt.map((v) => `<text x="${m.l - 8}" y="${y(v) + 4}" text-anchor="end">${yLbl(v)}</text>`).join("")}
          ${xt.map((t, i) => `<text x="${x(t)}" y="${H - 6}" text-anchor="${i === 0 ? "start" : i === 3 ? "end" : "middle"}">${dateLbl(t)}</text>`).join("")}</g>
        ${start > lo && start < hi ? `<line class="start-line" x1="${m.l}" x2="${W - m.r}" y1="${y(start)}" y2="${y(start)}"></line>` : ""}
        <path class="area" d="${area}"></path>
        <path class="line" d="${line}"></path>
        <circle class="end-dot" cx="${x(last[0])}" cy="${y(last[1])}" r="5"></circle>
        <g class="cross" hidden><line y1="${m.t}" y2="${H - m.b}"></line><circle r="4.5"></circle></g>
      </svg><div class="tip" hidden></div>`;
    const svg = box.querySelector("svg"), cross = box.querySelector(".cross"), tip = box.querySelector(".tip");
    const move = (ev) => {
      const rect = svg.getBoundingClientRect();
      const px = (ev.clientX - rect.left) * (W / rect.width);
      let best = pts[0];
      for (const p of pts) if (Math.abs(x(p[0]) - px) < Math.abs(x(best[0]) - px)) best = p;
      const cx = x(best[0]), cy = y(best[1]);
      cross.hidden = false;
      cross.querySelector("line").setAttribute("x1", cx); cross.querySelector("line").setAttribute("x2", cx);
      cross.querySelector("circle").setAttribute("cx", cx); cross.querySelector("circle").setAttribute("cy", cy);
      tip.hidden = false;
      tip.innerHTML = `${fmtTime(best[0])}<br><b>${usd(best[1])}</b> <span class="${cls(best[1] - start)}">${signedPct(best[1] / start - 1)}</span>`;
      const sx = cx * rect.width / W, sy = cy * rect.height / H;
      tip.style.left = Math.min(Math.max(8, sx - tip.offsetWidth / 2), rect.width - tip.offsetWidth) + "px";
      tip.style.top = Math.max(0, sy - tip.offsetHeight - 14) + "px";
    };
    svg.addEventListener("pointermove", move);
    svg.addEventListener("pointerleave", () => { cross.hidden = true; tip.hidden = true; });
  }

  function bind() {
    $app.querySelectorAll("[data-range]").forEach((b) => b.addEventListener("click", () => { ui.range = b.dataset.range; render(); }));
    $app.querySelectorAll("[data-filter]").forEach((b) => b.addEventListener("click", () => { ui.filter = b.dataset.filter; render(); }));
    $app.querySelectorAll("[data-toggle]").forEach((b) => b.addEventListener("click", () => { ui.open[b.dataset.toggle] = !ui.open[b.dataset.toggle]; render(); }));
  }
  let rT;
  window.addEventListener("resize", () => { clearTimeout(rT); rT = setTimeout(drawChart, 150); });

  // ---------- Demo-Daten ----------
  function demoData() {
    const now = Math.floor(Date.now() / 1000);
    let seed = 7; const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
    const kurve = []; let eq = 1000;
    for (let i = 30 * 24 * 6; i >= 0; i -= 3) {
      eq *= 1 + (rnd() - 0.47) * 0.006;
      kurve.push([now - i * 600, Math.round(eq * 100) / 100]);
    }
    const wert = kurve[kurve.length - 1][1];
    const peak = Math.max(...kurve.map((p) => p[1]));
    const h = 3600;
    const trader = [
      { address: "0x7b3f1c9a2e4d5f60718293a4b5c6d7e8f9a0b1c2", monthRoi: 0.31, median_hold_min: 540, gewicht: 1.62, gewinn: 41.8, vertrauen: 1 },
      { address: "0x2c91de04f5a6b7c8d9e0f1a2b3c4d5e6f7a8b9d4", monthRoi: 0.18, median_hold_min: 1320, gewicht: 1.24, gewinn: 22.3, vertrauen: 1 },
      { address: "0x9e44a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8", monthRoi: 0.42, median_hold_min: 95, gewicht: 0.71, gewinn: -12.6, vertrauen: 0.7 },
      { address: "0x51ac0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c", monthRoi: 0.12, median_hold_min: 2880, gewicht: 1.05, gewinn: 8.9, vertrauen: 1 },
      { address: "0xd03be7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2c3d4", monthRoi: 0.09, median_hold_min: 410, gewicht: 0.88, gewinn: -3.1, vertrauen: 1 },
    ];
    return {
      generiert: now - 40, modus: "paper", gestoppt: false,
      konto: { wert, start: 1000, hoechststand: peak, drawdown: 1 - wert / peak, kill_switch_bei: 0.25, risikobremse: Math.max(0.3, 1 - (1 - wert / peak) / 0.25), trades: 214 },
      kurve,
      positionen: [
        { coin: "BTC", szi: 0.0021, entryPx: 96120, value: 204.6, upnl: 6.8, sl: 88430 },
        { coin: "ETH", szi: -0.041, entryPx: 3655, value: 147.2, upnl: 2.6, sl: 3947 },
        { coin: "SOL", szi: 0.55, entryPx: 188.4, value: 101.9, upnl: -1.7, sl: 173.3 },
        { coin: "HYPE", szi: 2.4, entryPx: 31.2, value: 77.9, upnl: 3.0, sl: 28.7 },
      ],
      trader,
      agenten: {
        t: now - 2.4 * h, model: "claude-opus-5-5", intervall_h: 8, kosten: { usd: 6.42, calls: 96 },
        entscheidung: { ampel: "gelb", global: 0.85, coins: { SOL: 0.6 }, trader: { [trader[2].address]: 0.7 }, sperren: {} },
        berichte: [
          { key: "markt", name: "Markt-Analyst", role: "Analysiert Trend, Volatilität, Funding und Open Interest der gehandelten Coins", ok: true, t: now - 2.4 * h, dauer_s: 21.4,
            text: "**Marktlage:** BTC hält sich über dem 20er- und 50er-Durchschnitt, der Trend ist leicht aufwärts. Die Volatilität ist moderat.\n\n- **BTC:** Aufwärtstrend intakt, RSI 58, Funding normal.\n- **ETH:** schwächer als BTC, unter SMA20. Der Short der Trader passt ins Bild.\n- **SOL:** Funding bei +48 % p.a. – viele sind long, Gefahr eines schnellen Rücksetzers.\n- **HYPE:** hohe Volatilität (6,1 % pro Tag), nahe am 14-Tage-Hoch.\n\n**Größte Risiken:** überfüllter SOL-Long und HYPE-Volatilität." },
          { key: "news", name: "Nachrichten-Analyst", role: "Durchsucht aktuelle Nachrichten & Medien nach Risiken und Stimmung", ok: true, t: now - 2.4 * h, dauer_s: 48.9,
            text: "**Stimmung:** neutral bis leicht bullisch – ETF-Zuflüsse stabil, keine größeren Negativ-Schlagzeilen.\n\n**Wichtige Meldungen:**\n- BTC: Spot-ETFs mit drei Tagen Nettozuflüssen in Folge.\n- SOL: Großer Token-Unlock in 4 Tagen angekündigt.\n- ETH: Upgrade-Termin verschoben, Stimmung gedämpft.\n\n**Termine (48 h):** US-Inflationsdaten am Mittwoch 14:30 Uhr.\n\n**Warnungen:** keine akuten Risiken (kein Hack, kein Delisting)." },
          { key: "trader", name: "Trader-Analyst", role: "Prüft das Verhalten der kopierten Trader auf Warnsignale", ok: true, t: now - 2.4 * h, dauer_s: 17.2,
            text: "- **0x7b3f…b1c2:** solide, moderater Hebel (1,8×), verteilt auf 3 Coins.\n- **0x2c91…b9d4:** sehr ruhig, lange Haltedauer – gut kopierbar.\n- **0x9e44…e7f8:** hat Verlustposition in SOL zweimal nachgekauft und Hebel auf 6× erhöht. Martingale-Verdacht.\n- **0x51ac…6b7c / 0xd03b…c3d4:** unauffällig.\n\n**Empfehlung:** 0x9e44 weniger vertrauen." },
          { key: "chef", name: "Risiko-Chef", role: "Liest alle Berichte und entscheidet", ok: true, t: now - 2.4 * h, dauer_s: 26.0,
            text: "", data: { zusammenfassung: "Der Markt ist insgesamt stabil, aber vor den Inflationsdaten am Mittwoch fahren wir etwas kleiner. SOL ist überfüllt und hat einen Unlock vor sich, deshalb halbieren wir dort fast. Einem Trader trauen wir wegen Nachkaufens von Verlusten weniger.",
              marktampel: "gelb", global_faktor: 0.85,
              coin_faktoren: [{ coin: "SOL", faktor: 0.6, grund: "Funding extrem hoch, Token-Unlock in 4 Tagen" }],
              sperren: [], trader_vertrauen: [{ adresse: trader[2].address, faktor: 0.7, grund: "kauft Verluste nach, Hebel 6×" }],
              warnungen: ["US-Inflationsdaten Mittwoch 14:30 Uhr – starke Bewegungen möglich"] } },
        ],
      },
      ki_wochenanalyse: { t: now - 3 * 86400, ergebnis: { zusammenfassung: "Gute Woche mit +3,1 %. Die meisten Gewinne kamen von zwei ruhigen Tradern. Drei von vier Stop-Losses waren unnötig, der Kurs lief danach zurück.", probleme: ["Stop-Loss bei 8 % ist für HYPE zu eng"] },
        angewendet: ["✅ risk.stop_loss_pct: 0.08 → 0.09 – zu viele unnötige Stops"] },
      lernen: {
        parameter: {
          "risk.stop_loss_pct": { wert: 0.09, config: 0.08 }, "copy.copy_ratio": { wert: 0.5, config: 0.5 },
          "risk.max_leverage": { wert: 3, config: 3 }, "risk.max_position_pct": { wert: 0.35, config: 0.35 },
          "selection.top_n": { wert: 5, config: 5 }, "selection.min_median_hold_minutes": { wert: 90, config: 60 },
          "selection.drop_trader_loss_pct": { wert: 0.15, config: 0.15 },
        },
        aenderungen: [
          { t: now - 3 * 86400, param: "risk.stop_loss_pct", old: 0.08, new: 0.09, reason: "3 von 4 Stops waren unnötig", source: "ki" },
          { t: now - 5 * 86400, param: "selection.min_median_hold_minutes", old: 60, new: 90, reason: "Einstieg im Schnitt 0,62 % schlechter als der Trader", source: "lernen" },
        ],
      },
      aktivitaet: {
        trades: [
          { t: now - 0.3 * h, coin: "HYPE", reason: "increase", side: "LONG", usd: 26.1, lag: 0.0021 },
          { t: now - 1.1 * h, coin: "SOL", reason: "reduce", side: "LONG", usd: 64.0, lag: null },
          { t: now - 5.2 * h, coin: "ETH", reason: "open", side: "SHORT", usd: 147.0, lag: 0.0034 },
          { t: now - 9.8 * h, coin: "BTC", reason: "increase", side: "LONG", usd: 58.4, lag: 0.0012 },
          { t: now - 26 * h, coin: "DOGE", reason: "close", side: "LONG", usd: 41.5, lag: null },
        ],
        stops: [{ t: now - 31 * h, coin: "AVAX", whipsaw: true }],
        fehler: [{ t: now - 7 * h, coin: "SOL", kategorie: "zu_wenig_margin", korrektur: "Größe halbiert", behoben: true }],
      },
      sperren: { cooldown: {}, quarantaene: {}, aussortiert: {} },
      meme: {
        aktiv: true, sol: 1.412, start_sol: 2.0, wert_sol: 2.318, sol_usd: 182.4,
        tag: { pnl_sol: 0.0861, buys: 6 },
        positionen: [
          { mint: "8dL1kqGmQbE3tVz7Hj2pW4nX6rS9cFyU1aB5oKpump", symbol: "GIGACAT", cost_sol: 0.0251, value_sol: 0.0846, pnl_pct: 2.37, tp_done: true, leader: "7vYqZ1oWm3xKp9eTn4bF2sHd8cJr5uLa6gEi1MpQx3Ws", opened: now - 3.2 * h },
          { mint: "4pXr9TkqW2nB7mVc5eHy1Lz8sD3fGjA6uRoN2Ypump", symbol: "WOJAK", cost_sol: 0.0503, value_sol: 0.0582, pnl_pct: 0.157, tp_done: false, leader: "3kHn8RwPz5qLe1vXc7bJt2mYd9sFg4aUo6NiQeTr8Bm", opened: now - 1.1 * h },
          { mint: "9sGh2LmP4wQx7cVb1nKe5rTy8uIo3aZd6fJp1Hpump", symbol: "MOONDOG", cost_sol: 0.0503, value_sol: 0.0381, pnl_pct: -0.243, tp_done: false, leader: "7vYqZ1oWm3xKp9eTn4bF2sHd8cJr5uLa6gEi1MpQx3Ws", opened: now - 0.4 * h },
        ],
        wallets: [
          { adresse: "7vYqZ1oWm3xKp9eTn4bF2sHd8cJr5uLa6gEi1MpQx3Ws", copied: 21, skipped: 34, trades: 18, wins: 8, pnl_sol: 0.412, gesperrt: false },
          { adresse: "3kHn8RwPz5qLe1vXc7bJt2mYd9sFg4aUo6NiQeTr8Bm", copied: 12, skipped: 19, trades: 11, wins: 4, pnl_sol: -0.061, gesperrt: false },
          { adresse: "Fz2wQe8Rt5yUi1oPa4sDf7gHj3kLz6xCv9bNm2QwEr4T", copied: 9, skipped: 40, trades: 9, wins: 2, pnl_sol: -0.268, gesperrt: true },
        ],
        ereignisse: [
          { t: now - 0.4 * h, kind: "buy", symbol: "MOONDOG", mint: "9sG", sol: 0.0503, wallet: "7vYqZ1oWm3xKp9eTn4bF2sHd8cJr5uLa6gEi1MpQx3Ws", lag: 0.064 },
          { t: now - 0.6 * h, kind: "skip", symbol: "RUGME", mint: "x", reasons: ["Entwickler kann neue Tokens drucken (Mint Authority aktiv)", "zu wenig Liquidität (6.200 $)"] },
          { t: now - 0.9 * h, kind: "sell", symbol: "GIGACAT", mint: "8dL", pnl_sol: 0.0298, pct: 1.18, reason: "Take-Profit +118 % – Einsatz gesichert" },
          { t: now - 1.4 * h, kind: "skip", symbol: "PNUT2", mint: "y", reasons: ["Kurs schon +41 % seit Kauf des Traders"] },
          { t: now - 2.2 * h, kind: "sell", symbol: "FROGE", mint: "z", pnl_sol: -0.0177, pct: -0.35, reason: "Stop-Loss -35 %" },
        ],
      },
    };
  }

  load();
  setInterval(() => { if (!document.hidden) load(); }, REFRESH_MS);
})();
