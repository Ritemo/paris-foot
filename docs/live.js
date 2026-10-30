/* Suivi en direct des tickets joués : scores ESPN (gratuit, sans clé), actualisés chaque minute pendant les matchs. */
const ESPN_LEAGUE = { "Ligue 1": "fra.1", "Premier League": "eng.1", "Liga": "esp.1", "Serie A": "ita.1", "Bundesliga": "ger.1" };
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
    if (c && c.status === "en attente") for (const l of c.legs) if (l.won === undefined) out.push(l);
  }
  return out;
}
// faut-il suivre maintenant ? (un match commence dans moins de 15 min, ou a commencé il y a moins de 2h30)
function liveWindow(legs) {
  const now = Date.now();
  return legs.some((l) => { const k = new Date(l.kickoff).getTime(); return now > k - 15 * 6e4 && now < k + 150 * 6e4; });
}

async function refreshLive() {
  const legs = liveLegs();
  if (!legs.length) return;
  const wanted = new Set(legs.map((l) => `${ESPN_LEAGUE[l.league]}|${ymd(l.kickoff)}`).filter((k) => !k.startsWith("undefined")));
  try {
    const boards = await Promise.all([...wanted].map(async (k) => {
      const [lg, d] = k.split("|");
      const r = await fetch(`https://site.api.espn.com/apis/site/v2/sports/soccer/${lg}/scoreboard?dates=${d}`, { cache: "no-store" });
      if (!r.ok) throw new Error(r.status);
      return (await r.json()).events || [];
    }));
    const events = boards.flat();
    for (const l of legs) {
      const k = new Date(l.kickoff).getTime();
      let best = null, bestScore = -1;
      for (const e of events) {
        if (Math.abs(new Date(e.date).getTime() - k) > 20 * 6e4) continue;
        const comp = e.competitions?.[0]?.competitors || [];
        const H = comp.find((t) => t.homeAway === "home"), A = comp.find((t) => t.homeAway === "away");
        if (!H || !A) continue;
        const sc = teamScore(l.home, H.team.displayName) + teamScore(l.away, A.team.displayName);
        if (sc > bestScore) { best = { e, H, A }; bestScore = sc; }
      }
      if (best && bestScore > 0) {
        const st = best.e.status?.type || {};
        LIVE[l.match_id] = { h: +best.H.score || 0, a: +best.A.score || 0, state: st.state, clock: st.shortDetail || "" };
      }
    }
    liveUpdated = new Date(); liveError = false;
  } catch { liveError = true; }
  renderAll();
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
    note = ok ? (end ? "gagné" : "ça passe pour l'instant") : end ? "perdu" : `il faut ${gap} but${gap > 1 ? "s" : ""} de ${who}`;
  } else if (m[0] === "+" || m[0] === "-") {
    const line = parseFloat(m.slice(1)), need = Math.floor(line) + 1 - tot;
    if (m[0] === "+") {
      state = tot > line ? "ok" : end ? "ko" : "risk";
      note = tot > line ? "gagné" : end ? "perdu" : `encore ${need} but${need > 1 ? "s" : ""}`;
    } else {
      const margin = Math.floor(line) - tot;
      state = tot > line ? "ko" : end ? "ok" : margin === 0 ? "risk" : "on";
      note = tot > line ? "perdu" : end ? "gagné" : margin === 0 ? "plus un seul but" : `encore ${margin} but${margin > 1 ? "s" : ""} de marge`;
    }
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
  return `<div class="live ${x.state}"><b>${x.h} - ${x.a}</b><span>${esc(clock)}</span><em>${esc(x.note)}</em></div>`;
}
function liveTicketHtml(c) {
  const t = ticketLive(c);
  return t ? `<div class="verdict ${t.cls}">${esc(t.text)}</div>` : "";
}
function liveStatusLine() {
  if (liveError) return `<p class="hint live-status">Scores en direct indisponibles pour l'instant, nouvel essai dans une minute.</p>`;
  return liveUpdated ? `<p class="hint live-status">Scores en direct mis à jour à ${hour(liveUpdated.toISOString())}, actualisés chaque minute.</p>` : "";
}
