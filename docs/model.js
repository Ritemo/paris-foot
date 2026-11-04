/* Onglet Modèle : ce que le robot apprend des résultats (docs/data/model.json, écrit par robot/learn.py). */
const fr1 = (x, d = 1) => Number(x).toLocaleString("fr-FR", { minimumFractionDigits: d, maximumFractionDigits: d });

/* lecture d'un écart en nombre d'écarts-types : la marge du hasard */
function verdictChip(z) {
  const a = Math.abs(z || 0);
  if (a < 2) return `<span class="vchip hasard" title="${fr1(z, 2)} écart-type">● Dans la marge du hasard</span>`;
  if (a < 3) return `<span class="vchip surveiller" title="${fr1(z, 2)} écarts-types">▲ À surveiller</span>`;
  return `<span class="vchip net" title="${fr1(z, 2)} écarts-types">■ Écart net</span>`;
}

function mKpi(label, value, sub) {
  return `<div class="mkpi"><small>${label}</small><b>${value}</b><span>${sub}</span></div>`;
}

/* diagramme de calibration : annoncé (x) contre réel (y), la diagonale = parfait */
function calibChart(bins) {
  if (!bins?.length) return "";
  const W = 320, H = 240, L = 34, B = 30, T = 10, R = 10;
  const X = (v) => L + v * (W - L - R), Y = (v) => T + (1 - v) * (H - T - B);
  const ticks = [0, 0.25, 0.5, 0.75, 1];
  const grid = ticks.map((t) => `<line class="g" x1="${X(0)}" x2="${X(1)}" y1="${Y(t)}" y2="${Y(t)}"/>
    <text class="ax" x="${L - 6}" y="${Y(t) + 4}" text-anchor="end">${t * 100}</text>
    <text class="ax" x="${X(t)}" y="${H - B + 16}" text-anchor="middle">${t * 100}</text>`).join("");
  const maxN = Math.max(...bins.map((b) => b.n));
  const pts = bins.map((b) => {
    const r = 4 + 6 * Math.sqrt(b.n / maxN);
    const tip = `Annoncé ${pct(b.p)}, arrivé ${pct(b.f)} sur ${b.n} cas`;
    return `<g class="hit" data-tip="${esc(tip)}" tabindex="0"><circle class="halo" cx="${X(b.p)}" cy="${Y(b.f)}" r="${r + 10}"/>
      <circle class="dot" cx="${X(b.p)}" cy="${Y(b.f)}" r="${r}"><title>${esc(tip)}</title></circle></g>`;
  }).join("");
  return `<figure class="mchart">
    <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Calibration : probabilités annoncées contre fréquences observées">
      ${grid}<line class="diag" x1="${X(0)}" y1="${Y(0)}" x2="${X(1)}" y2="${Y(1)}"/>
      <text class="ax lbl" x="${X(0.03)}" y="${Y(0.95)}">parfait</text>${pts}
      <text class="ax" x="${(L + W - R) / 2}" y="${H - 2}" text-anchor="middle">annoncé par le robot (%)</text>
      <text class="ax" x="10" y="${T + (H - T - B) / 2}" text-anchor="middle" transform="rotate(-90 10 ${T + (H - T - B) / 2})">arrivé (%)</text>
    </svg><figcaption class="tip">Touche un point pour le détail.</figcaption></figure>`;
}

/* courbe simple (une série) ou deux séries avec légende et étiquettes directes */
function lineChart(series, { fmtY, label, yMin, yMax, xLabels }) {
  const W = 320, H = 170, L = 40, B = 24, T = 12, R = 70;
  const n = series[0].v.length;
  if (n < 2) return "";
  const all = series.flatMap((s) => s.v);
  const lo = yMin ?? Math.min(...all), hi = yMax ?? Math.max(...all), span = hi - lo || 1;
  const X = (i) => L + (i * (W - L - R)) / (n - 1), Y = (v) => T + ((hi - v) * (H - T - B)) / span;
  const ticks = [lo, lo + span / 2, hi];
  let h = ticks.map((t) => `<line class="g" x1="${L}" x2="${W - R}" y1="${Y(t)}" y2="${Y(t)}"/><text class="ax" x="${L - 6}" y="${Y(t) + 4}" text-anchor="end">${fmtY(t)}</text>`).join("");
  h += `<text class="ax" x="${L}" y="${H - 6}">${esc(xLabels[0])}</text><text class="ax" x="${W - R}" y="${H - 6}" text-anchor="end">${esc(xLabels[n - 1])}</text>`;
  const lastY = series.map((s) => Y(s.v[n - 1]));
  if (series.length === 2 && Math.abs(lastY[0] - lastY[1]) < 14) {   // étiquettes directes sans chevauchement
    const mid = (lastY[0] + lastY[1]) / 2, up = lastY[0] <= lastY[1] ? 0 : 1;
    lastY[up] = mid - 8; lastY[1 - up] = mid + 8;
  }
  series.forEach((s, k) => {
    h += `<polyline class="ln s${k}" points="${s.v.map((v, i) => `${X(i).toFixed(1)},${Y(v).toFixed(1)}`).join(" ")}"/>`;
    h += `<circle class="pt s${k}" cx="${X(n - 1)}" cy="${Y(s.v[n - 1])}" r="4"/>`;
    h += `<text class="dl" x="${X(n - 1) + 8}" y="${lastY[k] + 4}">${esc(s.name)}</text>`;
  });
  // zones de survol : une colonne par point, tooltip avec toutes les séries
  const colW = (W - L - R) / (n - 1);
  for (let i = 0; i < n; i++) {
    const tip = `${xLabels[i]} : ` + series.map((s) => `${s.name} ${fmtY(s.v[i])}`).join(", ");
    h += `<rect class="col" data-tip="${esc(tip)}" tabindex="0" x="${X(i) - colW / 2}" y="${T}" width="${colW}" height="${H - T - B}"><title>${esc(tip)}</title></rect>`;
  }
  const legend = series.length > 1 ? `<div class="mlegend">${series.map((s, k) => `<span><i class="s${k}"></i>${esc(s.name)}</span>`).join("")}</div>` : "";
  return `<figure class="mchart">${legend}<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(label)}">${h}</svg><figcaption class="tip">Touche le graphique pour le détail.</figcaption></figure>`;
}

/* barres autour de zéro : avance (au-dessus) ou retard (en dessous) du robot sur les bookmakers, mois par mois */
function gapBars(rows) {
  const W = 320, H = 150, L = 34, B = 22, T = 10, R = 6, n = rows.length;
  const vals = rows.map((r) => r.v), m = Math.max(0.5, ...vals.map(Math.abs));
  const Y = (v) => T + ((m - v) * (H - T - B)) / (2 * m), bw = Math.min(18, (W - L - R) / n - 4);
  const X = (i) => L + ((i + 0.5) * (W - L - R)) / n;
  let h = [m, 0, -m].map((t) => `<line class="g" x1="${L}" x2="${W - R}" y1="${Y(t)}" y2="${Y(t)}"/><text class="ax" x="${L - 6}" y="${Y(t) + 4}" text-anchor="end">${t > 0 ? "+" : ""}${fr1(t)}</text>`).join("");
  rows.forEach((r, i) => {
    const y0 = Y(0), y1 = Y(r.v), top = Math.min(y0, y1), hh = Math.max(Math.abs(y1 - y0), 1.5);
    const tip = `${r.label} : robot ${r.v >= 0 ? "en avance" : "en retard"} de ${fr1(Math.abs(r.v))} millième${Math.abs(r.v) >= 2 ? "s" : ""} sur ${r.n} matchs`;
    h += `<g class="hit" data-tip="${esc(tip)}" tabindex="0"><rect class="halo" x="${X(i) - (W - L - R) / n / 2}" y="${T}" width="${(W - L - R) / n}" height="${H - T - B}"/>
      <rect class="gbar ${r.v >= 0 ? "up" : "down"}" x="${X(i) - bw / 2}" y="${top}" width="${bw}" height="${hh}" rx="3"><title>${esc(tip)}</title></rect></g>`;
  });
  h += `<text class="ax" x="${X(0)}" y="${H - 6}" text-anchor="middle">${esc(rows[0].label)}</text><text class="ax" x="${X(n - 1)}" y="${H - 6}" text-anchor="middle">${esc(rows[n - 1].label)}</text>`;
  return `<figure class="mchart"><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Avance ou retard mensuel du robot sur les bookmakers">${h}</svg><figcaption class="tip">Touche une barre pour le détail.</figcaption></figure>`;
}

const monthLabel = (m) => new Date(m + "-15").toLocaleDateString("fr-FR", { month: "short", year: "2-digit" });

function renderModele() {
  const el = document.getElementById("tab-modele");
  if (!el) return;
  const m = model;
  if (!m) { el.innerHTML = `<div class="panel" style="margin-top:14px"><p class="hint" style="margin:0">Les mesures apparaîtront après le prochain passage du robot avec les cotes.</p></div>`; return; }
  const p = m.params, c = m.counts, s = m.scores || {};
  const nCorr = Object.values(p.offsets || {}).filter((x) => Math.abs(x) >= 0.005).length;
  const early = (c.last_year || 0) < m.min_verdict;
  const lessons = `<h2 class="section-title">Ce que le robot apprend</h2>
    <div class="panel lessons"><ul>${(m.lessons || []).map((x) => `<li>${esc(x)}</li>`).join("")}</ul>
    <p class="hint">Mis à jour ${when(m.updated)}. Le robot réapprend à chaque passage avec les cotes, sur tous les matchs terminés des cinq grands championnats et des coupes d'Europe, pas seulement sur tes tickets.</p></div>`;

  let h = `<h2 class="section-title">Les mesures</h2><div class="mkpis">
    ${mKpi("Matchs mesurés", fmt(c.last_year || 0, 0), `sur 12 mois${c.live ? `, dont ${c.live} en direct` : ""}`)}
    ${mKpi("Poids du modèle maison", Math.round(p.w_model * 100) + " %", `départ : ${Math.round(p.w_prior * 100)} %`)}
    ${mKpi("Corrections actives", nCorr + " sur 6", "types de pari")}
    ${mKpi("En attente de score", fmt(c.pending || 0, 0), "matchs suivis")}
  </div>`;

  if (s.robot) {
    const rows = [["Modèle maison seul", s.modele], ["Bookmakers", s.marche], ["Robot (annoncé)", s.robot]].filter((r) => r[1]);
    const worst = Math.max(...rows.map((r) => r[1].brier)), best = Math.min(...rows.map((r) => r[1].brier));
    const pad = (worst - best) * 0.6 || 0.01;
    h += `<h2 class="section-title">Qui voit le plus juste ?</h2><div class="panel">
      ${rows.map(([name, x]) => `<div class="brow ${name.startsWith("Robot") ? "me" : ""}"><span>${name}</span>
        <div class="bar"><i style="width:${Math.max(6, 100 * (1 - (worst + pad - x.brier) / (worst + pad - (best - pad))))}%"></i></div>
        <b>${fr1(x.brier, 3)}</b></div>`).join("")}
      <div class="verdict-line">Robot contre bookmakers : ${verdictChip(s.z_vs_marche)}</div>
      ${s.z_modele_vs_marche !== undefined ? `<div class="verdict-line">Modèle maison seul contre bookmakers : ${verdictChip(s.z_modele_vs_marche)}</div>` : ""}
      <p class="hint">Erreur moyenne sur le résultat 1N2 (score de Brier) : <b>plus la barre est courte, mieux c'est</b>. 0,667 correspond à un tirage au hasard entre 1, N et 2. Le favori annoncé par le robot a gagné ${pct(s.robot.acc)} des matchs. Battre les bookmakers de peu ne suffit pas à couvrir leur marge.</p>
    </div>`;
  }

  if (m.calibration?.length) {
    h += `<h2 class="section-title">Ses pourcentages sont-ils honnêtes ?</h2><div class="panel">
      ${calibChart(m.calibration)}
      <p class="hint">Chaque point regroupe les annonces d'une même tranche (victoire, nul, plus de 2,5 buts). Sur la diagonale, le robot dit vrai : quand il annonce 40 %, ça arrive 4 fois sur 10. Plus le point est gros, plus il y a de cas.</p></div>`;
  }

  if (m.families?.length) {
    h += `<h2 class="section-title">Par type de pari</h2><div class="panel">` + m.families.map((f) => {
      const corr = Math.abs(f.offset) >= 0.005 ? `<span class="corr">Corrigé ${f.offset < 0 ? "à la baisse" : "à la hausse"}</span>` : `<span class="corr off">Pas de correction</span>`;
      return `<div class="mstat"><div class="mstat-head"><b>${esc(f.name)}</b>${verdictChip(f.z)}</div>${compare(f.annonce, f.reel)}${corr}</div>`;
    }).join("") + `<p class="hint">Annoncée = moyenne des probabilités du robot, réelle = ce qui s'est passé, sur ${fmt(c.last_year || 0, 0)} matchs. Le robot ne corrige un type de pari que si l'écart sort nettement de la marge du hasard (plus de 2 écarts-types), et toujours avec prudence : de quoi éviter de courir après une mauvaise série.</p></div>`;
  }

  const t = m.tickets || {};
  if (t.tickets || t.selections) {
    const block = (name, x) => x ? `<div class="mstat"><div class="mstat-head"><b>${name}</b>${verdictChip(x.z)}</div>
      <p class="trap"><b>${x.observes}</b> gagnés sur ${x.n}, pour <b>${fr1(x.attendus)}</b> attendus.
      ${x.marge ? `Tant que l'écart reste sous <b>${fr1(x.marge)}</b>, c'est la chance du moment, pas un défaut du robot.` : ""}</p>${compare(x.annonce, x.reel)}</div>` : "";
    h += `<h2 class="section-title">Le piège des petites séries</h2><div class="panel">
      ${block("Tickets proposés", t.tickets)}${block("Sélections de ces tickets", t.selections)}
      <p class="hint">Sur quelques dizaines de tickets, 3 ou 4 gagnés de plus ou de moins arrivent tout le temps. C'est pour cela que le robot apprend sur les centaines de matchs du journal, et que ton flair reste le bienvenu pour écarter ce qu'il ne voit pas : blessures, enjeu, météo, rotation.</p></div>`;
  }

  const months = (m.months || []).slice(-12);
  const log = m.log || [];
  if (months.length >= 2 || log.length >= 2) {
    h += `<h2 class="section-title">Évolution</h2><div class="panel">`;
    if (months.length >= 2) h += `<h3>Avance du robot sur les bookmakers, par mois</h3>` +
      gapBars(months.map((x) => ({ v: (x.marche - x.robot) * 1000, n: x.n, label: monthLabel(x.m) })))
      + `<p class="hint">En millièmes d'erreur moyenne : au-dessus de zéro, le robot a vu plus juste que les cotes ce mois-là ; en dessous, moins juste. Des barres qui changent de côté d'un mois à l'autre, c'est le signe qu'aucun des deux ne domine.</p>`;
    if (log.length >= 2) h += `<h3 style="margin-top:14px">Poids du modèle maison</h3>` + lineChart(
      [{ name: "Poids", v: log.map((x) => x.w * 100) }],
      { fmtY: (v) => Math.round(v) + " %", label: "Poids du modèle maison dans le mélange au fil du temps", yMin: 0, yMax: 60,
        xLabels: log.map((x) => new Date(x.d + "T12:00:00").toLocaleDateString("fr-FR", { day: "numeric", month: "short", year: "2-digit" })) })
      + `<p class="hint">Part du modèle maison dans les probabilités, le reste venant des cotes. Il gagne du poids s'il améliore les prévisions, il en perd sinon.</p>`;
    h += `</div>`;
  }

  if (m.leagues?.length) {
    h += `<h2 class="section-title">Par championnat</h2><div class="panel"><table class="months"><thead><tr><th>Championnat</th><th>Robot</th><th>Bookm.</th></tr></thead><tbody>` +
      m.leagues.map((x) => `<tr><td>${esc(x.name)}<small>${x.n} matchs</small></td><td class="${x.robot < x.marche - 0.0005 ? "pos" : ""}">${fr1(x.robot, 3)}</td><td>${fr1(x.marche, 3)}</td></tr>`).join("") +
      `</tbody></table><p class="hint">Erreur moyenne, plus bas = mieux.</p></div>`;
  }

  h += lessons;
  h += `<div class="panel legend"><h3>Comment il apprend</h3><dl>
    <dt>Sur quoi</dt><dd>Tous les matchs des championnats suivis${c.since ? `, depuis le ${new Date(c.since + "T12:00:00").toLocaleDateString("fr-FR", { day: "numeric", month: "long", year: "numeric" })}` : ""}. ${c.backtest ? `${fmt(c.backtest, 0)} matchs viennent d'un rejeu du passé avec les cotes moyennes des bookmakers, ` : ""}les suivants des vraies cotes du jour.</dd>
    <dt>Le mélange</dt><dd>Le poids du modèle maison est réajusté pour coller au mieux aux résultats, mais ramené vers ${Math.round(p.w_prior * 100)} % tant que les données sont peu nombreuses, et plafonné à 60 %.</dd>
    <dt>Les corrections</dt><dd>Seulement si un type de pari est mal estimé au-delà de la marge du hasard, et plafonnées. Les matchs récents comptent plus que les anciens.</dd>
    <dt>Ce qu'il ne fait pas</dt><dd>Il ne tient pas compte de tes gains ou de tes pertes : trop peu de tickets pour en tirer une leçon fiable.</dd></dl>
    ${early ? `<p class="hint">Encore trop peu de matchs pour conclure.</p>` : ""}</div>`;
  el.innerHTML = h;
}

/* tooltip au toucher ou au survol, pour tous les graphiques de l'onglet */
document.addEventListener("click", (e) => {
  const t = e.target.closest(".mchart [data-tip]");
  if (!t) return;
  const fig = t.closest(".mchart");
  fig.querySelectorAll(".on").forEach((x) => x.classList.remove("on"));
  t.classList.add("on");
  fig.querySelector(".tip").textContent = t.dataset.tip;
});
document.addEventListener("mouseover", (e) => {
  const t = e.target.closest?.(".mchart [data-tip]");
  if (t) t.closest(".mchart").querySelector(".tip").textContent = t.dataset.tip;
});
