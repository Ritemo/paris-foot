/* Combinés Foot : affiche les combinés du robot, suivi des paris joués (stockés sur le téléphone). */
const LS = {
  get(k, d) { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch {} },
};
let today = null, hist = null, meta = null;
const overrides = () => LS.get("pf_overrides", {});
const bets = () => LS.get("pf_bets", {});
const settings = () => Object.assign({ budget: 40, token: "", repo: "" }, LS.get("pf_settings", {}));

const fmt = (x, d = 2) => Number(x).toLocaleString("fr-FR", { minimumFractionDigits: d, maximumFractionDigits: d });
const pct = (x) => Math.round(x * 100) + " %";
const eur = (x) => (x > 0 ? "+" : "") + fmt(x) + " €";
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const isoDay = (d) => d.toLocaleDateString("sv-SE", { timeZone: "Europe/Paris" });
const hour = (iso) => new Date(iso).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit", timeZone: "Europe/Paris" });

function dayLabel(day) {
  const t = isoDay(new Date());
  const tm = isoDay(new Date(Date.now() + 864e5));
  const y = isoDay(new Date(Date.now() - 864e5));
  if (day === t) return "Aujourd'hui";
  if (day === tm) return "Demain";
  if (day === y) return "Hier";
  return new Date(day + "T12:00:00").toLocaleDateString("fr-FR", { weekday: "long", day: "numeric", month: "long" });
}

const SRC = { unibet: "Unibet", pmu: "PMU · à vérifier", netbet: "NetBet · à vérifier", betclic: "Betclic · à vérifier",
  winamax: "Winamax · à vérifier", estimee: "estimée · à saisir" };

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
  return (today?.combos || []).find((c) => c.id === id) || (hist?.combos || []).find((c) => c.id === id);
}

/* --------------------------------------------------------------- rendu combinés */
function legHtml(c, l, i) {
  const ov = overrides()[c.id] || {};
  const o = legOdds(c, i);
  const res = l.won === true ? `<span class="res ok">✓ ${esc(l.score)}</span>` : l.won === false ? `<span class="res ko">✗ ${esc(l.score)}</span>` : "";
  return `<div class="leg">
    <div class="what"><b>${esc(l.label)}</b>
      <small>${esc(l.home)} - ${esc(l.away)} · ${esc(l.league)} · ${hour(l.kickoff)} · chance ${pct(l.p)}</small> ${res}</div>
    <button class="odd ${l.src === "estimee" ? "estimee" : ""} ${ov[i] ? "edited" : ""}" data-combo="${esc(c.id)}" data-leg="${i}">
      ${fmt(o)}<small>${ov[i] ? "ta cote" : esc(SRC[l.src] || l.src)}</small></button>
  </div>`;
}

function comboHtml(c) {
  const k = combo(c);
  const b = bets()[c.id];
  const mise = b ? b.mise : c.stake;
  const st = c.status === "gagne" ? "Gagné" : c.status === "perdu" ? "Perdu" : "En attente";
  const gain = b && c.status !== "en attente" ? (c.status === "gagne" ? b.mise * (b.odds - 1) : -b.mise) : null;
  return `<article class="card ${c.status}">
    <div class="chead">
      <span class="kind">Combiné ${c.kind === "x3" ? "de 3" : "de 2"} <span class="stars">${"★".repeat(k.stars)}${"☆".repeat(3 - k.stars)}</span></span>
      <span class="status ${c.status}">${st}</span>
    </div>
    <div class="big">
      <div><b>${fmt(k.odds)}</b><small>cote</small></div>
      <div><b>${pct(c.p)}</b><small>chance</small></div>
      <div><b>${Math.round(k.cost * 100)} %</b><small>coût</small></div>
    </div>
    ${c.legs.map((l, i) => legHtml(c, l, i)).join("")}
    <div class="actions">
      ${b ? `<button class="btn played" data-bet="${esc(c.id)}">Joué ${fmt(b.mise, 0)} € à ${fmt(b.odds)}${gain !== null ? " · " + eur(gain) : ""}</button>`
          : c.status === "en attente" ? `<button class="btn" data-bet="${esc(c.id)}">Je le joue (${mise} € conseillés)</button>` : ""}
      <span class="sub" style="align-self:center">Gain possible : ${fmt(mise * k.odds)} € pour ${mise} €</span>
    </div>
  </article>`;
}

function renderCombos() {
  const el = document.getElementById("tab-combos");
  const t = isoDay(new Date());
  const current = (today?.combos || []).filter((c) => c.day >= t);
  const s = settings(), spent = monthSpent();
  let h = `<div class="card" style="margin-top:14px"><div class="chead"><span>Budget du mois</span><span><b>${fmt(spent, 0)}</b> / ${fmt(s.budget, 0)} €</span></div>
    <div class="bar ${spent > s.budget ? "over" : ""}"><i style="width:${Math.min(100, (100 * spent) / Math.max(s.budget, 1))}%"></i></div></div>`;
  if (!current.length) h += `<p class="empty">Pas de combiné proposé pour l'instant.<br>Le robot passe à 8h et 17h les jours de match.</p>`;
  const days = [...new Set(current.map((c) => c.day))].sort();
  for (const d of days) {
    h += `<div class="day">${dayLabel(d)}</div>` + current.filter((c) => c.day === d).map(comboHtml).join("");
  }
  const recent = (hist?.combos || []).filter((c) => c.day < t && c.day >= isoDay(new Date(Date.now() - 3 * 864e5)));
  if (recent.length) {
    h += `<h2>Derniers jours</h2>`;
    for (const d of [...new Set(recent.map((c) => c.day))].sort().reverse())
      h += `<div class="day">${dayLabel(d)}</div>` + recent.filter((c) => c.day === d).map(comboHtml).join("");
  }
  el.innerHTML = h;
}

/* --------------------------------------------------------------- rendu matchs */
function renderMatchs() {
  const el = document.getElementById("tab-matchs");
  const ms = today?.matches || [];
  if (!ms.length) { el.innerHTML = `<p class="empty">Aucun match chargé.</p>`; return; }
  let h = "";
  for (const d of [...new Set(ms.map((m) => m.day))].sort()) {
    h += `<div class="day">${dayLabel(d)}</div>`;
    for (const lg of [...new Set(ms.filter((m) => m.day === d).map((m) => m.league))]) {
      h += `<div class="league">${esc(lg)}</div>`;
      for (const m of ms.filter((x) => x.day === d && x.league === lg)) {
        const chips = m.sel.map((s) => {
          const short = s.market === "1" ? "1" : s.market === "N" ? "N" : s.market === "2" ? "2"
            : s.market.startsWith("H") ? (s.market === "H1" ? m.home : m.away) + " -1" : s.market.replace(".", ",") + " buts";
          return `<span class="chip">${esc(short)} <b>${pct(s.p)}</b> · ${fmt(s.odds)}${s.src === "estimee" ? "*" : ""}</span>`;
        }).join("");
        h += `<div class="match"><div class="mh"><span>${esc(m.home)} - ${esc(m.away)}</span><small>${hour(m.kickoff)}</small></div>
          <div class="chips">${chips}</div></div>`;
      }
    }
  }
  el.innerHTML = h + `<p class="sub" style="margin:14px 0">Chance estimée · cote (Unibet pour 1N2, PMU pour les buts, * = estimée).</p>`;
}

/* --------------------------------------------------------------- rendu bilan */
function renderBilan() {
  const el = document.getElementById("tab-bilan");
  const b = hist?.bilan || {};
  const mine = Object.entries(bets()).map(([id, x]) => ({ id, ...x, c: findCombo(id) }));
  const done = mine.filter((x) => x.c && x.c.status !== "en attente");
  const mise = done.reduce((s, x) => s + x.mise, 0);
  const gain = done.reduce((s, x) => s + (x.c.status === "gagne" ? x.mise * (x.odds - 1) : -x.mise), 0);
  let h = `<h2>Mes paris</h2><div class="kpis">
    <div class="kpi"><b>${done.length} / ${mine.length}</b><small>paris terminés / joués</small></div>
    <div class="kpi"><b class="${gain >= 0 ? "pos" : "neg"}">${eur(gain)}</b><small>bilan sur ${fmt(mise, 0)} € misés</small></div>
    <div class="kpi"><b>${done.length ? pct(done.filter((x) => x.c.status === "gagne").length / done.length) : "-"}</b><small>réussite réelle</small></div>
    <div class="kpi"><b>${done.length ? pct(done.reduce((s, x) => s + x.c.p, 0) / done.length) : "-"}</b><small>réussite annoncée</small></div>
  </div>
  <h2>Tous les combinés du robot</h2>`;
  if (!b.n) h += `<p class="empty">Pas encore de combiné terminé.</p>`;
  else {
    h += `<div class="kpis">
      <div class="kpi"><b>${b.gagnes} / ${b.n}</b><small>combinés gagnés</small></div>
      <div class="kpi"><b>${pct(b.reussite_reelle)}</b><small>réussite réelle (annoncée ${pct(b.reussite_annoncee)})</small></div>
      <div class="kpi"><b class="${b.bilan_2eur >= 0 ? "pos" : "neg"}">${eur(b.bilan_2eur)}</b><small>si 2 € sur chaque (${b.mise_2eur} € misés)</small></div>
      <div class="kpi"><b class="${b.bilan_mise_suggeree >= 0 ? "pos" : "neg"}">${eur(b.bilan_mise_suggeree)}</b><small>avec les mises conseillées (${b.mise_suggeree_totale} €)</small></div>
    </div>`;
    for (const k of ["x2", "x3"]) if (b[k]) h += `<p class="sub">Combinés ${k === "x2" ? "de 2" : "de 3"} : ${b[k].gagnes}/${b[k].n} gagnés, réussite annoncée ${pct(b[k].reussite_annoncee)}.</p>`;
    h += `<p class="sub">Tant que la réussite réelle reste proche de l'annoncée, le modèle fait son travail. Il faut une bonne centaine de combinés avant de juger : sur quelques semaines, c'est surtout de la chance.</p>`;
  }
  const past = (hist?.combos || []).filter((c) => c.status !== "en attente").slice(0, 40);
  if (past.length) {
    h += `<h2>Historique</h2>` + past.map((c) => `<div class="hist"><span>${c.status === "gagne" ? "✓" : "✗"} ${esc(c.day.slice(8))}/${esc(c.day.slice(5, 7))}
      · ${c.legs.map((l) => esc(l.label)).join(" + ")}</span><span class="${c.status === "gagne" ? "pos" : "neg"}">${fmt(c.odds)}</span></div>`).join("");
  }
  el.innerHTML = h;
}

function renderHeader() {
  const g = today?.generated_at ? new Date(today.generated_at) : null;
  document.getElementById("maj").textContent = g
    ? `Mis à jour ${g.toLocaleDateString("fr-FR", { weekday: "short", day: "numeric", timeZone: "Europe/Paris" })} à ${hour(today.generated_at)} · ${today.credits_remaining ?? "?"} crédits API`
    : "Pas encore de données";
}
function renderAll() { renderHeader(); renderCombos(); renderMatchs(); renderBilan(); }

/* --------------------------------------------------------------- dialogues */
function ask(title, text, value, { clear = false } = {}) {
  return new Promise((resolve) => {
    const d = document.getElementById("dlg");
    document.getElementById("dlg-title").textContent = title;
    document.getElementById("dlg-text").textContent = text;
    const inp = document.getElementById("dlg-input");
    inp.value = value;
    document.getElementById("dlg-clear").style.display = clear ? "" : "none";
    d.onclose = () => resolve(d.returnValue === "ok" ? parseFloat(String(inp.value).replace(",", ".")) : d.returnValue === "clear" ? "clear" : null);
    d.returnValue = "";
    d.showModal();
    setTimeout(() => inp.select(), 50);
  });
}
function toast(msg, ms = 3500) {
  const t = document.createElement("div");
  t.className = "toast"; t.textContent = msg;
  document.body.appendChild(t); setTimeout(() => t.remove(), ms);
}

document.addEventListener("click", async (e) => {
  const odd = e.target.closest(".odd");
  if (odd) {
    const c = findCombo(odd.dataset.combo), i = +odd.dataset.leg;
    const v = await ask("Cote Unibet", `${c.legs[i].label} (${c.legs[i].home} - ${c.legs[i].away})`, legOdds(c, i), { clear: true });
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
      const v = await ask("Modifier la mise", "Mets 0 pour annuler ce pari.", all[c.id].mise);
      if (v === null || isNaN(v)) return;
      if (v <= 0) delete all[c.id]; else all[c.id].mise = Math.min(v, 5);
    } else {
      const s = settings(), left = s.budget - monthSpent();
      const v = await ask("Mise", `Conseillé : ${c.stake} € (max 5 €). Reste ${fmt(left, 0)} € dans ton budget du mois.`, c.stake);
      if (!v || isNaN(v) || v <= 0) return;
      if (v > left && !confirm("Cette mise dépasse ton budget du mois. La garder quand même ?")) return;
      all[c.id] = { mise: Math.min(v, 5), odds: +combo(c).odds.toFixed(2), date: isoDay(new Date()) };
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
  document.getElementById("repo").placeholder = repoGuess() || "propriétaire/nom-du-dépôt";
}
document.getElementById("save-settings").onclick = () => {
  LS.set("pf_settings", {
    budget: +document.getElementById("budget").value || 40,
    token: document.getElementById("token").value.trim(),
    repo: document.getElementById("repo").value.trim(),
  });
  document.getElementById("settings-msg").textContent = "Enregistré sur ce téléphone.";
  renderAll();
};

document.getElementById("refresh").onclick = async () => {
  const s = settings(), repo = repoGuess(), btn = document.getElementById("refresh");
  if (!s.token || !repo) { toast("Ajoute ton jeton GitHub dans Réglages pour lancer une actualisation. En attendant, je recharge les données."); await load(); return; }
  const before = today?.generated_at;
  btn.classList.add("spin");
  try {
    const r = await fetch(`https://api.github.com/repos/${repo}/actions/workflows/robot.yml/dispatches`, {
      method: "POST", headers: { Authorization: `Bearer ${s.token}`, Accept: "application/vnd.github+json" },
      body: JSON.stringify({ ref: "main" }),
    });
    if (r.status !== 204) throw new Error("GitHub a répondu " + r.status);
    toast("Actualisation lancée (environ 2 à 3 minutes, environ 10 crédits).", 5000);
    for (let i = 0; i < 24; i++) {
      await new Promise((ok) => setTimeout(ok, 15000));
      await load(true);
      if (today?.generated_at !== before) { toast("Cotes à jour."); break; }
    }
  } catch (err) { toast("Échec : " + err.message); }
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
