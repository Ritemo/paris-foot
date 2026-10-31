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
  "Ligue des champions": "#0b1f6b" };
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
  const c = (today?.combos || []).find((x) => x.id === id) || (hist?.combos || []).find((x) => x.id === id);
  const snap = bets()[id]?.snap;
  // résultat déjà connu par l'appli (scores ESPN) alors que le robot n'est pas encore repassé
  if (c && c.status === "en attente" && snap && snap.status !== "en attente") return snap;
  return c || snap;
}

/* --------------------------------------------------------------- tickets */
function legHtml(c, l, i) {
  const ov = (overrides()[c.id] || {})[i];
  const res = l.won === true ? `<span class="tag win">✓ ${esc(l.score)}</span>` : l.won === false ? `<span class="tag loss">✗ ${esc(l.score)}</span>` : "";
  return `<div class="leg">
    <div class="crests">${crest(l.home, "h")}${crest(l.away, "a")}</div>
    <div class="pick"><b>${esc(l.label)}</b><span class="vs">${esc(l.home)} contre ${esc(l.away)}</span>
      <div class="meta"><span class="tag">${esc(l.league)}</span><span class="tag">${when(l.kickoff)}</span><span class="tag">${pct(l.p)}</span>${res}</div>${bets()[c.id] && c.status === "en attente" ? liveLegHtml(l) : ""}</div>
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
    : c.kind === "perso" ? `<span class="kind">Mon combiné de ${c.legs.length}</span><span class="fun perso">composé par toi</span>`
    : `<span class="kind">Combiné ${c.kind === "x3" ? "de 3" : "de 2"}</span>
      <span class="stars" aria-label="${k.stars} étoile${k.stars > 1 ? "s" : ""} sur 3">${[1, 2, 3].map((n) => `<i class="${n <= k.stars ? "on" : ""}"></i>`).join("")}</span>`;
  return `<article class="ticket ${c.status} ${folie ? "folie" : ""} ${c.kind === "perso" ? "perso" : ""}">
    <div class="board">
      ${head}
      <div class="score">
        <div class="cote">${fmt(k.odds)}<small>cote</small></div>
        <div class="stat">${c.p < 0.1 ? fmt(c.p * 100, 1) + " %" : pct(c.p)}<small>de chance</small></div>
        <div class="stat ${costCls}">${Math.round(k.cost * 100)} %<small>de coût</small></div>
      </div>
    </div>
    ${b && c.status === "en attente" ? liveTicketHtml(c) : ""}
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
  const t = isoDay(new Date()), now = new Date().toISOString();
  // seuls les tickets encore jouables : aucun de leurs matchs n'a commencé (les tickets joués vivent dans « En cours »)
  const all = (today?.combos || []).filter((c) => c.day >= t);
  const current = all.filter((c) => c.status === "en attente" && c.legs.every((l) => l.kickoff > now));
  const gone = all.length - current.length;
  let h = "";
  if (!current.length) h += `<div class="empty">${EMPTY_BALL}<b>Plus de ticket jouable pour l'instant</b>
    <p>Les tickets disparaissent dès qu'un de leurs matchs commence. Les suivants arrivent vers 8h et 17h les jours de match.</p></div>`;
  for (const d of [...new Set(current.map((c) => c.day))].sort()) {
    const [a, b] = dayTitle(d);
    h += `<div class="day"><h2>${esc(a)}</h2><span>${esc(b)}</span></div>` + current.filter((c) => c.day === d).sort((x, y) => kindOrder(x) - kindOrder(y)).map(ticketHtml).join("");
  }
  if (gone) h += `<p class="hint" style="margin:14px 4px 24px">${gone} ticket${gone > 1 ? "s" : ""} retiré${gone > 1 ? "s" : ""} car un match a commencé : tes tickets joués sont dans « En cours », les résultats dans le Bilan.</p>`;
  el.innerHTML = h;
  freshStamp = null;
}
setInterval(() => { if (!document.hidden) renderCombos(); }, 60e3);

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
          return pickBtn(m, x, `${lab}, ${pct(x.p)}`);
        }).join("");
        const started = new Date(m.kickoff) <= new Date();
        h += `<div class="match">
          <div class="mhead">
            <div class="team">${crest(m.home, "")}<span>${esc(m.home)}</span></div>
            <div class="kick">${hour(m.kickoff)}<small>${esc(new Date(m.kickoff).toLocaleDateString("fr-FR", { weekday: "short", day: "numeric", month: "short", timeZone: "Europe/Paris" }))}</small></div>
            <div class="team away">${crest(m.away, "")}<span>${esc(m.away)}</span></div>
          </div>
          <div class="tri" role="img" aria-label="Victoire ${esc(m.home)} ${pct(p1)}, nul ${pct(pN)}, victoire ${esc(m.away)} ${pct(p2)}">
            <div class="h" style="flex:${p1}">${pct(p1)}</div><div class="n" style="flex:${pN}">${pct(pN)}</div><div class="a" style="flex:${p2}">${pct(p2)}</div>
          </div>
          ${started ? `<p class="hint">Match commencé.</p>` : `<div class="picks3">${s["1"] ? pickBtn(m, s["1"], "1") : ""}${s["N"] ? pickBtn(m, s["N"], "Nul") : ""}${s["2"] ? pickBtn(m, s["2"], "2") : ""}</div>
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
  h += `<table class="months"><thead><tr><th>Mois</th><th>Misé</th><th>Récupéré</th><th>Gain réel</th></tr></thead><tbody>` +
    Object.keys(months).sort().reverse().map((m) => {
      const label = new Date(m + "-15").toLocaleDateString("fr-FR", { month: "long", year: "numeric" });
      return `<tr><td>${esc(label)}<small>${months[m].n} pari${months[m].n > 1 ? "s" : ""}</small></td><td>${fmt(months[m].mise)} €</td><td>${fmt(months[m].back)} €</td><td class="${months[m].g >= 0 ? "pos" : "neg"}">${eur(months[m].g)}</td></tr>`;
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
  let h = backupDue() ? `<div class="panel backup-nudge"><b>Pense à sauvegarder tes paris</b><p class="hint">Ils ne sont stockés que sur ce téléphone. ${backupInfo()} Onglet Réglages, bouton « Sauvegarder ».</p></div>` : "";
  h += `<div class="panel" style="margin-top:14px">`;
  if (!mine.length) return h + `<p class="hint" style="margin:0">Touche « Je le joue » sur un ticket : ton bilan se construira ici, pari après pari.</p></div>`;
  h += `<div class="scoreline"><div class="w"><b>${won}</b><small>gagnés</small></div><span class="sep">/</span>
      <div class="l"><b>${done.length - won}</b><small>perdus</small></div><span class="sep">/</span>
      <div><b>${mine.length - done.length}</b><small>en cours</small></div></div>
    <div class="cash">
      <div><small>Misé</small><b>${fmt(mise)} €</b></div>
      <div><small>Récupéré</small><b>${fmt(mise + gain)} €</b></div>
      <div class="net ${gain >= 0 ? "pos" : "neg"}"><small>Gain réel</small><b>${eur(gain)}</b></div>
    </div>
    <p class="hint">Récupéré = ce que les tickets gagnants t'ont rapporté, mise comprise. Gain réel = récupéré moins tout ce que tu as misé${mise ? `, soit ${gain >= 0 ? "+" : ""}${Math.round((100 * gain) / mise)} % de ta mise` : ""}.</p>`;
  if (done.length) h += compare(done.reduce((s, x) => s + x.c.p, 0) / done.length, won / done.length);
  h += `</div>` + myCharts(done);
  h += marketStats(done.map((x) => x.c), "Sur les matchs de tes tickets joués.");
  if (done.length) {
    h += `<h2 class="section-title">Mes tickets terminés</h2><div class="panel">` + done.sort((a, b) => b.c.day.localeCompare(a.c.day)).map((x) => {
      const g = x.c.status === "gagne" ? x.mise * (x.odds - 1) : -x.mise;
      return `<div class="hist"><span class="dot ${x.c.status}">${x.c.status === "gagne" ? "✓" : "✗"}</span>
        <div>${x.c.legs.map((l) => esc(l.label)).join(" + ")}<small>${esc(longDate(x.c.day))}, ${fmt(x.mise, 0)} € misés à ${fmt(x.odds)}${x.c.status === "gagne" ? `, ${fmt(x.mise * x.odds)} € récupérés` : ""}</small></div>
        <span class="o ${g >= 0 ? "pos" : "neg"}">${eur(g)}</span></div>`;
    }).join("") + `</div>`;
  }
  return h;
}

/* ---- qualité de tous les tickets proposés par le robot, par étoiles et folie */
function bilanRobot() {
  const all = (hist?.combos || []).filter((c) => !c.replaced && c.status !== "en attente");
  if (!all.length) return `<div class="panel" style="margin-top:14px"><p class="hint" style="margin:0">Aucun ticket terminé pour l'instant.</p></div>`;
  const groups = [["3 étoiles", (c) => c.kind !== "folie" && c.stars === 3, 2], ["2 étoiles", (c) => c.kind !== "folie" && c.stars === 2, 2],
    ["1 étoile", (c) => c.kind !== "folie" && (c.stars || 1) <= 1, 2], ["Folies du jour", (c) => c.kind === "folie", 1]];
  let h = `<p class="hint" style="margin:14px 4px">Tous les tickets proposés par le robot, joués ou non, pour juger si ses notes tiennent la route.</p>`;
  for (const [name, f, stake] of groups) {
    const g = all.filter(f);
    if (!g.length) continue;
    const w = g.filter((c) => c.status === "gagne").length;
    const bil = g.reduce((s, c) => s + (c.status === "gagne" ? stake * (c.odds - 1) : -stake), 0);
    h += `<details class="panel grp"><summary><div class="grp-head"><b>${esc(name)}</b><span>${w} gagné${w > 1 ? "s" : ""} sur ${g.length}</span>
        <span class="${bil >= 0 ? "pos" : "neg"}">${eur(bil)}</span></div>
        <p class="hint" style="margin:2px 0 0">à ${stake} € par ticket, cote moyenne ${fmt(g.reduce((s, c) => s + c.odds, 0) / g.length)}</p>
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
    h += liveStatusLine() + live.map(ticketHtml).join("");
  }
  if (done.length) h += `<div class="day"><h2>Derniers résultats</h2><span>sur 2 jours</span></div>` + done.map(ticketHtml).join("");
  el.innerHTML = h;
}

function renderAll() { renderHeader(); renderEncours(); renderCombos(); renderMatchs(); renderBilan(); renderComposer(); }

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
    LS.set("pf_bets", all); renderAll(); scheduleLive(); syncPlayed(); return;
  }
  const bv = e.target.closest("[data-bview]");
  if (bv) { bilanView = bv.dataset.bview; LS.set("pf_bilan_view", bilanView); renderBilan(); return; }
  const tab = e.target.closest(".tabs button");
  if (tab) {
    document.querySelectorAll(".tabs button").forEach((b) => b.classList.toggle("active", b === tab));
    document.querySelectorAll(".tab").forEach((s) => s.classList.toggle("active", s.id === "tab-" + tab.dataset.tab));
    window.scrollTo(0, 0);
    renderComposer();
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
  const data = { app: "combines-foot", version: 1, date: new Date().toISOString(), bets: bets(), overrides: overrides(), budget: s.budget };
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
  [today, hist, meta] = await Promise.all([get("today.json"), get("history.json"), get("meta.json")]);
  if (today) LS.set("pf_cache", { today, hist }); else if (!quiet) ({ today, hist } = LS.get("pf_cache", {}));
  renderAll();
}

loadSettings();
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
if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});
