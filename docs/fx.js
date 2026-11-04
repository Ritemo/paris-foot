/* Animations et contenus interactifs : célébration des tickets gagnés, compteurs, buts en direct, simulation. */
const calm = () => window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/* ---------- compteurs animés : tout élément [data-count] glisse de son ancienne valeur à la nouvelle */
const lastCount = {};
function animateCounters(root = document) {
  root.querySelectorAll("[data-count]").forEach((el) => {
    const key = el.dataset.countKey || "", to = parseFloat(el.dataset.count), suffix = el.dataset.suffix || " €";
    const from = key in lastCount ? lastCount[key] : to;
    lastCount[key] = to;
    const sign = el.dataset.sign === "1";
    const show = (v) => { el.textContent = (sign && v > 0 ? "+" : "") + fmt(v) + suffix; };
    if (calm() || Math.abs(to - from) < 0.005) { show(to); return; }
    const t0 = performance.now(), dur = 900;
    const step = (t) => {
      const k = Math.min(1, (t - t0) / dur), e = 1 - Math.pow(1 - k, 3);
      show(from + (to - from) * e);
      if (k < 1) requestAnimationFrame(step);
    };
    show(from); requestAnimationFrame(step);
    el.classList.remove("bump"); void el.offsetWidth; if (to !== from) el.classList.add(to > from ? "bump" : "bump-down");
  });
}

/* ---------- célébration à l'ouverture : tes tickets gagnés depuis ta dernière visite */
function pendingCelebrations() {
  const seen = LS.get("pf_celebrated", null);
  const all = Object.entries(bets()).map(([id, b]) => ({ id, b, c: findCombo(id) })).filter((x) => x.c && x.c.status !== "en attente");
  if (seen === null) { LS.set("pf_celebrated", all.map((x) => x.id)); return { won: [], lost: [] }; }  // première fois : on ne fête pas l'historique
  const fresh = all.filter((x) => !seen.includes(x.id));
  return { won: fresh.filter((x) => x.c.status === "gagne"), lost: fresh.filter((x) => x.c.status === "perdu") };
}
function markCelebrated(list) {
  const seen = LS.get("pf_celebrated", []);
  LS.set("pf_celebrated", [...new Set([...seen, ...list.map((x) => x.id)])].slice(-300));
}

function celebrate() {
  if (window.__noCelebrate) return;   // tests automatiques
  const { won, lost } = pendingCelebrations();
  if (lost.length && !won.length) {
    markCelebrated(lost);
    toast(lost.length > 1 ? `${lost.length} tickets sont tombés depuis ta dernière visite.` : "Un ticket est tombé depuis ta dernière visite.", 4500);
    return;
  }
  if (!won.length) return;
  const total = won.reduce((s, x) => s + x.b.mise * x.b.odds, 0), net = won.reduce((s, x) => s + x.b.mise * (x.b.odds - 1), 0);
  const ov = document.createElement("div");
  ov.className = "celebrate";
  ov.setAttribute("role", "dialog");
  ov.setAttribute("aria-label", "Ticket gagné");
  ov.innerHTML = `<canvas class="confetti"></canvas>
    <div class="cel-card">
      <div class="cel-ball">${EMPTY_BALL}</div>
      <p class="cel-kicker">${won.length > 1 ? `${won.length} tickets gagnés` : "Ticket gagné"}</p>
      <div class="cel-amount" data-count="${total.toFixed(2)}" data-count-key="cel">0,00 €</div>
      <p class="cel-sub">récupérés, soit <b>${eur(net)}</b> de gain réel</p>
      <div class="cel-legs">${won.map((x) => `<div class="cel-ticket"><b>Cote ${fmt(x.b.odds)}</b>${x.c.legs.map((l) =>
        `<span>✓ ${esc(l.label)}${l.score ? ` <small>${esc(l.home)} ${esc(l.score)} ${esc(l.away)}</small>` : ""}</span>`).join("")}</div>`).join("")}</div>
      <button class="btn cel-ok">Super !</button>
      ${lost.length ? `<p class="cel-lost">et ${lost.length} ticket${lost.length > 1 ? "s" : ""} tombé${lost.length > 1 ? "s" : ""} depuis ta dernière visite</p>` : ""}
    </div>`;
  document.body.appendChild(ov);
  lastCount.cel = 0;
  setTimeout(() => animateCounters(ov), 350);
  if (!calm()) confetti(ov.querySelector(".confetti"));
  if (navigator.vibrate) try { navigator.vibrate([60, 40, 120]); } catch {}
  const close = () => { markCelebrated([...won, ...lost]); ov.classList.add("out"); setTimeout(() => ov.remove(), 300); };
  ov.querySelector(".cel-ok").onclick = close;
  ov.addEventListener("click", (e) => { if (e.target === ov) close(); });
}

function confetti(cv) {
  const ctx = cv.getContext("2d"), dpr = window.devicePixelRatio || 1;
  const W = (cv.width = innerWidth * dpr), H = (cv.height = innerHeight * dpr);
  const colors = ["#ffd23f", "#1faa59", "#ffffff", "#e63946", "#2f6fd6", "#9ff0bf"];
  const parts = Array.from({ length: 160 }, () => ({
    x: W / 2 + (Math.random() - 0.5) * W * 0.3, y: H * 0.35, vx: (Math.random() - 0.5) * 18 * dpr, vy: (-Math.random() * 16 - 6) * dpr,
    s: (4 + Math.random() * 6) * dpr, r: Math.random() * 6, vr: (Math.random() - 0.5) * 0.3, c: colors[(Math.random() * colors.length) | 0],
  }));
  const t0 = performance.now();
  const frame = (t) => {
    ctx.clearRect(0, 0, W, H);
    for (const p of parts) {
      p.vy += 0.45 * dpr; p.vx *= 0.99; p.x += p.vx; p.y += p.vy; p.r += p.vr;
      ctx.save(); ctx.translate(p.x, p.y); ctx.rotate(p.r); ctx.fillStyle = p.c; ctx.fillRect(-p.s / 2, -p.s / 4, p.s, p.s / 2); ctx.restore();
    }
    if (t - t0 < 3200 && cv.isConnected) requestAnimationFrame(frame); else ctx.clearRect(0, 0, W, H);
  };
  requestAnimationFrame(frame);
}

/* ---------- but en direct : la ligne du match clignote quand le score change */
const lastScores = {};
function flashGoals(root = document) {
  root.querySelectorAll(".live[data-mid]").forEach((el) => {
    const id = el.dataset.mid, sc = el.dataset.score;
    if (lastScores[id] !== undefined && lastScores[id] !== sc && !calm()) {
      el.classList.add("goal");
      const tag = document.createElement("i"); tag.className = "goal-tag"; tag.textContent = "BUT !"; el.appendChild(tag);
      setTimeout(() => { el.classList.remove("goal"); tag.remove(); }, 4000);
    }
    lastScores[id] = sc;
  });
}

/* ---------- simulation : « et si on jouait ce ticket 100 fois ? » */
function simulate(c) {
  const k = combo(c), n = 100, p = c.p;
  const results = Array.from({ length: n }, () => Math.random() < p);
  const wins = results.filter(Boolean).length, net = wins * 2 * (k.odds - 1) - (n - wins) * 2;
  const ov = document.createElement("div");
  ov.className = "celebrate sim";
  ov.innerHTML = `<div class="cel-card">
    <p class="cel-kicker">Ce ticket joué 100 fois à 2 €</p>
    <div class="sim-grid">${results.map((w, i) => `<i class="${w ? "w" : "l"}" style="animation-delay:${calm() ? 0 : i * 18}ms"></i>`).join("")}</div>
    <p class="sim-res"><b>${wins} gagnés</b> sur 100</p>
    <p class="cel-sub">Bilan de ces 100 paris : <b class="${net >= 0 ? "pos" : "neg"}">${eur(net)}</b><br>
      En moyenne, on en gagnerait ${Math.round(p * 100)} sur 100 : la chance de ce ticket. Rejoue pour voir comme le hasard varie.</p>
    <div class="row" style="justify-content:center"><button class="btn ghost sim-again">Rejouer</button><button class="btn cel-ok">Fermer</button></div>
  </div>`;
  document.body.appendChild(ov);
  const close = () => { ov.classList.add("out"); setTimeout(() => ov.remove(), 250); };
  ov.querySelector(".cel-ok").onclick = close;
  ov.querySelector(".sim-again").onclick = () => { ov.remove(); simulate(c); };
  ov.addEventListener("click", (e) => { if (e.target === ov) close(); });
}
document.addEventListener("click", (e) => {
  const s = e.target.closest("[data-sim]");
  if (!s) return;
  const c = s.dataset.sim === "__draft" ? draftCombo() : findCombo(s.dataset.sim);
  if (c) simulate(c);
});
