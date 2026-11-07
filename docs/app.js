/* Combinés Foot : tickets du robot et suivi des paris joués (enregistrés sur le téléphone). */
const LS = {
  get(k, d) { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch {} },
};
let today = null, hist = null, meta = null, model = null, freshStamp = null, LOGOS = {};
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
const kindOrder = (c) => (c.kind === "folie" ? 9 : c.kind === "perso" ? 0 : c.kind === "x3" ? 2 : 1);
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
const LEAGUE_COLOR = { "Ligue 1": "#1a3a8f", "Premier League": "#3d195b", "Liga": "#e0301e", "Serie A": "#008fd7", "Bundesliga": "#d20515",
  "Ligue des champions": "#0b1f6b", "Ligue Europa": "#f26722" };
const KIT = ["#c8102e", "#0057b8", "#e3a400", "#00843d", "#6c1d45", "#26323a", "#e35205", "#0095c8", "#7a2582", "#b5121b", "#1f6f50", "#3949ab"];

// logo du club (ESPN) si connu, sinon pastille aux initiales ; si l'image ne charge pas, on retombe sur les initiales
const logoSmall = (u) => u.replace("https://a.espncdn.com/", "https://a.espncdn.com/combiner/i?img=/").replace(/\.png$/, ".png&w=96&h=96");
function crestFail(img) {
  if (!img.dataset.f) { img.dataset.f = "1"; img.src = img.dataset.raw; return; }
  img.parentNode.classList.remove("has-logo"); img.remove();
}
function crest(name, cls) {
  const lg = LOGOS[name];
  const words = String(name).replace(/\b(FC|AS|RC|SC|TSG|VfB|VfL|FSV|CA|CF|AC|BC|1\.)\b/g, "").replace(/[0-9.]/g, "").trim().split(/\s+/).filter(Boolean);
  const ini = words.length === 1 ? words[0].slice(0, 3) : words.slice(0, 3).map((w) => w[0]).join("");
  let h = 0; for (const c of String(name)) h = (h * 31 + c.charCodeAt(0)) >>> 0;
  const bg = lg?.color && lg.color.length === 7 ? lg.color : KIT[h % KIT.length];
  // couleur de club très claire (blanc, jaune pâle) : initiales en foncé et léger contour pour rester lisibles
  const lum = (() => { const n = parseInt(bg.slice(1), 16); return isNaN(n) ? 0 : (0.299 * (n >> 16) + 0.587 * ((n >> 8) & 255) + 0.114 * (n & 255)) / 255; })();
  const img = lg?.logo ? `<img src="${esc(logoSmall(lg.logo))}" data-raw="${esc(lg.logo)}" alt="" loading="lazy" decoding="async" onerror="crestFail(this)">` : "";
  return `<span class="crest ${cls} ${img ? "has-logo" : ""} ${lum > 0.7 ? "light" : ""}" style="--kit:${bg}" aria-hidden="true">${esc(ini.toUpperCase())}${img}</span>`;
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
  // étoiles : intérêt du ticket = son prix et sa ressemblance avec ton style de jeu (même formule que le robot)
  const it = interest(c.p, cost, c.legs.length);
  // Unibet arrondit la cote totale au centième le plus proche (2,465 -> 2,47), puis gain = mise x cote totale
  return { odds: Math.round(odds * 100 + 1e-6) / 100, cost, stars: it.stars, score: it.score, price: it.price, fit: it.fit };
}
// ton style de jeu : 0 = petit gain sûr (cote visée ~1,7), 1 = gros gain (cote visée ~4,5) ; et le poids du prix dans la note
const clamp01 = (x, d) => (isNaN(+x) ? d : Math.min(1, Math.max(0, +x)));
const style = () => clamp01(LS.get("pf_style", 0.25), 0.25);
const priceW = () => clamp01(LS.get("pf_pricew", 0.5), 0.5);
const targetOdds = (st = style()) => Math.exp(Math.log(1.7) + st * Math.log(4.5 / 1.7));
function interest(p, cost, n = 2, wp = priceW(), st = style()) {
  const perLeg = 1 - Math.pow(1 - Math.max(cost, 0), 1 / Math.max(n, 1));
  const price = Math.min(1, Math.max(0, (0.13 - perLeg) / 0.09));    // 4 % de marge par sélection = excellent, 13 % = cher
  const odds = (1 - cost) / Math.max(p, 1e-9);
  const fit = Math.max(0, 1 - Math.abs(Math.log(odds / targetOdds(st))) / Math.log(2));   // 0 dès qu'on est 2 fois au-dessus ou en dessous de la cote visée
  const score = wp * price + (1 - wp) * fit;
  return { score, price, fit, stars: score >= 0.62 ? 3 : score >= 0.45 ? 2 : 1 };
}
// un ticket joué garde la cote à laquelle tu l'as pris : si tu corriges une cote, on recalcule la cote du ticket joué
function syncBetOdds(id) {
  const all = bets(), b = all[id], c = findCombo(id);
  if (!b || !c) return;
  // cote totale arrondie comme Unibet
  const odds = combo(c).odds;
  if (Math.abs((b.odds || 0) - odds) > 1e-6) {
    b.odds = odds; LS.set("pf_bets", all);
    if (typeof publishPlayed === "function" && c.status === "en attente") publishPlayed("add", id, b);
  }
}
/* bankroll : ton solde Unibet = point de départ + dépôts - retraits + résultat des paris depuis cette date - mises en jeu */
// { start: date, moves: [{date, kind, amount, note}] } ; par défaut : dépôt de départ de 30 € à la date de ton premier pari
const bank = () => {
  const B = LS.get("pf_bank", null);
  if (B) return B;
  const first = Object.values(LS.get("pf_bets", {})).map((x) => x.date).filter(Boolean).sort()[0];
  if (!first) return null;
  const init = { start: first, moves: [{ date: first, kind: "depart", amount: 30, note: "Dépôt de départ" }] };
  LS.set("pf_bank", init);
  return init;
};
function bankroll() {
  const B = bank();
  if (!B) return null;
  // tous tes paris comptent, depuis ton dépôt de départ
  const moves = B.moves.reduce((x, m) => x + m.amount, 0);
  let gains = 0, pertes = 0, engaged = 0;
  for (const [id, b] of Object.entries(bets())) {
    const c = findCombo(id);
    if (!c) continue;
    if (c.status === "en attente") engaged += b.mise;
    else if (c.status === "gagne") gains += b.mise * (b.odds - 1);
    else pertes += b.mise;
  }
  const first = B.moves.find((m) => m.kind === "depart");
  return { value: moves + gains - pertes - engaged, engaged, gains, pertes, result: gains - pertes, moves,
    depart: first ? first.amount : 0, flows: moves - (first ? first.amount : 0), start: B.start };
}
function addBankMove(kind, amount, note) {
  const B = bank() || { start: isoDay(new Date()), moves: [] };
  B.moves.push({ date: isoDay(new Date()), kind, amount: +amount.toFixed(2), note });
  LS.set("pf_bank", B);
}

function monthSpent() {
  const m = isoDay(new Date()).slice(0, 7);
  return Object.values(bets()).filter((b) => (b.date || "").slice(0, 7) === m).reduce((s, b) => s + b.mise, 0);
}
function findCombo(id) {
  const c = (today?.combos || []).find((x) => x.id === id) || (hist?.combos || []).find((x) => x.id === id)
    || (bets()[id] ? null : (today?.alts || []).find((x) => x.id === id));
  const snap = bets()[id]?.snap;
  // résultat déjà connu par l'appli (scores ESPN) alors que le robot n'est pas encore repassé
  if (c && c.status === "en attente" && snap && snap.status !== "en attente") return snap;
  return c || snap;
}

/* deux notes : étoiles = intérêt du ticket (prix et chance, selon ta balance) ; rang = place parmi les tickets du même jour */
const PRICE = { 3: "très intéressant", 2: "intéressant", 1: "peu intéressant" };
function starsHtml(n) {
  return `<span class="stars" aria-label="${n} étoile${n > 1 ? "s" : ""} sur 3, ${PRICE[n]}">${[1, 2, 3].map((i) => `<i class="${i <= n ? "on" : ""}"></i>`).join("")}<em>${PRICE[n]}</em></span>`;
}
const ticketScore = (c) => combo(c).score;   // même critère que le robot, avec ta balance
// les meilleurs tickets d'un jour selon ta balance : ceux du robot et ses autres candidats, sans sélection en commun
function dayPicks(day, n = 3) {
  const now = new Date().toISOString();
  const seen = new Set(), pool = [];
  for (const c of [...(today?.combos || []), ...(today?.alts || [])]) {
    if (c.day !== day || c.kind === "folie" || c.replaced || seen.has(c.id) || c.status !== "en attente" || !c.legs.every((l) => l.kickoff > now)) continue;
    seen.add(c.id); pool.push(c);
  }
  pool.sort((a, b) => ticketScore(b) - ticketScore(a));
  const out = [], used = new Set();
  for (const c of pool) {
    const keys = c.legs.map((l) => l.match_id + ":" + l.market);
    if (keys.some((k) => used.has(k))) continue;
    out.push(c); keys.forEach((k) => used.add(k));
    if (out.length === n) break;
  }
  return out;
}
function dayRank(c, extra = false) {
  const pool = dayPicks(c.day);
  if (extra || !pool.some((x) => x.id === c.id)) pool.push(c);
  if (pool.length < 2) return null;
  const sc = ticketScore(c);
  return { rank: 1 + pool.filter((x) => x.id !== c.id && ticketScore(x) > sc).length, of: pool.length };
}
function rankHtml(r, verb = "") {
  return `<span class="rank ${r.rank === 1 ? "top" : ""}">${verb}${r.rank === 1 ? "1er" : r.rank + "e"} du jour sur ${r.of}</span>`;
}

/* --------------------------------------------------------------- tickets */
function legHtml(c, l, i) {
  const ov = (overrides()[c.id] || {})[i];
  const res = l.won === true ? `<span class="tag win">✓ ${esc(l.score)}</span>` : l.won === false ? `<span class="tag loss">✗ ${esc(l.score)}</span>` : "";
  return `<div class="leg">
    <div class="pick"><b>${esc(l.label)}</b><span class="vs"><span class="vt">${crest(l.home, "mini")}${esc(l.home)}</span><i>contre</i><span class="vt">${crest(l.away, "mini")}${esc(l.away)}</span></span>
      <div class="meta"><span class="tag">${esc(l.league)}</span><span class="tag">${when(l.kickoff)}</span><span class="tag">${pct(l.p)}</span>${res}</div>${bets()[c.id] && l.won === undefined ? liveLegHtml(l) : ""}</div>
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
  if (b) action = `<button class="btn played" data-bet="${esc(c.id)}">${gain !== null ? eur(gain) : `Joué ${fmtMise(b.mise)} €`}</button>`;
  else if (c.status === "en attente") action = `<button class="btn" data-bet="${esc(c.id)}">Je le joue</button>`;
  else action = "";
  if (b) action += betActions(c);
  const folie = c.kind === "folie";
  const rk = folie ? null : dayRank(c);
  const head = folie
    ? `<span class="kind">Folie du jour, ${c.legs.length} matchs</span><span class="fun">pour le fun</span>`
    : `<span class="kind">${c.kind === "perso" ? `Mon combiné de ${c.legs.length}` : `Combiné ${c.kind === "x3" ? "de 3" : "de 2"}`}</span>
      ${starsHtml(k.stars)}${rk ? rankHtml(rk) : ""}
      <div class="mix" aria-label="Prix ${Math.round(k.price * 10)} sur 10, proche de ton style ${Math.round(k.fit * 10)} sur 10">
        <span>Prix<i style="--v:${Math.round(k.price * 100)}%"></i></span><span>Ton style<i style="--v:${Math.round(k.fit * 100)}%"></i></span>${c.alt ? `<em class="alt-tag">pour ton style</em>` : ""}</div>`;
  return `<article class="ticket ${c.status} ${folie ? "folie" : ""} ${c.kind === "perso" ? "perso" : ""} ${b ? "is-played" : ""}">
    <div class="board">
      ${head}
      <div class="score">
        <div class="cote">${fmt(k.odds)}<small>cote</small></div>
        <div class="stat">${c.p < 0.1 ? fmt(c.p * 100, 1) + " %" : pct(c.p)}<small>de chance</small></div>
        <div class="stat ${costCls}">${Math.round(k.cost * 100)} %<small>de coût</small></div>
      </div>
    </div>
    ${b && c.status === "en attente" ? liveTicketHtml(c) : ""}
    <div class="legs">${c.legs.map((l, i) => legHtml(c, l, i)).join("")}</div>
    <div class="perf"><span class="notch"></span></div>
    <div class="stub">
      ${stamp ? `<div class="stamp ${stampCls} ${freshStamp === c.id ? "fresh" : ""}">${stamp}</div>` : ""}
      <div class="gain">${gainText(c, k, b, mise)}${c.status === "en attente" ? `<button class="sim-btn" data-sim="${esc(c.id)}">Simuler 100 fois</button>` : ""}</div>
      ${action}
    </div>
  </article>`;
}

function gainText(c, k, b, mise) {
  if (c.status === "en attente") return `<b>${fmt(mise * k.odds)} €</b>à gagner pour ${fmtMise(mise)} € ${b ? "misés" : "conseillés"}<span class="exp-loss">perte moyenne à la longue : ${fmt(mise * Math.max(k.cost, 0))} € par ticket</span>`;
  if (!b) return `<b>${c.status === "gagne" ? "Passé" : "Raté"}</b>ticket non joué`;
  return c.status === "gagne" ? `<b>${fmt(b.mise * b.odds)} €</b>récupérés pour ${fmtMise(b.mise)} € misés` : `<b>${fmtMise(b.mise)} € perdus</b>ce coup-ci`;
}

const EMPTY_BALL = `<svg viewBox="0 0 48 48" aria-hidden="true"><circle cx="24" cy="24" r="21"/><path d="M24 13l8 6-3 9h-10l-3-9z"/><path d="M24 3v10M32 19l10-4M29 28l6 9M19 28l-6 9M16 19l-10-4"/></svg>`;

function renderCombos() {
  const el = document.getElementById("tab-combos");
  const t = isoDay(new Date()), now = new Date().toISOString();
  // seuls les tickets encore jouables : aucun de leurs matchs n'a commencé (les tickets joués vivent dans « En cours »)
  const all = (today?.combos || []).filter((c) => c.day >= t && !c.replaced);
  const days = [...new Set(all.map((c) => c.day).concat((today?.alts || []).map((c) => c.day)))].filter((d) => d >= t).sort();
  const playable = (c) => c.status === "en attente" && c.legs.every((l) => l.kickoff > now);
  const current = days.flatMap((d) => [...dayPicks(d), ...all.filter((c) => c.day === d && c.kind === "folie" && playable(c))]);
  const gone = all.filter((c) => !playable(c)).length;
  // les réglages restent en place (et en haut de l'écran) : seule la liste des tickets est redessinée
  if (!document.getElementById("style")) {
    const st = style(), wp = priceW();
    el.innerHTML = `<div class="balance panel no-swipe"><div class="bal-head"><b>Ton style de jeu</b><span id="bal-label">${styleLabel(st)}</span></div>
      <input id="style" type="range" min="0" max="100" step="5" value="${Math.round(st * 100)}" aria-label="Style de jeu, du petit gain sûr au gros gain">
      <div class="bal-ends"><span>Petit gain sûr</span><span>Gros gain</span></div>
      <div class="pw" role="radiogroup" aria-label="Importance du prix"><span>Poids du prix</span>${[[0.3, "faible"], [0.5, "normal"], [0.7, "fort"]]
        .map(([v, t]) => `<button type="button" role="radio" data-pw="${v}" aria-checked="${Math.abs(wp - v) < 0.01}">${t}</button>`).join("")}</div></div><div id="combos-list"></div>`;
  }
  let h = "";
  if (!current.length) h += `<div class="empty">${EMPTY_BALL}<b>Plus de ticket jouable pour l'instant</b>
    <p>Les tickets disparaissent dès qu'un de leurs matchs commence. Les suivants arrivent vers 8h et 17h les jours de match.</p></div>`;
  for (const d of [...new Set(current.map((c) => c.day))].sort()) {
    const [a, b] = dayTitle(d);
    h += `<div class="day"><h2>${esc(a)}</h2><span>${esc(b)}</span></div>` + current.filter((c) => c.day === d).map(ticketHtml).join("");
  }
  if (gone) h += `<p class="hint" style="margin:14px 4px 24px">${gone} ticket${gone > 1 ? "s" : ""} retiré${gone > 1 ? "s" : ""} car un match a commencé : tes tickets joués sont dans « En cours », les résultats dans le Bilan.</p>`;
  document.getElementById("combos-list").innerHTML = h;
  freshStamp = null;
}
setInterval(() => { if (!document.hidden) renderCombos(); }, 60e3);
function styleLabel(st) {
  const t = targetOdds(st), p = Math.round(100 * 0.82 / t);   // chance typique à cette cote, marge comprise
  return `vise une cote de ${fmt(t, 1)}, environ ${p} % de chance`;
}
// le style se règle en direct : les tickets se reclassent pendant que tu bouges le curseur
document.addEventListener("input", (e) => {
  if (e.target.id !== "style") return;
  const st = +e.target.value / 100;
  LS.set("pf_style", st);
  document.getElementById("bal-label").textContent = styleLabel(st);
  clearTimeout(window.__balT);
  window.__balT = setTimeout(() => { renderCombos(); renderComposer(); }, 80);
});
document.addEventListener("click", (e) => {
  const b = e.target.closest("[data-pw]");
  if (!b) return;
  LS.set("pf_pricew", +b.dataset.pw);
  document.querySelectorAll("[data-pw]").forEach((x) => x.setAttribute("aria-checked", x === b));
  buzz(); renderCombos(); renderComposer();
});

/* --------------------------------------------------------------- matchs */
function renderMatchs() {
  const el = document.getElementById("tab-matchs");
  const ms = today?.matches || [];
  if (!ms.length) { el.innerHTML = `<div class="empty">${EMPTY_BALL}<b>Aucun match chargé</b><p>Les matchs des deux prochains jours apparaîtront après le passage du robot.</p></div>`; return; }
  const leagues = [...new Set(ms.map((m) => m.league))];
  let lf = LS.get("pf_league", "");
  if (lf && !leagues.includes(lf)) lf = "";
  const open = LS.get("pf_open", {}), dr = draft();
  let h = `<div class="chips no-swipe" role="tablist">${["", ...leagues].map((lg) => `<button class="chip ${lg === lf ? "on" : ""}" data-league="${esc(lg)}" style="--lc:${LEAGUE_COLOR[lg] || "var(--pelouse-2)"}">${lg ? esc(lg) : "Tous"}<small>${ms.filter((m) => !lg || m.league === lg).length}</small></button>`).join("")}</div>`;
  for (const d of [...new Set(ms.filter((m) => !lf || m.league === lf).map((m) => m.day))].sort()) {
    const [a, b] = dayTitle(d);
    h += `<div class="day"><h2>${esc(a)}</h2><span>${esc(b)}</span></div>`;
    for (const lg of [...new Set(ms.filter((m) => m.day === d && (!lf || m.league === lf)).map((m) => m.league))]) {
      h += `<div class="league" style="--lc:${LEAGUE_COLOR[lg] || "var(--pelouse-2)"}">${esc(lg)}</div>`;
      for (const m of ms.filter((x) => x.day === d && x.league === lg)) {
        const s = Object.fromEntries(m.sel.map((x) => [x.market, x]));
        const p1 = s["1"]?.p || 0, pN = s["N"]?.p || 0, p2 = s["2"]?.p || 0;
        const pb = (mk, txt) => (s[mk] ? pickBtn(m, s[mk], txt) : "");
        const lines = m.sel.filter((x) => /^[+-]\d/.test(x.market)).sort((a, b) => parseFloat(a.market.slice(1)) - parseFloat(b.market.slice(1)) || (a.market[0] === "+" ? -1 : 1));
        const hcp = m.sel.filter((x) => x.market === "H1" || x.market === "H2");
        const extras = `
          ${s["1N"] || s["12"] || s["N2"] ? `<div class="mk-title">Double chance</div><div class="picks3">${pb("1N", "1N")}${pb("12", "12")}${pb("N2", "N2")}</div>` : ""}
          ${s.BTTS ? `<div class="mk-title">Les deux équipes marquent</div><div class="picks2">${pb("BTTS", `Oui, ${pct(s.BTTS.p)}`)}${pb("NBTTS", `Non, ${pct(s.NBTTS?.p || 0)}`)}</div>` : ""}
          ${lines.length ? `<div class="mk-title">Nombre de buts</div><div class="picks2">${lines.map((x) => pickBtn(m, x, `${x.market[0] === "+" ? "Plus" : "Moins"} de ${x.market.slice(1).replace(".", ",")}, ${pct(x.p)}`)).join("")}</div>` : ""}
          ${hcp.length ? `<div class="mk-title">Handicap</div>${hcp.map((x) => pickBtn(m, x, `${x.market === "H1" ? m.home : m.away} par 2 buts ou +, ${pct(x.p)}`)).join("")}` : ""}`;
        const started = new Date(m.kickoff) <= new Date();
        const nExtra = m.sel.filter((x) => !["1", "N", "2"].includes(x.market)).length;
        const isOpen = open[m.id] || (dr[m.id] && !["1", "N", "2"].includes(dr[m.id]));
        h += `<div class="match ${isOpen ? "open" : ""}">
          <div class="mhead">
            <div class="team">${crest(m.home, "")}<span>${esc(m.home)}</span></div>
            <div class="kick">${hour(m.kickoff)}<small>${esc(new Date(m.kickoff).toLocaleDateString("fr-FR", { weekday: "short", day: "numeric", month: "short", timeZone: "Europe/Paris" }))}</small></div>
            <div class="team away">${crest(m.away, "")}<span>${esc(m.away)}</span></div>
          </div>
          <div class="tri" role="img" aria-label="Victoire ${esc(m.home)} ${pct(p1)}, nul ${pct(pN)}, victoire ${esc(m.away)} ${pct(p2)}">
            <div class="h" style="flex:${p1}">${pct(p1)}</div><div class="n" style="flex:${pN}">${pct(pN)}</div><div class="a" style="flex:${p2}">${pct(p2)}</div>
          </div>
          ${started ? `<p class="hint">Match commencé.</p>` : `<div class="picks3">${s["1"] ? pickBtn(m, s["1"], "1") : ""}${s["N"] ? pickBtn(m, s["N"], "Nul") : ""}${s["2"] ? pickBtn(m, s["2"], "2") : ""}</div>
          ${nExtra ? `<button class="more" data-more="${esc(m.id)}" aria-expanded="${!!isOpen}"><span>Plus de paris</span><small>${nExtra}</small><i aria-hidden="true"></i></button>` : ""}
          <div class="extras">${extras}</div>`}
        </div>`;
      }
    }
  }
  el.innerHTML = `<p class="hint" style="margin:16px 4px 0">Touche les cotes pour composer ton propre combiné.</p>` + h
    + `<p class="hint" style="margin:6px 4px 20px">Cotes Unibet pour la victoire et le nul, PMU pour les buts, * = estimée.</p>`;
}

/* --------------------------------------------------------------- bilan */
function compare(annonce, reelle) {
  return `<div class="cmp">
    <div class="row2"><span>Annoncée</span><div class="bar"><i style="width:${annonce * 100}%"></i></div><b>${pct(annonce)}</b></div>
    <div class="row2"><span>Réelle</span><div class="bar real"><i style="width:${reelle * 100}%"></i></div><b>${pct(reelle)}</b></div>
  </div>`;
}

/* rentabilité : gain réel / mise, comparée à ce que la marge des bookmakers laissait espérer */
const roiTxt = (r) => (r > 0 ? "+" : r < 0 ? "−" : "") + Math.abs(Math.round(r * 100)) + " %";
function roiBlock(real, expected) {
  const luck = real - expected;
  return `<div class="roi">
    <div class="roi-main ${real >= 0 ? "pos" : "neg"}"><small>Rentabilité</small><b>${roiTxt(real)}</b><span>de ta mise</span></div>
    <div class="roi-side"><small>Attendue</small><b>${roiTxt(expected)}</b><span>Écart : ${roiTxt(luck)}</span></div>
  </div>
  <p class="hint">La rentabilité attendue, c'est ce que tes tickets valaient d'après les chances du robot et les cotes (en général un peu négative, à cause de la marge des bookmakers). L'écart vient de la chance du moment et de tes choix : la partie « Ton flair » plus bas aide à faire la part des deux.</p>`;
}

/* jauge du flair : de -100 à +100 points, rouge, orange autour de 0, vert */
function flairGauge(diff, enough) {
  const real = Math.round(diff * 100), v = Math.max(-100, Math.min(100, real));
  const pos = (v + 100) / 2;
  const label = v <= -40 ? "Tri à revoir" : v < -10 ? "Plutôt défavorable" : v <= 10 ? "Neutre" : v < 40 ? "Plutôt bon" : "Bon flair";
  return `<div class="gauge-flair ${enough ? "" : "early"}" role="img" aria-label="Jauge du flair : ${label}, ${v >= 0 ? "+" : ""}${v} points">
    <div class="gf-track"><i class="gf-needle" data-pos="${pos}" style="left:${pos}%"><span style="transform:translateX(-${pos}%)">${real >= 0 ? "+" : "−"}${Math.abs(real)}</span></i></div>
    <div class="gf-scale"><span>−100</span><span>0</span><span>+100</span></div>
    <div class="gf-label">${label}${enough ? "" : " (provisoire)"}</div>
  </div>`;
}

/* carte bankroll en tête du bilan */
function bankCard() {
  const br = bankroll();
  if (!br) return `<div class="panel bank" style="margin-top:14px"><b class="bank-title">Ta bankroll</b>
    <p class="hint">Indique ton dépôt de départ : l'appli calcule tes gains, tes pertes et ton montant disponible à partir de tous tes paris.</p>
    <button class="btn" data-bank="init">Indiquer mon dépôt de départ</button></div>`;
  const row = (label, val, cls = "") => `<div class="bank-row"><span>${label}</span><b class="${cls}">${val}</b></div>`;
  return `<div class="panel bank" style="margin-top:14px">
    <div class="bank-head"><b class="bank-title">Ta bankroll</b>${(() => { const d = new Date(String(br.start).slice(0, 10) + "T12:00:00"); return isNaN(d) ? "" : `<span>départ le ${esc(d.toLocaleDateString("fr-FR", { day: "numeric", month: "long" }))}</span>`; })()}</div>
    <div class="bank-value ${br.value >= br.moves ? "" : "down"}" data-count="${br.value.toFixed(2)}" data-count-key="bankcard">${fmt(br.value)} €</div>
    <p class="hint" style="margin:0">disponible${br.engaged ? `, plus ${fmt(br.engaged)} € en jeu` : ""}</p>
    ${row("Dépôt de départ", `${fmt(br.depart)} €`)}
    ${br.flows ? row("Dépôts et retraits ensuite", `${br.flows > 0 ? "+" : "−"}${fmt(Math.abs(br.flows))} €`) : ""}
    ${row("Gains", `+${fmt(br.gains)} €`, "pos")}
    ${row("Pertes", `−${fmt(br.pertes)} €`, "neg")}
    ${br.engaged ? row("En jeu", `−${fmt(br.engaged)} €`) : ""}
    ${row("Résultat", `${eur(br.result)}${br.moves ? ` (${roiTxt(br.result / br.moves)})` : ""}`, br.result >= 0 ? "pos" : "neg")}
    <div class="bank-btns">
      <button class="btn ghost" data-bank="depot">Dépôt</button><button class="btn ghost" data-bank="retrait">Retrait</button>
      <button class="btn ghost" data-bank="init">Départ</button></div>
  </div>`;
}

/* ton flair : les tickets du robot que tu as choisis de jouer font-ils mieux que ceux que tu as laissés ? */
function flair(mine) {
  const playedIds = new Set(mine.map((x) => x.id));
  const days = new Set(mine.map((x) => x.c.day));
  const flat = (c) => (c.status === "gagne" ? c.odds - 1 : -1);   // même mise pour tous : seul le choix compte
  const pool = (hist?.combos || []).filter((c) => days.has(c.day) && c.status !== "en attente" && (!c.replaced || playedIds.has(c.id)));
  const played = pool.filter((c) => playedIds.has(c.id)).map((c) => findCombo(c.id) || c);
  const left = pool.filter((c) => !playedIds.has(c.id));
  if (!played.length || !left.length) return "";
  const avg = (a) => a.reduce((s, c) => s + flat(c), 0) / a.length;
  const rp = avg(played), rl = avg(left), diff = rp - rl;
  const hp = played.filter((c) => c.status === "gagne").length, hl = left.filter((c) => c.status === "gagne").length;
  const enough = played.length >= 15 && left.length >= 15;
  return `<h2 class="section-title">Ton flair</h2><div class="panel">
    <div class="flair">
      <div><small>Tickets que tu as joués</small><b class="${rp >= 0 ? "pos" : "neg"}">${roiTxt(rp)}</b><span>${hp} gagné${hp > 1 ? "s" : ""} sur ${played.length}</span></div>
      <div><small>Tickets que tu as laissés</small><b class="${rl >= 0 ? "pos" : "neg"}">${roiTxt(rl)}</b><span>${hl} gagné${hl > 1 ? "s" : ""} sur ${left.length}</span></div>
    </div>
    ${flairGauge(diff, enough)}
    <div class="flair-verdict ${diff >= 0 ? "pos" : "neg"}">Ton tri vaut <b>${diff >= 0 ? "+" : "−"}${Math.abs(Math.round(diff * 100))} points</b> de rentabilité
      ${diff >= 0 ? "par rapport aux tickets que tu as écartés" : "de moins que les tickets que tu as écartés"}</div>
    <p class="hint">Même mise pour chaque ticket, pour ne mesurer que tes choix, sur les jours où tu as joué. ${enough ? "Il y a assez de tickets pour que l'écart commence à avoir un sens." : `Encore trop peu de tickets pour conclure (il en faut une quinzaine de chaque côté) : pour l'instant, la chance pèse plus que le flair.`}</p>
  </div>`;
}

/* courbe du solde et bilan mensuel de mes paris */
function myCharts(done) {
  if (!done.length) return "";
  const rows = done.map((x) => ({ day: x.c.day, g: x.c.status === "gagne" ? x.mise * (x.odds - 1) : -x.mise, mise: x.mise,
    back: x.c.status === "gagne" ? x.mise * x.odds : 0 }))
    .sort((a, b) => a.day.localeCompare(b.day));
  let cum = 0;
  const pts = [{ v: 0 }].concat(rows.map((r) => ({ v: (cum += r.g), day: r.day })));
  let h = `<h2 class="section-title">Mon solde</h2><div class="panel">`;
  if (pts.length >= 3) {
    const W = 320, H = 130, pad = 8;
    const vs = pts.map((p) => p.v), lo = Math.min(0, ...vs), hi = Math.max(0, ...vs), span = hi - lo || 1;
    const X = (i) => pad + (i * (W - 2 * pad)) / (pts.length - 1), Y = (v) => pad + ((hi - v) * (H - 2 * pad)) / span;
    const line = pts.map((p, i) => `${X(i).toFixed(1)},${Y(p.v).toFixed(1)}`).join(" ");
    const last = pts[pts.length - 1].v;
    h += `<svg class="curve" viewBox="0 0 ${W} ${H}" role="img" aria-label="Évolution de ton solde, ${eur(last)} au total">
      <line x1="${pad}" x2="${W - pad}" y1="${Y(0)}" y2="${Y(0)}" class="zero"/>
      <polygon points="${X(0)},${Y(0)} ${line} ${X(pts.length - 1)},${Y(0)}" class="${last >= 0 ? "area-pos" : "area-neg"}"/>
      <polyline points="${line}" class="${last >= 0 ? "pos" : "neg"}"/>
      <circle cx="${X(pts.length - 1)}" cy="${Y(last)}" r="4" class="${last >= 0 ? "pos" : "neg"}"/></svg>
      <p class="hint">Après chaque pari terminé, du premier au dernier. La ligne fine marque 0 €.</p>`;
  } else h += `<p class="hint" style="margin:0">La courbe apparaît à partir de 2 paris terminés.</p>`;
  const months = {};
  for (const r of rows) { const m = r.day.slice(0, 7); months[m] = months[m] || { n: 0, mise: 0, g: 0, back: 0 }; months[m].n++; months[m].mise += r.mise; months[m].g += r.g; months[m].back += r.back; }
  h += `<table class="months"><thead><tr><th>Mois</th><th>Misé</th><th>Récupéré</th><th>Gain réel</th><th>Renta.</th></tr></thead><tbody>` +
    Object.keys(months).sort().reverse().map((m) => {
      const label = new Date(m + "-15").toLocaleDateString("fr-FR", { month: "long", year: "numeric" });
      return `<tr><td>${esc(label)}<small>${months[m].n} pari${months[m].n > 1 ? "s" : ""}</small></td><td>${fmt(months[m].mise)} €</td><td>${fmt(months[m].back)} €</td><td class="${months[m].g >= 0 ? "pos" : "neg"}">${eur(months[m].g)}</td><td class="${months[m].g >= 0 ? "pos" : "neg"}">${roiTxt(months[m].g / months[m].mise)}</td></tr>`;
    }).join("") + `</tbody></table></div>`;
  return h;
}

/* réussite par type de sélection, sur une liste de tickets */
function marketStats(combos, note) {
  const cats = { "Victoire": (m) => m === "1" || m === "2", "Match nul": (m) => m === "N", "Plus de buts": (m) => m[0] === "+",
    "Moins de buts": (m) => m[0] === "-", "Handicap": (m) => m[0] === "H" };
  const acc = {};
  for (const c of combos) {
    for (const l of c.legs) {
      if (l.won === undefined) continue;
      const k = Object.keys(cats).find((n) => cats[n](l.market));
      if (!k) continue;
      acc[k] = acc[k] || { n: 0, w: 0, p: 0 }; acc[k].n++; acc[k].w += l.won ? 1 : 0; acc[k].p += l.p;
    }
  }
  const keys = Object.keys(acc);
  if (!keys.length) return "";
  return `<h2 class="section-title">Réussite par type de pari</h2><div class="panel">` + keys.map((k) => {
    const a = acc[k];
    return `<div class="mstat"><div class="mstat-head"><b>${esc(k)}</b><span>${a.w} sur ${a.n} sélection${a.n > 1 ? "s" : ""}</span></div>${compare(a.p / a.n, a.w / a.n)}</div>`;
  }).join("") + `<p class="hint">${note}</p></div>`;
}

let bilanView = LS.get("pf_bilan_view", "mine");

function renderBilan() {
  const el = document.getElementById("tab-bilan");
  const seg = `<div class="seg" role="tablist">
    <button role="tab" data-bview="mine" aria-selected="${bilanView === "mine"}" class="${bilanView === "mine" ? "on" : ""}">Mes paris</button>
    <button role="tab" data-bview="robot" aria-selected="${bilanView === "robot"}" class="${bilanView === "robot" ? "on" : ""}">Qualité des tickets proposés</button></div>`;
  el.innerHTML = seg + (bilanView === "mine" ? bilanMine() : bilanRobot());
}

/* ---- mes paris : l'essentiel du bilan */
function bilanMine() {
  const mine = Object.entries(bets()).map(([id, x]) => ({ id, ...x, c: findCombo(id) })).filter((x) => x.c);
  const done = mine.filter((x) => x.c.status !== "en attente");
  const won = done.filter((x) => x.c.status === "gagne").length;
  const mise = done.reduce((s, x) => s + x.mise, 0);
  const gain = done.reduce((s, x) => s + (x.c.status === "gagne" ? x.mise * (x.odds - 1) : -x.mise), 0);
  let h = bankCard();
  h += backupDue() ? `<div class="panel backup-nudge"><b>Pense à sauvegarder tes paris</b><p class="hint">Ils ne sont stockés que sur ce téléphone. ${backupInfo()} Onglet Réglages, bouton « Sauvegarder ».</p></div>` : "";
  h += `<div class="panel" style="margin-top:14px">`;
  if (!mine.length) return h + `<p class="hint" style="margin:0">Touche « Je le joue » sur un ticket : ton bilan se construira ici, pari après pari.</p></div>`;
  h += `<div class="scoreline"><div class="w"><b>${won}</b><small>gagnés</small></div><span class="sep">/</span>
      <div class="l"><b>${done.length - won}</b><small>perdus</small></div><span class="sep">/</span>
      <div><b>${mine.length - done.length}</b><small>en cours</small></div></div>
    <div class="cash">
      <div><small>Misé</small><b>${fmt(mise)} €</b></div>
      <div><small>Récupéré</small><b>${fmt(mise + gain)} €</b></div>
      <div class="net ${gain >= 0 ? "pos" : "neg"}"><small>Gain réel</small><b data-count="${gain.toFixed(2)}" data-count-key="gain" data-sign="1">${eur(gain)}</b></div>
    </div>
    ${mise ? roiBlock(gain / mise, done.reduce((s, x) => s + x.mise * (x.c.p * x.odds - 1), 0) / mise) : ""}
    <p class="hint">Récupéré = ce que les tickets gagnants t'ont rapporté, mise comprise. Gain réel = récupéré moins tout ce que tu as misé.</p>`;
  if (done.length) h += compare(done.reduce((s, x) => s + x.c.p, 0) / done.length, won / done.length);
  h += `</div>` + flair(mine) + myCharts(done);
  h += marketStats(done.map((x) => x.c), "Sur les matchs de tes tickets joués.");
  if (done.length) {
    h += `<h2 class="section-title">Mes tickets terminés</h2><div class="panel">` + done.sort((a, b) => b.c.day.localeCompare(a.c.day)).map((x) => {
      const g = x.c.status === "gagne" ? x.mise * (x.odds - 1) : -x.mise;
      return `<div class="hist"><span class="dot ${x.c.status}">${x.c.status === "gagne" ? "✓" : "✗"}</span>
        <div><ul class="hist-legs">${x.c.legs.map((l) => `<li class="${l.won === true ? "w" : l.won === false ? "l" : "u"}"><i aria-hidden="true">${l.won === true ? "✓" : l.won === false ? "✗" : "…"}</i>
          <span>${esc(l.label)}<small>${esc(l.home)} ${l.score ? `<b>${esc(l.score)}</b>` : "contre"} ${esc(l.away)}${l.won === undefined ? " · pas encore joué" : ""}</small></span></li>`).join("")}</ul><small>${esc(longDate(x.c.day))}, ${fmtMise(x.mise)} € misés à ${fmt(x.odds)}${x.c.status === "gagne" ? `, ${fmt(x.mise * x.odds)} € récupérés` : ""}</small>
          <span class="hist-act"><button type="button" data-act="edit" data-id="${esc(x.c.id)}">Changer la mise</button><button type="button" class="danger" data-act="cancel" data-id="${esc(x.c.id)}">Annuler</button></span></div>
        <span class="o ${g >= 0 ? "pos" : "neg"}">${eur(g)}</span></div>`;
    }).join("") + `</div>`;
  }
  return h + missedWinners();
}

/* tickets gagnants du robot que tu n'as pas joués (14 derniers jours), et en face les perdants que tu as évités */
function missedWinners() {
  const since = isoDay(new Date(Date.now() - 14 * 864e5));
  const left = (hist?.combos || []).filter((c) => !c.replaced && !bets()[c.id] && c.day >= since && c.status !== "en attente");
  if (!left.length) return "";
  const stake = (c) => (c.kind === "folie" ? 1 : 2);
  const won = left.filter((c) => c.status === "gagne").sort((a, b) => b.day.localeCompare(a.day));
  const lost = left.filter((c) => c.status === "perdu");
  const missed = won.reduce((s, c) => s + stake(c) * (c.odds - 1), 0), avoided = lost.reduce((s, c) => s + stake(c), 0);
  const net = missed - avoided;
  let h = `<h2 class="section-title">Tickets passés sans toi</h2><div class="panel">
    <div class="flair">
      <div><small>Gagnants non joués</small><b class="pos">${won.length}</b><span>${eur(missed)} manqués</span></div>
      <div><small>Perdants évités</small><b class="neg">${lost.length}</b><span>${fmt(avoided)} € épargnés</span></div>
    </div>
    <p class="hint">Sur les 14 derniers jours, à 2 € par ticket (1 € la Folie). Au total, laisser ces tickets ${net >= 0 ? `t'a privé de ${fmt(net)} €` : `t'a fait économiser ${fmt(-net)} €`}.</p>`;
  if (won.length) {
    h += won.map((c) => `<div class="hist"><span class="dot gagne">✓</span>
      <div>${c.legs.map((l) => esc(l.label) + (l.score ? ` <small style="display:inline">(${esc(l.home)} ${esc(l.score)} ${esc(l.away)})</small>` : "")).join(" + ")}
        <small>${esc(longDate(c.day))}, ${c.kind === "folie" ? "Folie du jour" : "★".repeat(combo(c).stars)}, ${stake(c)} € auraient rapporté ${fmt(stake(c) * c.odds)} €</small></div>
      <span class="o">${fmt(c.odds)}</span></div>`).join("");
  } else h += `<p class="hint" style="margin:0">Aucun ticket gagnant laissé de côté ces 14 derniers jours.</p>`;
  return h + `</div>`;
}

/* ---- qualité de tous les tickets proposés par le robot, par étoiles et folie */
function bilanRobot() {
  // un ticket remplacé par une version plus récente compte quand même si tu l'as joué
  const all = (hist?.combos || []).filter((c) => (!c.replaced || bets()[c.id]) && c.status !== "en attente")
    .map((c) => { const x = findCombo(c.id); return x && x.status !== "en attente" ? x : c; });
  if (!all.length) return `<div class="panel" style="margin-top:14px"><p class="hint" style="margin:0">Aucun ticket terminé pour l'instant.</p></div>`;
  const st = (c) => combo(c).stars;  // même règle pour tous les tickets, anciens compris
  const groups = [["3 étoiles", (c) => c.kind !== "folie" && st(c) === 3, 2], ["2 étoiles", (c) => c.kind !== "folie" && st(c) === 2, 2],
    ["1 étoile", (c) => c.kind !== "folie" && st(c) <= 1, 2], ["Folies du jour", (c) => c.kind === "folie", 1]];
  const pending = (hist?.combos || []).filter((c) => !c.replaced && c.status === "en attente").length;
  let h = `<p class="hint" style="margin:14px 4px">Tickets proposés par le robot et terminés, joués ou non, pour juger si ses notes tiennent la route.${pending ? ` ${pending} ticket${pending > 1 ? "s" : ""} encore en cours ${pending > 1 ? "seront comptés" : "sera compté"} à la fin de leurs matchs.` : ""} Il faut plusieurs dizaines de tickets par groupe avant d'en tirer une conclusion.</p>`;
  for (const [name, f, stake] of groups) {
    const g = all.filter(f);
    if (!g.length) continue;
    const w = g.filter((c) => c.status === "gagne").length;
    const bil = g.reduce((s, c) => s + (c.status === "gagne" ? stake * (c.odds - 1) : -stake), 0);
    h += `<details class="panel grp"><summary><div class="grp-head"><b>${esc(name)}</b><span>${w} gagné${w > 1 ? "s" : ""} sur ${g.length}</span>
        <span class="${bil >= 0 ? "pos" : "neg"}">${eur(bil)}</span></div>
        <p class="hint" style="margin:2px 0 0">à ${stake} € par ticket, cote moyenne ${fmt(g.reduce((s, c) => s + c.odds, 0) / g.length)}, rentabilité <b class="${bil >= 0 ? "pos" : "neg"}">${roiTxt(bil / (stake * g.length))}</b></p>
        ${compare(g.reduce((s, c) => s + c.p, 0) / g.length, w / g.length)}</summary>` +
      g.map((c) => `<div class="hist"><span class="dot ${c.status}">${c.status === "gagne" ? "✓" : "✗"}</span>
        <div>${c.legs.map((l) => esc(l.label)).join(" + ")}<small>${esc(longDate(c.day))}${bets()[c.id] ? ", joué" : ""}</small></div>
        <span class="o">${fmt(c.odds)}</span></div>`).join("") + `</details>`;
  }
  h += marketStats(all, "Sur tous les tickets proposés. Un type de pari qui réussit nettement moins qu'annoncé sur plusieurs dizaines de sélections mérite d'être évité.");
  return h;
}

function renderHeader() {
  const g = today?.generated_at;
  document.getElementById("maj").textContent = g
    ? `Cotes du ${new Date(g).toLocaleDateString("fr-FR", { weekday: "long", day: "numeric", timeZone: "Europe/Paris" })} à ${hour(g)}, ${today.credits_remaining ?? "?"} crédits API`
    : "En attente du premier passage du robot";
  const s = settings(), spent = monthSpent();
  const br = bankroll();
  document.getElementById("budget-strip").innerHTML = (br ? `<div class="line bank-line"><span>Bankroll</span><span><b data-count="${br.value.toFixed(2)}" data-count-key="bankhead">${fmt(br.value)} €</b>${br.engaged ? ` + ${fmt(br.engaged)} € en jeu` : ""}</span></div>` : "") +
    `<div class="line"><span>Budget du mois</span><span><b>${fmt(spent, 0)} €</b> sur ${fmt(s.budget, 0)} €</span></div>
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
    h += `<div class="day"><h2>En cours</h2><span>${live.length} ticket${live.length > 1 ? "s" : ""}, ${fmtMise(stake)} € misés, jusqu'à ${fmt(pot)} € à gagner</span></div>`;
    h += liveStatusLine() + live.map(ticketHtml).join("");
  }
  if (done.length) h += `<div class="day"><h2>Derniers résultats</h2><span>sur 2 jours</span></div>` + done.map(ticketHtml).join("");
  el.innerHTML = h;
}

function renderAll() {
  renderHeader(); renderEncours(); renderCombos(); renderMatchs(); renderBilan(); renderModele(); renderComposer();
  animateCounters(); flashGoals(); animateGauge();
  if (!document.querySelector(".celebrate")) celebrate();
}
function animateGauge() {
  document.querySelectorAll(".gf-needle[data-pos]").forEach((n) => {
    if (n.dataset.done) return;
    n.dataset.done = "1";
    if (calm()) return;
    n.style.left = "50%";
    requestAnimationFrame(() => requestAnimationFrame(() => { n.style.left = n.dataset.pos + "%"; }));
  });
}

/* --------------------------------------------------------------- dialogues */
function ask(title, text, value, { clear = false, steps = null } = {}) {
  return new Promise((resolve) => {
    const d = document.getElementById("dlg"), inp = document.getElementById("dlg-input"), st = document.getElementById("dlg-steps");
    document.getElementById("dlg-title").textContent = title;
    document.getElementById("dlg-text").textContent = text;
    inp.value = value === "" || value === null || value === undefined ? "" : String(value).replace(".", ",");
    st.innerHTML = steps ? steps.map((n) => `<button type="button" data-v="${n}" class="${n == value ? "sel" : ""}">${n} €</button>`).join("") : "";
    st.onclick = (e) => { const b = e.target.closest("button"); if (!b) return; inp.value = String(b.dataset.v).replace(".", ",");
      st.querySelectorAll("button").forEach((x) => x.classList.toggle("sel", x === b)); };
    document.getElementById("dlg-clear").style.display = clear ? "" : "none";
    inp.oninput = () => st.querySelectorAll("button").forEach((x) => x.classList.toggle("sel", parseNum(inp.value) === +x.dataset.v));
    d.onclose = () => resolve(d.returnValue === "ok" ? parseNum(inp.value) : d.returnValue === "clear" ? "clear" : null);
    d.returnValue = "";
    d.showModal();
    setTimeout(() => inp.select(), 50);
  });
}
// montants saisis au clavier français : « 1,31 » comme « 1.31 », arrondis au centime
const parseNum = (t) => { const v = parseFloat(String(t).trim().replace(/\s|€/g, "").replace(",", ".")); return isNaN(v) ? NaN : Math.round(v * 100) / 100; };
const fmtMise = (v) => (Math.abs(v - Math.round(v)) < 1e-9 ? fmt(v, 0) : fmt(v));
/* corriger une erreur : changer la mise, annuler le pari, ou (combiné perso pas commencé) changer ses sélections */
function betActions(c) {
  const id = esc(c.id), notStarted = c.status === "en attente" && c.legs.every((l) => new Date(l.kickoff) > new Date());
  return `<div class="bet-actions">
    <button type="button" data-act="edit" data-id="${id}">Changer la mise</button>
    ${c.kind === "perso" && notStarted ? `<button type="button" data-act="change" data-id="${id}">Changer les sélections</button>` : ""}
    <button type="button" class="danger" data-act="cancel" data-id="${id}">Annuler le pari</button></div>`;
}
async function editMise(id) {
  const all = bets(); if (!all[id]) return;
  const v = await ask("Changer la mise", "Le montant que tu as vraiment misé sur Unibet.", all[id].mise, { steps: [1, 2, 3, 4, 5] });
  if (v === null || isNaN(v) || v <= 0) return;
  all[id].mise = v; LS.set("pf_bets", all); renderAll(); syncPlayed(); toast(`Mise corrigée : ${fmtMise(v)} €.`);
}
function cancelBet(id, { quiet = false } = {}) {
  const all = bets(), old = all[id]; if (!old) return;
  delete all[id]; LS.set("pf_bets", all); renderAll(); syncPlayed();
  if (!quiet) undoToast("Pari annulé : il sort de ton suivi et de ton bilan.", () => { const a = bets(); a[id] = old; LS.set("pf_bets", a); renderAll(); syncPlayed(); scheduleLive(); });
}
function undoToast(msg, undo, ms = 6000) {
  document.querySelectorAll(".toast.undo").forEach((x) => x.remove());
  const t = document.createElement("div");
  t.className = "toast undo"; t.setAttribute("role", "status");
  t.innerHTML = `<span>${esc(msg)}</span><button type="button">Rétablir</button>`;
  t.querySelector("button").onclick = () => { t.remove(); undo(); toast("Pari rétabli."); };
  document.body.appendChild(t); setTimeout(() => t.remove(), ms);
}
document.addEventListener("click", async (e) => {
  const a = e.target.closest("[data-act]");
  if (!a) return;
  const id = a.dataset.id, c = findCombo(id), b = bets()[id];
  if (!b) return;
  if (a.dataset.act === "edit") return editMise(id);
  if (a.dataset.act === "cancel") {
    if (!confirm(`Annuler ce pari de ${fmtMise(b.mise)} € ?`)) return;
    return cancelBet(id);
  }
  if (a.dataset.act === "change" && c) {
    const d = {}; c.legs.forEach((l) => { d[l.match_id] = l.market; });
    LS.set("pf_draft", d); cancelBet(id, { quiet: true });
    showTab("matchs"); renderMatchs(); renderComposer();
    toast("Tes sélections sont reprises : modifie-les puis touche « Je le joue ».", 5000);
  }
});

// touche Entrée dans une fenêtre de saisie = Valider (et non le premier bouton, « Annuler »)
document.addEventListener("keydown", (e) => {
  if (e.key !== "Enter" || !e.target.matches("dialog[open] input")) return;
  e.preventDefault(); e.target.closest("dialog").close("ok");
});

/* avant de jouer : les cotes qui ne viennent pas d'Unibet (PMU, Betclic, estimées) sont à vérifier sur ton ticket Unibet */
const SRC_NAME = { pmu: "cote PMU", betclic: "cote Betclic", estimee: "cote estimée" };
function checkOdds(c) {
  const ov = overrides()[c.id] || {};
  const idx = c.legs.map((l, i) => i).filter((i) => c.legs[i].src !== "unibet" && !ov[i]);
  if (!idx.length) return Promise.resolve(true);
  const d = document.getElementById("dlg-odds"), rows = document.getElementById("odds-rows"), tot = document.getElementById("odds-total");
  rows.innerHTML = idx.map((i) => { const l = c.legs[i]; return `<label class="odds-row"><span><b>${esc(l.label)}</b><small>${esc(l.home)} - ${esc(l.away)} · ${SRC_NAME[l.src] || l.src}</small></span>
    <input type="text" inputmode="decimal" autocomplete="off" data-i="${i}" value="${String(legOdds(c, i)).replace(".", ",")}" aria-label="Cote Unibet : ${esc(l.label)}"></label>`; }).join("");
  const total = () => {
    let o = 1;
    c.legs.forEach((l, i) => { const inp = rows.querySelector(`[data-i="${i}"]`); const v = inp ? parseNum(inp.value) : legOdds(c, i); o *= v > 1 ? v : legOdds(c, i); });
    return Math.round(o * 100 + 1e-6) / 100;
  };
  const upd = () => { tot.textContent = fmt(total()); };
  rows.oninput = upd; upd();
  return new Promise((resolve) => {
    d.onclose = () => {
      if (d.returnValue === "cancel") return resolve(false);
      if (d.returnValue === "skip") return resolve(true);
      const all = overrides(), o = Object.assign({}, all[c.id] || {});
      rows.querySelectorAll("[data-i]").forEach((inp) => { const v = parseNum(inp.value); if (v > 1 && v < 100) o[inp.dataset.i] = v; });
      all[c.id] = o; LS.set("pf_overrides", all);
      resolve(true);
    };
    d.returnValue = ""; d.showModal();
    setTimeout(() => rows.querySelector("input")?.select(), 50);
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
    LS.set("pf_overrides", ov); syncBetOdds(c.id); renderAll(); return;
  }
  const bt = e.target.closest("[data-bet]");
  if (bt) {
    const c = findCombo(bt.dataset.bet), all = bets();
    if (all[c.id]) {
      if (c.status !== "en attente") return;
      const v = await ask("Modifier la mise", "Mets 0 pour retirer ce pari de ton suivi.", all[c.id].mise, { steps: [0, 1, 2, 3, 4, 5] });
      if (v === null || isNaN(v)) return;
      if (v <= 0) delete all[c.id]; else all[c.id].mise = v;
    } else {
      if (!(await checkOdds(c))) return;
      const left = settings().budget - monthSpent();
      const v = await ask("Combien tu mises ?", c.kind === "folie" ? `Pour le fun : 1 € suffit, ${fmt(combo(c).odds)} fois la mise si ça passe. Il te reste ${fmt(Math.max(left, 0), 0)} € dans ton budget du mois.`
        : `${c.stake} € conseillés. Il te reste ${fmt(Math.max(left, 0), 0)} € dans ton budget du mois.`, c.stake, { steps: c.kind === "folie" ? [1, 2] : [1, 2, 3, 4, 5] });
      if (!v || isNaN(v) || v <= 0) return;
      if (v > left && !confirm("Cette mise dépasse ton budget du mois. La garder quand même ?")) return;
      all[c.id] = { mise: v, odds: +combo(c).odds.toFixed(4), date: isoDay(new Date()), ts: Date.now(), snap: c };
      freshStamp = c.id;
    }
    LS.set("pf_bets", all); renderAll(); scheduleLive(); syncPlayed(); return;
  }
  const bk = e.target.closest("[data-bank]");
  if (bk) {
    const k = bk.dataset.bank, br = bankroll();
    if (k === "init") {
      const B = bank();
      const cur = B ? (B.moves.find((m) => m.kind === "depart") || {}).amount : 30;
      const v = await ask("Dépôt de départ", "Ce que tu as mis sur Unibet au tout début. Tous tes paris sont comptés à partir de là.", cur ?? 30);
      if (v === null || isNaN(v) || v < 0) return;
      const firstBet = Object.values(bets()).map((b) => b.date).filter(Boolean).sort()[0] || isoDay(new Date());
      const others = B ? B.moves.filter((m) => m.kind !== "depart" && m.kind !== "ajust") : [];
      LS.set("pf_bank", { start: firstBet, moves: [{ date: firstBet, kind: "depart", amount: +v.toFixed(2), note: "Dépôt de départ" }, ...others] });
    } else if (k === "depot" || k === "retrait") {
      const v = await ask(k === "depot" ? "Dépôt sur Unibet" : "Retrait d'Unibet", "Montant en euros.", "");
      if (!v || isNaN(v) || v <= 0) return;
      addBankMove(k, k === "depot" ? v : -v, k === "depot" ? "Dépôt" : "Retrait");
    }
    renderAll(); return;
  }
  const bv = e.target.closest("[data-bview]");
  if (bv) { bilanView = bv.dataset.bview; LS.set("pf_bilan_view", bilanView); renderBilan(); return; }
  const tab = e.target.closest(".tabs button");
  if (tab) showTab(tab.dataset.tab);
  const mt = e.target.closest("[data-more]");
  if (mt) {
    const open = LS.get("pf_open", {}); open[mt.dataset.more] = !open[mt.dataset.more]; LS.set("pf_open", open);
    mt.closest(".match").classList.toggle("open", !!open[mt.dataset.more]);
    mt.setAttribute("aria-expanded", !!open[mt.dataset.more]); buzz();
  }
  const lf = e.target.closest("[data-league]");
  if (lf) { LS.set("pf_league", lf.dataset.league); buzz(); renderMatchs(); }
});

const TABS = ["combos", "encours", "matchs", "bilan", "modele", "reglages"];
const buzz = (ms = 8) => { try { if (!calm()) navigator.vibrate?.(ms); } catch {} };
function currentTab() { return document.querySelector(".tabs button.active")?.dataset.tab || "combos"; }
function showTab(name, dir = 0) {
  const prev = currentTab();
  if (!dir) dir = TABS.indexOf(name) > TABS.indexOf(prev) ? 1 : -1;
  document.querySelectorAll(".tabs button").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  document.querySelectorAll(".tab").forEach((sec) => {
    const on = sec.id === "tab-" + name;
    sec.classList.toggle("active", on);
    if (on && prev !== name && !calm()) {
      sec.classList.remove("enter-l", "enter-r"); void sec.offsetWidth;
      sec.classList.add(dir > 0 ? "enter-r" : "enter-l");
    }
  });
  if (prev !== name) { window.scrollTo(0, 0); buzz(); }
  renderComposer();
}

// glisser vers la gauche ou la droite pour changer d'onglet, tirer vers le bas en haut de page pour actualiser
(() => {
  let x0 = null, y0 = 0, t0 = 0, pull = 0, startTop = false;
  const main = document.querySelector("main");
  const ptr = document.createElement("div"); ptr.className = "ptr"; ptr.innerHTML = EMPTY_BALL; document.body.appendChild(ptr);
  main.addEventListener("touchstart", (e) => {
    if (e.touches.length !== 1 || e.target.closest("input, canvas, .no-swipe, .chips")) { x0 = null; return; }
    x0 = e.touches[0].clientX; y0 = e.touches[0].clientY; t0 = Date.now(); pull = 0; startTop = window.scrollY <= 0;
  }, { passive: true });
  main.addEventListener("touchmove", (e) => {
    if (x0 === null || !startTop) return;
    const dy = e.touches[0].clientY - y0, dx = Math.abs(e.touches[0].clientX - x0);
    if (dy > 0 && dy > dx) { pull = Math.min(dy, 140); ptr.style.transform = `translate(-50%, ${pull * 0.6}px) rotate(${pull * 3}deg)`; ptr.classList.add("show"); ptr.classList.toggle("ready", pull > 90); }
  }, { passive: true });
  main.addEventListener("touchend", async (e) => {
    if (x0 === null) return;
    const dx = e.changedTouches[0].clientX - x0, dy = e.changedTouches[0].clientY - y0;
    x0 = null;
    if (pull > 90) {
      ptr.classList.add("spin"); ptr.style.transform = "translate(-50%, 48px)";
      buzz(15); await load(true); toast("Données à jour.", 1800);
    }
    ptr.classList.remove("show", "ready", "spin"); ptr.style.transform = ""; pull = 0;
    if (Math.abs(dx) > 70 && Math.abs(dx) > 2 * Math.abs(dy) && Date.now() - t0 < 600) {
      const i = TABS.indexOf(currentTab()) + (dx < 0 ? 1 : -1);
      if (i >= 0 && i < TABS.length) showTab(TABS[i], dx < 0 ? 1 : -1);
    }
  }, { passive: true });
})();

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
/* --------------------------------------------------------------- sauvegarde des paris */
function backupInfo() {
  const last = LS.get("pf_last_export", null);
  return last ? `Dernière sauvegarde le ${new Date(last).toLocaleDateString("fr-FR", { day: "numeric", month: "long" })}.` : "Aucune sauvegarde pour l'instant.";
}
function backupDue() {
  const n = Object.keys(bets()).length, last = LS.get("pf_last_export", null);
  return n > 0 && (!last || Date.now() - new Date(last).getTime() > 14 * 864e5);
}
document.getElementById("export").onclick = async () => {
  const s = settings();
  const data = { app: "combines-foot", version: 1, date: new Date().toISOString(), bets: bets(), overrides: overrides(), budget: s.budget, bank: bank() };
  const text = JSON.stringify(data, null, 1);
  const name = `combines-foot-sauvegarde-${isoDay(new Date())}.txt`;
  const done = () => {
    LS.set("pf_last_export", new Date().toISOString());
    document.getElementById("backup-msg").textContent = `Sauvegarde créée (${Object.keys(bets()).length} paris). ${backupInfo()}`;
    renderAll();
  };
  const download = () => {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([text], { type: "text/plain" })); a.download = name;
    document.body.appendChild(a); a.click(); a.remove();
    toast("Fichier enregistré dans tes Téléchargements.");
    done();
  };
  // Android n'accepte de partager que certains types de fichiers : on passe par du texte, et on télécharge si le partage échoue
  const file = new File([text], name, { type: "text/plain" });
  try {
    if (navigator.canShare && navigator.canShare({ files: [file] })) { await navigator.share({ files: [file], title: "Sauvegarde Combinés Foot" }); done(); }
    else download();
  } catch (err) {
    if (err.name === "AbortError") return;
    try { download(); } catch (e2) { toast("Sauvegarde impossible : " + e2.message); }
  }
};
document.getElementById("import-file").onchange = async (e) => {
  const f = e.target.files[0];
  if (!f) return;
  try {
    const d = JSON.parse(await f.text());
    if (d.app !== "combines-foot" || typeof d.bets !== "object") throw new Error("ce fichier n'est pas une sauvegarde Combinés Foot");
    const merged = Object.assign({}, d.bets, bets());
    LS.set("pf_bets", merged);
    LS.set("pf_overrides", Object.assign({}, d.overrides || {}, overrides()));
    if (d.budget) LS.set("pf_settings", Object.assign(settings(), { budget: d.budget }));
    if (d.bank && !bank()) LS.set("pf_bank", d.bank);
    loadSettings(); renderAll(); scheduleLive(); syncPlayed();
    document.getElementById("backup-msg").textContent = `Restauré : ${Object.keys(merged).length} paris au total.`;
  } catch (err) { toast("Restauration impossible : " + err.message); }
  e.target.value = "";
};

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
  let logos;
  [today, hist, meta, logos, model] = await Promise.all([get("today.json"), get("history.json"), get("meta.json"), get("logos.json"), get("model.json")]);
  if (logos) LOGOS = logos;
  if (today) LS.set("pf_cache", { today, hist, logos: LOGOS, model }); else if (!quiet) ({ today, hist, logos: LOGOS = {}, model = null } = LS.get("pf_cache", {}));
  for (const id of Object.keys(bets())) syncBetOdds(id);
  renderAll();
}

loadSettings();
document.getElementById("token-show").onclick = () => {
  const t = document.getElementById("token"), shown = t.type === "text";
  t.type = shown ? "password" : "text"; document.getElementById("token-show").textContent = shown ? "Afficher" : "Masquer";
};
document.getElementById("token-copy").onclick = async () => {
  const v = document.getElementById("token").value.trim();
  if (!v) { toast("Aucun jeton enregistré dans l'appli."); return; }
  try { await navigator.clipboard.writeText(v); toast("Jeton copié."); } catch { toast("Copie impossible : touche Afficher puis sélectionne le texte."); }
};
document.getElementById("app-version").textContent = (document.querySelector('script[src^="app.js"]')?.src.split("v=")[1]) || "?";
document.getElementById("backup-msg").textContent = backupInfo();
document.getElementById("ntfy-sub").href = `ntfy://ntfy.sh/${NTFY_TOPIC}`;
document.getElementById("ntfy-topic").textContent = NTFY_TOPIC;
document.getElementById("ntfy-test").onclick = ntfyTest;
const liveBox = document.getElementById("live-alerts");
liveBox.checked = LS.get("pf_live_alerts", false) && "Notification" in window && Notification.permission === "granted";
liveBox.onchange = async () => { liveBox.checked = await toggleLiveAlerts(liveBox.checked); };
load().then(() => { scheduleLive(); syncPlayed(); });
document.addEventListener("visibilitychange", () => { if (!document.hidden) scheduleLive(); });
// mises à jour de l'appli : on vérifie à chaque retour sur l'appli, et on recharge tout seul quand une nouvelle version
// est prête (sauf si une fenêtre de saisie est ouverte : ce sera au prochain retour)
if ("serviceWorker" in navigator) {
  const hadController = !!navigator.serviceWorker.controller;
  let pendingReload = false;
  const reloadIfIdle = () => { if (document.querySelector("dialog[open]")) { pendingReload = true; return; } location.reload(); };
  navigator.serviceWorker.register("sw.js").then((reg) => {
    document.addEventListener("visibilitychange", () => {
      if (document.hidden) return;
      if (pendingReload) return reloadIfIdle();
      reg.update().catch(() => {});
    });
  }).catch(() => {});
  navigator.serviceWorker.addEventListener("controllerchange", () => { if (hadController) reloadIfIdle(); });
}
