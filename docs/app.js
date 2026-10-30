/* Combinés Foot : tickets du robot et suivi des paris joués (enregistrés sur le téléphone). */
const LS = {
  get(k, d) { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch {} },
};
let today = null, hist = null, meta = null, freshStamp = null;
const overrides = () => LS.get("pf_overrides", {});
const bets = () => LS.get("pf_bets", {});
const settings = () => Object.assign({ budget: 40, token: "", repo: "" }, LS.get("pf_settings", {}));

const fmt = (x, d = 2) => Number(x).toLocaleString("fr-FR", { minimumFractionDigits: d, maximumFractionDigits: d });
const pct = (x) => Math.round(x * 100) + " %";
const eur = (x) => (x > 0 ? "+" : "") + fmt(x) + " €";
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const isoDay = (d) => d.toLocaleDateString("sv-SE", { timeZone: "Europe/Paris" });
const hour = (iso) => new Date(iso).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit", timeZone: "Europe/Paris" }).replace(":", "h");
const when = (iso) => {
  const d = new Date(iso);
  const day = d.toLocaleDateString("fr-FR", { weekday: "short", day: "numeric", month: "short", timeZone: "Europe/Paris" });
  return `${day} à ${hour(iso)}`;
};
const kindOrder = (c) => (c.kind === "folie" ? 9 : c.kind === "x3" ? 2 : 1);
const longDate = (day) => new Date(day + "T12:00:00").toLocaleDateString("fr-FR", { weekday: "long", day: "numeric", month: "long" });

function dayTitle(day) {
  const t = isoDay(new Date());
  if (day === t) return ["Aujourd'hui", longDate(day)];
  if (day === isoDay(new Date(Date.now() + 864e5))) return ["Demain", longDate(day)];
  if (day === isoDay(new Date(Date.now() - 864e5))) return ["Hier", longDate(day)];
  const l = longDate(day);
  return [l.charAt(0).toUpperCase() + l.slice(1), ""];
}

const SRC = { unibet: "Unibet", pmu: "PMU, à vérifier", netbet: "NetBet, à vérifier", betclic: "Betclic, à vérifier",
  winamax: "Winamax, à vérifier", estimee: "estimée" };
const LEAGUE_COLOR = { "Ligue 1": "#1a3a8f", "Premier League": "#3d195b", "Liga": "#e0301e", "Serie A": "#008fd7", "Bundesliga": "#d20515" };
const KIT = ["#c8102e", "#0057b8", "#e3a400", "#00843d", "#6c1d45", "#26323a", "#e35205", "#0095c8", "#7a2582", "#b5121b", "#1f6f50", "#3949ab"];

function crest(name, cls) {
  const words = String(name).replace(/\b(FC|AS|RC|SC|TSG|VfB|VfL|FSV|CA|CF|AC|BC|1\.)\b/g, "").replace(/[0-9.]/g, "").trim().split(/\s+/).filter(Boolean);
  const ini = words.length === 1 ? words[0].slice(0, 3) : words.slice(0, 3).map((w) => w[0]).join("");
  let h = 0; for (const c of String(name)) h = (h * 31 + c.charCodeAt(0)) >>> 0;
  return `<span class="crest ${cls}" style="background:${KIT[h % KIT.length]}" aria-hidden="true">${esc(ini.toUpperCase())}</span>`;
}

/* --------------------------------------------------------------- calculs */
function legOdds(c, i) {
  const o = overrides()[c.id];
  return o && o[i] ? o[i] : c.legs[i].odds;
}
function combo(c) {
  let odds = 1, ev = 1;
  c.legs.forEach((l, i) => { const o = legOdds(c, i); odds *= o; ev *= l.p * o; });
  const cost = 1 - ev;
  const stars = c.p >= 0.35 && cost <= 0.12 ? 3 : c.p >= 0.28 && cost <= 0.18 ? 2 : 1;
  return { odds, cost, stars };
}
function monthSpent() {
  const m = isoDay(new Date()).slice(0, 7);
  return Object.values(bets()).filter((b) => (b.date || "").slice(0, 7) === m).reduce((s, b) => s + b.mise, 0);
}
function findCombo(id) {
  return (today?.combos || []).find((c) => c.id === id) || (hist?.combos || []).find((c) => c.id === id) || bets()[id]?.snap;
}

/* --------------------------------------------------------------- tickets */
function legHtml(c, l, i) {
  const ov = (overrides()[c.id] || {})[i];
  return `<div class="leg">
    <div class="crests">${crest(l.home, "h")}${crest(l.away, "a")}</div>
    <div class="pick"><b>${esc(l.label)}</b><span class="vs">${esc(l.home)} contre ${esc(l.away)}</span>
      <div class="meta"><span class="tag">${esc(l.league)}</span><span class="tag">${when(l.kickoff)}</span><span class="tag">${pct(l.p)}</span>${res}</div></div>
    <button class="odd ${esc(l.src)} ${ov ? "edited" : ""}" data-combo="${esc(c.id)}" data-leg="${i}" aria-label="Corriger la cote">
      ${fmt(ov || l.odds)}<small>${ov ? "ta cote" : esc(SRC[l.src] || l.src)}</small></button>
  </div>`;
}

function ticketHtml(c) {
  const k = combo(c), b = bets()[c.id];
  const mise = b ? b.mise : c.stake;
  const gain = b && c.status !== "en attente" ? (c.status === "gagne" ? b.mise * (b.odds - 1) : -b.mise) : null;
  const stamp = c.status === "gagne" ? "GAGNÉ" : c.status === "perdu" ? "PERDU" : b ? "JOUÉ" : "";
  const stampCls = c.status === "gagne" ? "gagne" : c.status === "perdu" ? "perdu" : "joue";
  const costCls = k.cost <= 0.12 ? "cost-low" : k.cost > 0.18 ? "cost-high" : "";
  let action;
  if (b) action = `<button class="btn played" data-bet="${esc(c.id)}">${gain !== null ? eur(gain) : `Joué ${fmt(b.mise, 0)} €`}</button>`;
  else if (c.status === "en attente") action = `<button class="btn" data-bet="${esc(c.id)}">Je le joue</button>`;
  else action = "";
  const folie = c.kind === "folie";
  const head = folie
    ? `<span class="kind">Folie du jour, ${c.legs.length} matchs</span><span class="fun">pour le fun</span>`
    : `<span class="kind">Combiné ${c.kind === "x3" ? "de 3" : "de 2"}</span>
      <span class="stars" aria-label="${k.stars} étoile${k.stars > 1 ? "s" : ""} sur 3">${[1, 2, 3].map((n) => `<i class="${n <= k.stars ? "on" : ""}"></i>`).join("")}</span>`;
  return `<article class="ticket ${c.status} ${folie ? "folie" : ""}">
    <div class="board">
      ${head}
      <div class="score">
        <div class="cote">${fmt(k.odds)}<small>cote</small></div>
        <div class="stat">${c.p < 0.1 ? fmt(c.p * 100, 1) + " %" : pct(c.p)}<small>de chance</small></div>
        <div class="stat ${costCls}">${Math.round(k.cost * 100)} %<small>de coût</small></div>
      </div>
    </div>
    ${stamp ? `<div class="stamp ${stampCls} ${freshStamp === c.id ? "fresh" : ""}">${stamp}</div>` : ""}
    <div class="legs">${c.legs.map((l, i) => legHtml(c, l, i)).join("")}</div>
    <div class="perf"><span class="notch"></span></div>
    <div class="stub">
      <div class="gain">${gainText(c, k, b, mise)}</div>
      ${action}
    </div>
  </article>`;
}

function gainText(c, k, b, mise) {
  if (c.status === "en attente") return `<b>${fmt(mise * k.odds)} €</b>à gagner pour ${fmt(mise, 0)} € ${b ? "misés" : "conseillés"}`;
  if (!b) return `<b>${c.status === "gagne" ? "Passé" : "Raté"}</b>ticket non joué`;
  return c.status === "gagne" ? `<b>${fmt(b.mise * b.odds)} €</b>récupérés pour ${fmt(b.mise, 0)} € misés` : `<b>${fmt(b.mise, 0)} € perdus</b>ce coup-ci`;
}

const EMPTY_BALL = `<svg viewBox="0 0 48 48" aria-hidden="true"><circle cx="24" cy="24" r="21"/><path d="M24 13l8 6-3 9h-10l-3-9z"/><path d="M24 3v10M32 19l10-4M29 28l6 9M19 28l-6 9M16 19l-10-4"/></svg>`;

function renderCombos() {
  const el = document.getElementById("tab-combos");
  const t = isoDay(new Date());
  const current = (today?.combos || []).filter((c) => c.day >= t);
  let h = "";
  if (!current.length) h += `<div class="empty">${EMPTY_BALL}<b>Pas de ticket pour l'instant</b>
    <p>Le robot prépare les combinés vers 8h et 17h les jours de match. Touche le ballon pour lancer une actualisation.</p></div>`;
  for (const d of [...new Set(current.map((c) => c.day))].sort()) {
    const [a, b] = dayTitle(d);
    h += `<div class="day"><h2>${esc(a)}</h2><span>${esc(b)}</span></div>` + current.filter((c) => c.day === d).sort((x, y) => kindOrder(x) - kindOrder(y)).map(ticketHtml).join("");
  }
  const recent = (hist?.combos || []).filter((c) => c.day < t && c.day >= isoDay(new Date(Date.now() - 3 * 864e5)));
  for (const d of [...new Set(recent.map((c) => c.day))].sort().reverse()) {
    const [a, b] = dayTitle(d);
    h += `<div class="day"><h2>${esc(a)}</h2><span>${esc(b)}</span></div>` + recent.filter((c) => c.day === d).sort((x, y) => kindOrder(x) - kindOrder(y)).map(ticketHtml).join("");
  }
  el.innerHTML = h;
  freshStamp = null;
}

/* --------------------------------------------------------------- matchs */
function renderMatchs() {
  const el = document.getElementById("tab-matchs");
  const ms = today?.matches || [];
  if (!ms.length) { el.innerHTML = `<div class="empty">${EMPTY_BALL}<b>Aucun match chargé</b><p>Les matchs des deux prochains jours apparaîtront après le passage du robot.</p></div>`; return; }
  let h = "";
  for (const d of [...new Set(ms.map((m) => m.day))].sort()) {
    const [a, b] = dayTitle(d);
    h += `<div class="day"><h2>${esc(a)}</h2><span>${esc(b)}</span></div>`;
    for (const lg of [...new Set(ms.filter((m) => m.day === d).map((m) => m.league))]) {
      h += `<div class="league" style="--lc:${LEAGUE_COLOR[lg] || "var(--pelouse-2)"}">${esc(lg)}</div>`;
      for (const m of ms.filter((x) => x.day === d && x.league === lg)) {
        const s = Object.fromEntries(m.sel.map((x) => [x.market, x]));
        const p1 = s["1"]?.p || 0, pN = s["N"]?.p || 0, p2 = s["2"]?.p || 0;
        const extras = m.sel.filter((x) => !["1", "N", "2"].includes(x.market)).map((x) => {
          const lab = x.market.startsWith("H") ? `${x.market === "H1" ? m.home : m.away} par 2 buts ou +` : x.label;
          return `<span class="extra">${esc(lab)} <b>${pct(x.p)}</b> à ${fmt(x.odds)}${x.src === "estimee" ? " (estimée)" : ""}</span>`;
        }).join("");
        h += `<div class="match">
          <div class="mhead">
            <div class="team">${crest(m.home, "")}<span>${esc(m.home)}</span></div>
            <div class="kick">${hour(m.kickoff)}<small>${esc(new Date(m.kickoff).toLocaleDateString("fr-FR", { weekday: "short", day: "numeric", month: "short", timeZone: "Europe/Paris" }))}</small></div>
            <div class="team away">${crest(m.away, "")}<span>${esc(m.away)}</span></div>
          </div>
          <div class="tri" role="img" aria-label="Victoire ${esc(m.home)} ${pct(p1)}, nul ${pct(pN)}, victoire ${esc(m.away)} ${pct(p2)}">
            <div class="h" style="flex:${p1}">${pct(p1)}</div><div class="n" style="flex:${pN}">${pct(pN)}</div><div class="a" style="flex:${p2}">${pct(p2)}</div>
          </div>
          <div class="tri-odds"><span>1 à ${fmt(s["1"]?.odds || 0)}</span><span>nul à ${fmt(s["N"]?.odds || 0)}</span><span>2 à ${fmt(s["2"]?.odds || 0)}</span></div>
          <div class="extras">${extras}</div>
        </div>`;
      }
    }
  }
  el.innerHTML = h + `<p class="hint" style="margin:6px 4px 20px">Cotes Unibet pour la victoire et le nul, PMU pour les buts.</p>`;
}

/* --------------------------------------------------------------- bilan */
function compare(annonce, reelle) {
  return `<div class="cmp">
    <div class="row2"><span>Annoncée</span><div class="bar"><i style="width:${annonce * 100}%"></i></div><b>${pct(annonce)}</b></div>
    <div class="row2"><span>Réelle</span><div class="bar real"><i style="width:${reelle * 100}%"></i></div><b>${pct(reelle)}</b></div>
  </div>`;
}

function renderBilan() {
  const el = document.getElementById("tab-bilan");
  const b = hist?.bilan || {};
  const mine = Object.entries(bets()).map(([id, x]) => ({ id, ...x, c: findCombo(id) }));
  const done = mine.filter((x) => x.c && x.c.status !== "en attente");
  const won = done.filter((x) => x.c.status === "gagne").length;
  const mise = done.reduce((s, x) => s + x.mise, 0);
  const gain = done.reduce((s, x) => s + (x.c.status === "gagne" ? x.mise * (x.odds - 1) : -x.mise), 0);

  let h = `<h2 class="section-title">Mes paris</h2><div class="panel">`;
  if (!mine.length) h += `<p class="hint" style="margin:0">Touche « Je le joue » sur un ticket pour suivre tes paris ici.</p>`;
  else {
    h += `<div class="scoreline"><div class="w"><b>${won}</b><small>gagnés</small></div><span class="sep">/</span>
      <div class="l"><b>${done.length - won}</b><small>perdus</small></div><span class="sep">/</span>
      <div><b>${mine.length - done.length}</b><small>en cours</small></div></div>
      <div class="money ${gain >= 0 ? "pos" : "neg"}">${eur(gain)}</div><p class="hint">sur ${fmt(mise, 0)} € misés</p>`;
    if (done.length) h += compare(done.reduce((s, x) => s + x.c.p, 0) / done.length, won / done.length);
  }
  h += `</div><h2 class="section-title">Tous les tickets du robot</h2><div class="panel">`;
  if (!b.n) h += `<p class="hint" style="margin:0">Aucun ticket terminé pour l'instant. Le premier bilan arrive après les matchs du jour.</p>`;
  else {
    h += `<div class="scoreline"><div class="w"><b>${b.gagnes}</b><small>gagnés</small></div><span class="sep">/</span>
      <div class="l"><b>${b.n - b.gagnes}</b><small>perdus</small></div></div>
      <div class="money ${b.bilan_2eur >= 0 ? "pos" : "neg"}">${eur(b.bilan_2eur)}</div>
      <p class="hint">en misant 2 € sur chaque ticket (${b.mise_2eur} € au total). Avec les mises conseillées : ${eur(b.bilan_mise_suggeree)} sur ${b.mise_suggeree_totale} €.</p>
      ${compare(b.reussite_annoncee, b.reussite_reelle)}
      <p class="hint">Si la réussite réelle reste proche de l'annoncée, le modèle fait son travail. Il faut une bonne centaine de tickets avant de juger : sur quelques semaines, c'est surtout de la chance.</p>`;
  }
  if (b.folie) {
    h += `<p class="hint">Folies : ${b.folie.gagnes} passée${b.folie.gagnes > 1 ? "s" : ""} sur ${b.folie.n}, ${eur(b.folie.bilan)} à 1 € la folie (comptées à part).</p>`;
  }
  h += `</div>`;
  const past = (hist?.combos || []).filter((c) => c.status !== "en attente").slice(0, 40);
  if (past.length) {
    h += `<h2 class="section-title">Historique</h2><div class="panel">` + past.map((c) => `<div class="hist">
      <span class="dot ${c.status}">${c.status === "gagne" ? "✓" : "✗"}</span>
      <div>${c.legs.map((l) => esc(l.label)).join(" + ")}<small>${esc(longDate(c.day))}</small></div>
      <span class="o">${fmt(c.odds)}</span></div>`).join("") + `</div>`;
  }
  el.innerHTML = h;
}

function renderHeader() {
  const g = today?.generated_at;
  document.getElementById("maj").textContent = g
    ? `Cotes du ${new Date(g).toLocaleDateString("fr-FR", { weekday: "long", day: "numeric", timeZone: "Europe/Paris" })} à ${hour(g)}, ${today.credits_remaining ?? "?"} crédits API`
    : "En attente du premier passage du robot";
  const s = settings(), spent = monthSpent();
  document.getElementById("budget-strip").innerHTML = `<div class="line"><span>Budget du mois</span><span><b>${fmt(spent, 0)} €</b> sur ${fmt(s.budget, 0)} €</span></div>
    <div class="gauge ${spent > s.budget ? "over" : ""}"><i style="width:${Math.min(100, (100 * spent) / Math.max(s.budget, 1))}%"></i></div>`;
}
/* --------------------------------------------------------------- tickets joués en cours */
function renderEncours() {
  const el = document.getElementById("tab-encours");
  const t = isoDay(new Date()), since = isoDay(new Date(Date.now() - 2 * 864e5));
  const mine = Object.keys(bets()).map(findCombo).filter(Boolean);
  const live = mine.filter((c) => c.status === "en attente").sort((x, y) => (x.day + x.legs[0].kickoff).localeCompare(y.day + y.legs[0].kickoff));
  const done = mine.filter((c) => c.status !== "en attente" && c.day >= since).sort((x, y) => y.day.localeCompare(x.day));
  const badge = document.getElementById("encours-badge");
  badge.hidden = !live.length; badge.textContent = live.length;
  let h = "";
  if (!live.length) h += `<div class="empty">${EMPTY_BALL}<b>Aucun ticket en cours</b><p>Touche « Je le joue » sur un ticket : il se rangera ici jusqu'à la fin de ses matchs.</p></div>`;
  else {
    const stake = live.reduce((s, c) => s + bets()[c.id].mise, 0);
    const pot = live.reduce((s, c) => s + bets()[c.id].mise * bets()[c.id].odds, 0);
    h += `<div class="day"><h2>En cours</h2><span>${live.length} ticket${live.length > 1 ? "s" : ""}, ${fmt(stake, 0)} € misés, jusqu'à ${fmt(pot)} € à gagner</span></div>`;
    h += live.map(ticketHtml).join("");
  }
  if (done.length) h += `<div class="day"><h2>Derniers résultats</h2><span>sur 2 jours</span></div>` + done.map(ticketHtml).join("");
  el.innerHTML = h;
}

function renderAll() { renderHeader(); renderEncours(); renderCombos(); renderMatchs(); renderBilan(); }

/* --------------------------------------------------------------- dialogues */
function ask(title, text, value, { clear = false, steps = null } = {}) {
  return new Promise((resolve) => {
    const d = document.getElementById("dlg"), inp = document.getElementById("dlg-input"), st = document.getElementById("dlg-steps");
    document.getElementById("dlg-title").textContent = title;
    document.getElementById("dlg-text").textContent = text;
    inp.value = value;
    inp.step = steps ? "1" : "0.01";
    st.innerHTML = steps ? steps.map((n) => `<button type="button" data-v="${n}" class="${n == value ? "sel" : ""}">${n} €</button>`).join("") : "";
    st.onclick = (e) => { const b = e.target.closest("button"); if (!b) return; inp.value = b.dataset.v;
      st.querySelectorAll("button").forEach((x) => x.classList.toggle("sel", x === b)); };
    document.getElementById("dlg-clear").style.display = clear ? "" : "none";
    d.onclose = () => resolve(d.returnValue === "ok" ? parseFloat(String(inp.value).replace(",", ".")) : d.returnValue === "clear" ? "clear" : null);
    d.returnValue = "";
    d.showModal();
    if (!steps) setTimeout(() => inp.select(), 50);
  });
}
function toast(msg, ms = 3500) {
  const t = document.createElement("div");
  t.className = "toast"; t.setAttribute("role", "status"); t.textContent = msg;
  document.body.appendChild(t); setTimeout(() => t.remove(), ms);
}

document.addEventListener("click", async (e) => {
  const odd = e.target.closest(".odd");
  if (odd) {
    const c = findCombo(odd.dataset.combo), i = +odd.dataset.leg;
    const v = await ask("Cote Unibet", `${c.legs[i].label}, ${c.legs[i].home} contre ${c.legs[i].away}`, legOdds(c, i), { clear: true });
    const ov = overrides();
    if (v === "clear") { if (ov[c.id]) delete ov[c.id][i]; }
    else if (v && v > 1) { ov[c.id] = ov[c.id] || {}; ov[c.id][i] = v; }
    LS.set("pf_overrides", ov); renderAll(); return;
  }
  const bt = e.target.closest("[data-bet]");
  if (bt) {
    const c = findCombo(bt.dataset.bet), all = bets();
    if (all[c.id]) {
      if (c.status !== "en attente") return;
      const v = await ask("Modifier la mise", "Mets 0 pour retirer ce pari de ton suivi.", all[c.id].mise, { steps: [0, 1, 2, 3, 4, 5] });
      if (v === null || isNaN(v)) return;
      if (v <= 0) delete all[c.id]; else all[c.id].mise = Math.min(v, 5);
    } else {
      const left = settings().budget - monthSpent();
      const v = await ask("Combien tu mises ?", c.kind === "folie" ? `Pour le fun : 1 € suffit, ${fmt(combo(c).odds)} fois la mise si ça passe. Il te reste ${fmt(Math.max(left, 0), 0)} € dans ton budget du mois.`
        : `${c.stake} € conseillés. Il te reste ${fmt(Math.max(left, 0), 0)} € dans ton budget du mois.`, c.stake, { steps: c.kind === "folie" ? [1, 2] : [1, 2, 3, 4, 5] });
      if (!v || isNaN(v) || v <= 0) return;
      if (v > left && !confirm("Cette mise dépasse ton budget du mois. La garder quand même ?")) return;
      all[c.id] = { mise: Math.min(v, 5), odds: +combo(c).odds.toFixed(2), date: isoDay(new Date()), snap: c };
      freshStamp = c.id;
    }
    LS.set("pf_bets", all); renderAll(); return;
  }
  const tab = e.target.closest(".tabs button");
  if (tab) {
    document.querySelectorAll(".tabs button").forEach((b) => b.classList.toggle("active", b === tab));
    document.querySelectorAll(".tab").forEach((s) => s.classList.toggle("active", s.id === "tab-" + tab.dataset.tab));
    window.scrollTo(0, 0);
  }
});

/* --------------------------------------------------------------- réglages et actualisation */
function repoGuess() {
  const s = settings();
  if (s.repo) return s.repo;
  const host = location.hostname;
  if (host.endsWith(".github.io")) return host.split(".")[0] + "/" + (location.pathname.split("/")[1] || "");
  return "";
}
function loadSettings() {
  const s = settings();
  document.getElementById("budget").value = s.budget;
  document.getElementById("token").value = s.token;
  document.getElementById("repo").value = s.repo;
  document.getElementById("repo").placeholder = repoGuess() || "compte/nom-du-dépôt";
}
document.getElementById("save-settings").onclick = () => {
  LS.set("pf_settings", {
    budget: +document.getElementById("budget").value || 40,
    token: document.getElementById("token").value.trim(),
    repo: document.getElementById("repo").value.trim(),
  });
  document.getElementById("settings-msg").textContent = "Réglages enregistrés sur ce téléphone.";
  renderAll();
};

document.getElementById("refresh").onclick = async () => {
  const s = settings(), repo = repoGuess(), btn = document.getElementById("refresh");
  const before = today?.generated_at;
  if (!s.token) {
    // sans jeton : on ouvre la page du robot sur GitHub (appli GitHub ou navigateur), il reste a toucher "Run workflow"
    window.open(`https://github.com/${repo || "Ritemo/paris-foot"}/actions/workflows/robot.yml`, "_blank");
    toast("Sur GitHub, touche « Run workflow ». Les cotes arrivent ici 2 à 3 minutes après.", 6000);
    btn.classList.add("spin");
    for (let i = 0; i < 30; i++) {
      await new Promise((ok) => setTimeout(ok, 15000));
      await load(true);
      if (today?.generated_at !== before) { toast("Cotes à jour."); break; }
    }
    btn.classList.remove("spin");
    return;
  }
  btn.classList.add("spin");
  try {
    const r = await fetch(`https://api.github.com/repos/${repo}/actions/workflows/robot.yml/dispatches`, {
      method: "POST", headers: { Authorization: `Bearer ${s.token}`, Accept: "application/vnd.github+json" },
      body: JSON.stringify({ ref: "main" }),
    });
    if (r.status !== 204) throw new Error(r.status === 401 || r.status === 403 ? "jeton GitHub refusé, vérifie-le dans Réglages" : "GitHub a répondu " + r.status);
    toast("Robot lancé. Les nouvelles cotes arrivent dans 2 à 3 minutes.", 5000);
    for (let i = 0; i < 24; i++) {
      await new Promise((ok) => setTimeout(ok, 15000));
      await load(true);
      if (today?.generated_at !== before) { toast("Cotes à jour."); break; }
    }
  } catch (err) { toast("Actualisation impossible : " + err.message); }
  btn.classList.remove("spin");
};

async function load(quiet) {
  const get = (f) => fetch(`data/${f}?t=${Date.now()}`, { cache: "no-store" }).then((r) => (r.ok ? r.json() : null)).catch(() => null);
  [today, hist, meta] = await Promise.all([get("today.json"), get("history.json"), get("meta.json")]);
  if (today) LS.set("pf_cache", { today, hist }); else if (!quiet) ({ today, hist } = LS.get("pf_cache", {}));
  renderAll();
}

loadSettings();
load();
if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});
