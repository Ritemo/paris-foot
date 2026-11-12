/* Suivi en direct des tickets joués : scores ESPN (gratuit, sans clé), actualisés chaque minute pendant les matchs. */
const ESPN_LEAGUE = { "Ligue 1": "fra.1", "Premier League": "eng.1", "Liga": "esp.1", "Serie A": "ita.1", "Bundesliga": "ger.1",
  "Ligue des champions": "uefa.champions", "Ligue Europa": "uefa.europa" };
// NBA et tennis : tableaux ESPN par sport
const ESPN_OTHER = { NBA: "basketball/nba", ATP: "tennis/atp", WTA: "tennis/wta" };
const sportOf = (l) => l.sport || (l.div === "NBA" ? "basket" : l.div === "ATP" || l.div === "WTA" ? "tennis" : "foot");
const UNIT = { foot: ["but", "buts"], basket: ["point", "points"], tennis: ["set", "sets"] };
const unit = (l, n) => UNIT[sportOf(l)][n > 1 ? 1 : 0];
const espnPath = (l) => ESPN_OTHER[l.div] || (ESPN_LEAGUE[l.league] ? `soccer/${ESPN_LEAGUE[l.league]}` : null);
let LIVE = {};            // match_id -> { h, a, state: "pre" | "in" | "post", clock }
let liveUpdated = null;   // date de la dernière mise à jour réussie
let liveError = false;
let liveTimer = null;

function normTeam(s) {
  return String(s).normalize("NFKD").replace(/[̀-ͯ]/g, "").toLowerCase()
    .replace(/[-'.]/g, " ").replace(/\b(fc|ac|as|afc|sc|rc|cf|ca|bc|tsg|vfb|vfl|fsv|ogc|ssc|us|ud|rcd|1|04|05|07|29)\b/g, " ")
    .split(/\s+/).filter((w) => w.length > 1);
}
function teamScore(a, b) {
  const x = normTeam(a), y = normTeam(b);
  let s = 0;
  for (const w of x) if (y.some((v) => v === w || (w.length >= 4 && v.length >= 4 && (v.startsWith(w.slice(0, 4)) || w.startsWith(v.slice(0, 4)))))) s++;
  return s;
}
const ymd = (iso) => new Date(iso).toISOString().slice(0, 10).replace(/-/g, "");

// les sélections des tickets joués encore en cours
function liveLegs() {
  const out = [];
  for (const id of Object.keys(bets())) {
    const c = findCombo(id);
    if (c) for (const l of c.legs) if (l.won === undefined) out.push({ ...l, played: true });   // même si le ticket est déjà perdu
  }
  return out;
}
// faut-il suivre maintenant ? (un match commence dans moins de 15 min, ou a commencé il y a moins de 2h30,
// ou un de tes combinés perso attend encore son résultat : l'appli le règle elle-même)
function liveWindow(legs) {
  const now = Date.now();
  return legs.some((l) => {
    const k = new Date(l.kickoff).getTime();
    const dur = { foot: 150, basket: 190, tennis: 300 }[sportOf(l)];
    return (now > k - 15 * 6e4 && now < k + dur * 6e4) || (l.played && now > k + 105 * 6e4 && now < k + 4 * 864e5);
  });
}

async function refreshLive() {
  const legs = liveLegs();
  if (!legs.length) return;
  const wanted = new Set();
  for (const l of legs) {
    const p = espnPath(l);
    if (!p) continue;
    wanted.add(`${p}|${ymd(l.kickoff)}`);
    if (sportOf(l) === "basket") wanted.add(`${p}|${ymd(new Date(new Date(l.kickoff).getTime() - 12 * 36e5).toISOString())}`);   // date américaine
  }
  try {
    const boards = await Promise.all([...wanted].map(async (k) => {
      const [p, d] = k.split("|");
      const r = await fetch(`https://site.api.espn.com/apis/site/v2/sports/${p}/scoreboard?dates=${d}`, { cache: "no-store" });
      if (!r.ok) throw new Error(r.status);
      // une « compétition » = un match : foot et NBA, la première de chaque événement ; tennis, tous les simples du tournoi
      return ((await r.json()).events || []).flatMap((e) => p.startsWith("tennis")
        ? (e.groupings || []).filter((g) => /Singles/.test(g.grouping?.displayName || "")).flatMap((g) => (g.competitions || []).map((c) => ({ c, path: p })))
        : (e.competitions || []).slice(0, 1).map((c) => ({ c, path: p, date: e.date, status: e.status })));
    }));
    const comps = boards.flat();
    const nameOf = (t) => t.athlete?.displayName || t.team?.displayName || t.displayName || "";
    for (const l of legs) {
      const k = new Date(l.kickoff).getTime(), p = espnPath(l), tennis = sportOf(l) === "tennis";
      let best = null, bestScore = 0;
      for (const x of comps) {
        if (x.path !== p || Math.abs(new Date(x.c.date || x.date).getTime() - k) > (tennis ? 8 * 36e5 : 20 * 6e4)) continue;
        const cs = x.c.competitors || [];
        let H = cs.find((t) => t.homeAway === "home"), A = cs.find((t) => t.homeAway === "away");
        if (tennis || !H || !A) {   // tennis : pas de domicile, on cherche chaque joueur
          [H, A] = teamScore(l.home, nameOf(cs[0] || {})) >= teamScore(l.home, nameOf(cs[1] || {})) ? [cs[0], cs[1]] : [cs[1], cs[0]];
        }
        if (!H || !A) continue;
        const sc = Math.min(teamScore(l.home, nameOf(H)), teamScore(l.away, nameOf(A))) > 0 ? teamScore(l.home, nameOf(H)) + teamScore(l.away, nameOf(A)) : 0;
        if (sc > bestScore) { best = { x, H, A }; bestScore = sc; }
      }
      if (best) {
        const st = best.x.c.status?.type || best.x.status?.type || {};
        const sets = (t) => (t.linescores || []).filter((s) => s.winner).length;
        let h = tennis ? sets(best.H) : +best.H.score || 0, a = tennis ? sets(best.A) : +best.A.score || 0;
        if (tennis && st.state === "post") { if (best.H.winner && h <= a) h = a + 1; if (best.A.winner && a <= h) a = h + 1; }
        const games = tennis ? (best.H.linescores || []).map((s, i) => `${s.value ?? 0}-${best.A.linescores?.[i]?.value ?? 0}`).join(" ") : "";
        LIVE[l.match_id] = { h, a, state: st.state, clock: tennis && games ? games : st.shortDetail || "" };
      }
    }
    liveUpdated = new Date(); liveError = false;
    settlePerso();
    liveAlerts();
  } catch { liveError = true; }
  renderAll();
}

// l'appli pose elle-même le résultat de tes tickets joués dès la fin des matchs, sans attendre le robot
// (indispensable pour tes combinés perso, que le robot ne règle pas dans son historique)
function settlePerso() {
  const all = bets();
  let changed = false;
  for (const [id, b] of Object.entries(all)) {
    const c = b.snap;
    if (!c || c.legs.every((l) => l.won !== undefined)) continue;
    // reprendre les résultats déjà posés par le robot
    const rc = (today?.combos || []).find((x) => x.id === id) || (hist?.combos || []).find((x) => x.id === id);
    for (const l of c.legs) {
      const r = rc && rc.legs.find((x) => x.match_id === l.match_id && x.market === l.market);
      if (l.won === undefined && r && r.won !== undefined) { l.won = r.won; l.score = r.score; changed = true; }
    }
    for (const l of c.legs) {
      const s = LIVE[l.match_id];
      if (l.won === undefined && s && s.state === "post") {
        const x = legLive(l);
        l.score = `${s.h}-${s.a}`; l.won = x.state === "ok"; changed = true;
      }
    }
    if (c.legs.some((l) => l.won === false)) c.status = "perdu";
    else if (c.legs.every((l) => l.won === true)) c.status = "gagne";
  }
  if (changed) LS.set("pf_bets", all);
}

// alertes sur le téléphone pendant les matchs (si tu les as autorisées)
function liveAlerts() {
  if (!("Notification" in window) || Notification.permission !== "granted" || !LS.get("pf_live_alerts", false)) return;
  const seen = LS.get("pf_alert_seen", {});
  const fire = (key, title, body) => {
    if (seen[key]) return;
    seen[key] = Date.now();
    navigator.serviceWorker?.ready.then((r) => r.showNotification(title, { body, icon: "icon-192.png", badge: "icon-192.png", tag: key }))
      .catch(() => { try { new Notification(title, { body }); } catch {} });
  };
  for (const id of Object.keys(bets())) {
    const c = findCombo(id);
    if (!c || c.status !== "en attente") continue;
    for (const l of c.legs) {
      const s = LIVE[l.match_id];
      if (!s || s.state === "pre") continue;
      const x = legLive(l);
      const sk = `s|${l.match_id}`, now = `${s.h}-${s.a}`;
      if (sportOf(l) === "foot" && seen[sk] && seen[sk] !== now) fire(`but|${l.match_id}|${now}`, `But ! ${l.home} ${now} ${l.away}`, `${l.label} : ${x.note} (${s.clock})`);
      seen[sk] = now;
    }
    const t = ticketLive(c);
    if (t && t.cls === "ko") fire(`ko|${id}`, "Ticket tombé", `Ton combiné à ${fmt(combo(c).odds)} est perdu.`);
    if (t && t.cls === "ok") fire(`ok|${id}`, "Ticket gagnant !", `Ton combiné à ${fmt(combo(c).odds)} est passé.`);
  }
  for (const k of Object.keys(seen)) {
    if (typeof seen[k] === "number" ? Date.now() - seen[k] > 3 * 864e5 : !LIVE[k.slice(2)]) delete seen[k];   // scores mémorisés des matchs plus suivis
  }
  LS.set("pf_alert_seen", seen);
}

function scheduleLive() {
  clearTimeout(liveTimer);
  const legs = liveLegs();
  if (!legs.length) return;
  const active = liveWindow(legs);
  if (active) refreshLive();
  liveTimer = setTimeout(scheduleLive, active ? 60e3 : 5 * 60e3);
}

// état d'une sélection selon le score : "ok" (gagnée pour de bon), "on" (en bonne voie), "risk" (pas encore), "ko" (perdue pour de bon)
function legLive(l) {
  const s = LIVE[l.match_id];
  if (!s || s.state === "pre") return null;
  const { h, a } = s, tot = h + a, end = s.state === "post", m = l.market;
  let state, note;
  if (m === "1" || m === "2" || m === "N") {
    const ok = m === "1" ? h > a : m === "2" ? a > h : h === a;
    state = end ? (ok ? "ok" : "ko") : ok ? "on" : "risk";
    const gap = m === "1" ? a - h + 1 : m === "2" ? h - a + 1 : Math.abs(h - a);
    const who = m === "1" ? l.home : m === "2" ? l.away : "l'équipe menée";
    note = ok ? (end ? "gagné" : "ça passe pour l'instant") : end ? "perdu" : `il faut ${gap} ${unit(l, gap)} de ${who}`;
  } else if (m.startsWith("HC1:") || m.startsWith("HC2:")) {   // handicap en points (NBA)
    const line = parseFloat(m.slice(4)), d = (m[2] === "1" ? h - a : a - h) + line;
    state = end ? (d > 0 ? "ok" : "ko") : d > 0 ? "on" : "risk";
    note = d > 0 ? (end ? "gagné" : `${Math.floor(d) + 1} points de marge`) : end ? "perdu" : `il manque ${Math.ceil(-d)} points`;
  } else if (m[0] === "+" || m[0] === "-") {
    const line = parseFloat(m.slice(1)), need = Math.floor(line) + 1 - tot;
    if (m[0] === "+") {
      state = tot > line ? "ok" : end ? "ko" : "risk";
      note = tot > line ? "gagné" : end ? "perdu" : `encore ${need} ${unit(l, need)}`;
    } else {
      const margin = Math.floor(line) - tot;
      state = tot > line ? "ko" : end ? "ok" : margin === 0 ? "risk" : "on";
      note = tot > line ? "perdu" : end ? "gagné" : margin === 0 ? `plus un seul ${unit(l, 1)}` : `encore ${margin} ${unit(l, margin)} de marge`;
    }
  } else if (m === "1N" || m === "N2" || m === "12") {
    const ok = m === "1N" ? h >= a : m === "N2" ? h <= a : h !== a;
    state = end ? (ok ? "ok" : "ko") : ok ? "on" : "risk";
    note = ok ? (end ? "gagné" : "ça passe pour l'instant") : end ? "perdu" : m === "12" ? "il faut un vainqueur" : `il faut 1 but de ${m === "1N" ? l.home : l.away}`;
  } else if (m === "BTTS" || m === "NBTTS") {
    const both = h > 0 && a > 0;
    if (m === "BTTS") { state = both ? "ok" : end ? "ko" : "risk"; note = both ? "gagné" : end ? "perdu" : `il manque un but de ${h === 0 ? l.home : l.away}${h === 0 && a === 0 ? " et de " + l.away : ""}`; }
    else { state = both ? "ko" : end ? "ok" : "on"; note = both ? "perdu" : end ? "gagné" : "ça tient tant qu'une équipe ne marque pas"; }
  } else if (m === "H1" || m === "H2") {
    const d = m === "H1" ? h - a : a - h;
    state = end ? (d >= 2 ? "ok" : "ko") : d >= 2 ? "on" : "risk";
    note = d >= 2 ? (end ? "gagné" : "écart suffisant pour l'instant") : end ? "perdu" : `il faut ${2 - d} but${2 - d > 1 ? "s" : ""} d'écart de plus`;
  }
  return { ...s, state, note, end };
}

// verdict d'un ticket entier
function ticketLive(c) {
  const ls = c.legs.map(legLive);
  if (!ls.some(Boolean)) return null;
  if (ls.some((x) => x && x.state === "ko")) return { cls: "ko", text: "Déjà perdu" };
  if (ls.every((x) => x && x.state === "ok")) return { cls: "ok", text: "Gagné, en attente de validation" };
  const good = ls.filter((x) => x && (x.state === "ok" || x.state === "on")).length;
  return { cls: "on", text: `Encore jouable : ${good} sur ${c.legs.length} en bonne voie` };
}

function liveLegHtml(l) {
  const x = legLive(l);
  if (!x) return "";
  const clock = x.end ? "terminé" : x.clock;
  // le flash « BUT ! » ne concerne que le foot (au basket, le score bouge sans arrêt)
  const goal = sportOf(l) === "foot" ? ` data-mid="${esc(l.match_id)}" data-score="${x.h}-${x.a}"` : "";
  return `<div class="live ${x.state}"${goal}><b>${x.h} - ${x.a}</b><span>${esc(clock)}</span><em>${esc(x.note)}</em></div>`;
}
function liveTicketHtml(c) {
  const t = ticketLive(c);
  return t ? `<div class="verdict ${t.cls}">${esc(t.text)}</div>` : "";
}
function liveStatusLine() {
  if (liveError) return `<p class="hint live-status">Scores en direct indisponibles pour l'instant, nouvel essai dans une minute.</p>`;
  return liveUpdated ? `<p class="hint live-status">Scores en direct mis à jour à ${hour(liveUpdated.toISOString())}, actualisés chaque minute.</p>` : "";
}
