/* Composer son propre combiné depuis l'onglet Matchs. */
const NTFY_TOPIC = "combines-foot-ritemo-7k3q9x";
const draft = () => LS.get("pf_draft", {});   // match_id -> market

function matchById(id) { return (today?.matches || []).find((m) => m.id === id); }

function draftLegs() {
  const out = [];
  for (const [mid, mk] of Object.entries(draft())) {
    const m = matchById(mid);
    const s = m && m.sel.find((x) => x.market === mk);
    if (!m || !s || new Date(m.kickoff) <= new Date()) continue;   // match commencé : sélection retirée
    out.push({ match_id: m.id, league: m.league, kickoff: m.kickoff, home: m.home, away: m.away, fd_home: m.fd_home, fd_away: m.fd_away,
      div: m.div, market: s.market, label: s.market.startsWith("H") ? `${s.market === "H1" ? m.home : m.away} gagne par 2 buts ou +` : s.label,
      odds: s.odds, src: s.src, p: s.p, ev: s.ev });
  }
  return out.sort((a, b) => a.kickoff.localeCompare(b.kickoff));
}

function draftCombo() {
  const legs = draftLegs();
  if (!legs.length) return null;
  const p = legs.reduce((x, l) => x * l.p, 1), odds = legs.reduce((x, l) => x * l.odds, 1);
  const ev = legs.reduce((x, l) => x * (1 + l.ev), 1) - 1;
  const day = isoDay(new Date(legs[0].kickoff));
  return { id: `perso|${day}|${legs.map((l) => l.match_id + ":" + l.market).join("|")}`, day, kind: "perso", legs,
    odds: +odds.toFixed(2), p, cost: -ev, stars: 0, stake: p < 0.25 ? 1 : p < 0.35 ? 2 : 3, status: "en attente" };
}

function pickBtn(m, s, text) {
  const on = draft()[m.id] === s.market;
  return `<button class="pick-btn ${on ? "on" : ""}" data-pick="${esc(m.id)}" data-market="${esc(s.market)}" aria-pressed="${on}">
    <span>${esc(text)}</span><b>${fmt(s.odds)}${s.src === "estimee" ? "*" : ""}</b></button>`;
}

function renderComposer() {
  let bar = document.getElementById("composer");
  const c = draftCombo();
  const onMatchs = document.getElementById("tab-matchs").classList.contains("active");
  if (!c || !onMatchs) { if (bar) bar.remove(); return; }
  if (!bar) { bar = document.createElement("div"); bar.id = "composer"; document.body.appendChild(bar); }
  const k = combo(c);
  bar.innerHTML = `<div class="comp-head"><b>Mon combiné</b><span>${c.legs.length} sélection${c.legs.length > 1 ? "s" : ""}</span>
      <button class="comp-clear" data-compose="clear">Vider</button></div>
    <div class="comp-stats"><div><b>${fmt(k.odds)}</b><small>cote</small></div><div><b>${c.p < 0.1 ? fmt(c.p * 100, 1) + " %" : pct(c.p)}</b><small>de chance</small></div>
      <div class="${k.cost <= 0.12 ? "cost-low" : k.cost > 0.18 ? "cost-high" : ""}"><b>${Math.round(k.cost * 100)} %</b><small>de coût</small></div>
      <button class="btn" data-compose="play">Je le joue</button></div>`;
}

document.addEventListener("click", async (e) => {
  const pb = e.target.closest("[data-pick]");
  if (pb) {
    const d = draft(), mid = pb.dataset.pick, mk = pb.dataset.market;
    if (d[mid] === mk) delete d[mid];
    else {
      if (!d[mid] && Object.keys(d).length >= 8) { toast("8 sélections au maximum."); return; }
      d[mid] = mk;
    }
    LS.set("pf_draft", d); renderMatchs(); renderComposer(); return;
  }
  const cb = e.target.closest("[data-compose]");
  if (!cb) return;
  if (cb.dataset.compose === "clear") { LS.set("pf_draft", {}); renderMatchs(); renderComposer(); return; }
  const c = draftCombo();
  if (!c) return;
  if (bets()[c.id]) { toast("Tu as déjà joué exactement ce combiné."); return; }
  const left = settings().budget - monthSpent();
  const v = await ask("Combien tu mises ?", `Ton combiné à ${fmt(combo(c).odds)}, ${pct(c.p)} de chance. Il te reste ${fmt(Math.max(left, 0), 0)} € dans ton budget du mois.`, c.stake, { steps: [1, 2, 3, 4, 5] });
  if (!v || isNaN(v) || v <= 0) return;
  if (v > left && !confirm("Cette mise dépasse ton budget du mois. La garder quand même ?")) return;
  const all = bets();
  all[c.id] = { mise: Math.min(v, 5), odds: +combo(c).odds.toFixed(2), date: isoDay(new Date()), snap: c };
  LS.set("pf_bets", all); LS.set("pf_draft", {});
  freshStamp = c.id;
  renderAll(); scheduleLive();
  document.querySelector('.tabs button[data-tab="encours"]').click();
  toast("Combiné ajouté à tes tickets en cours.");
});

/* --------------------------------------------------------------- notifications */
async function ntfyTest() {
  try {
    const r = await fetch(`https://ntfy.sh/${NTFY_TOPIC}`, { method: "POST", body: "Les notifications Combinés Foot fonctionnent.",
      headers: { Title: "Test Combinés Foot", Tags: "soccer" } });
    toast(r.ok ? "Notification envoyée : elle doit arriver dans quelques secondes." : "Envoi impossible (" + r.status + ").");
  } catch (err) { toast("Envoi impossible : " + err.message); }
}
async function toggleLiveAlerts(on) {
  if (on) {
    if (!("Notification" in window)) { toast("Ton navigateur ne gère pas les notifications."); return false; }
    const p = await Notification.requestPermission();
    if (p !== "granted") { toast("Notifications refusées : autorise-les dans les réglages du téléphone pour Combinés Foot."); return false; }
  }
  LS.set("pf_live_alerts", on);
  return on;
}
