/* Sauvegarde automatique : tes paris, chiffrés sur ce téléphone avec ton code de récupération, puis confiés au robot.
   Le robot ne fait que les ranger (docs/data/backup.json) : sans ton code, personne ne peut les lire. */
const BK_TOPIC = `${NTFY_TOPIC}-sauvegarde`;
const B32 = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
const BK_CHUNK = 3000;   // ntfy limite un message à 4 Ko : la sauvegarde part en morceaux
let BACKUPS = null;      // sauvegardes rangées par le robot (data/backup.json)

function backupCode() {
  let c = LS.get("pf_backup_code", "");
  if (!c) {
    const r = crypto.getRandomValues(new Uint8Array(16));
    c = [...r].map((x) => B32[x % 32]).join("").match(/.{4}/g).join("-");
    LS.set("pf_backup_code", c);
  }
  return c;
}
const normCode = (c) => String(c || "").toUpperCase().replace(/[^A-Z0-9]/g, "");
const toB64 = (u8) => { let s = ""; for (let i = 0; i < u8.length; i += 0x8000) s += String.fromCharCode(...u8.subarray(i, i + 0x8000)); return btoa(s); };
const fromB64 = (s) => Uint8Array.from(atob(s), (ch) => ch.charCodeAt(0));
async function gzip(u8, back = false) {
  const st = new Blob([u8]).stream().pipeThrough(back ? new DecompressionStream("gzip") : new CompressionStream("gzip"));
  return new Uint8Array(await new Response(st).arrayBuffer());
}
async function codeKey(code, salt) {
  const base = await crypto.subtle.importKey("raw", new TextEncoder().encode(normCode(code)), "PBKDF2", false, ["deriveKey"]);
  return crypto.subtle.deriveKey({ name: "PBKDF2", salt, iterations: 150000, hash: "SHA-256" }, base, { name: "AES-GCM", length: 256 }, false, ["encrypt", "decrypt"]);
}
async function sealBackup(obj, code) {
  const salt = crypto.getRandomValues(new Uint8Array(16)), iv = crypto.getRandomValues(new Uint8Array(12));
  const ct = new Uint8Array(await crypto.subtle.encrypt({ name: "AES-GCM", iv }, await codeKey(code, salt), await gzip(new TextEncoder().encode(JSON.stringify(obj)))));
  const out = new Uint8Array(28 + ct.length); out.set(salt); out.set(iv, 16); out.set(ct, 28);
  return "1." + toB64(out);
}
async function openBackup(blob, code) {
  const raw = fromB64(String(blob).replace(/^1\./, ""));
  const pt = await crypto.subtle.decrypt({ name: "AES-GCM", iv: raw.subarray(16, 28) }, await codeKey(code, raw.subarray(0, 16)), raw.subarray(28));
  return JSON.parse(new TextDecoder().decode(await gzip(new Uint8Array(pt), true)));
}

// ce qui est sauvegardé : les copies des tickets du robot ne sont pas nécessaires (le robot les garde déjà)
function backupData() {
  const known = new Set((hist?.combos || []).map((c) => c.id));
  const b = {};
  for (const [id, x] of Object.entries(bets())) b[id] = known.has(id) && x.snap && x.snap.kind !== "perso" && !x.snap.alt ? Object.assign({}, x, { snap: undefined }) : x;
  const ov = {};
  for (const [id, o] of Object.entries(overrides())) if (b[id]) ov[id] = o;
  return { app: "combines-foot", version: 2, bets: b, overrides: ov, budget: settings().budget, bank: bank(),
    style: LS.get("pf_style", null), pricew: LS.get("pf_pricew", null) };
}
function restoreData(d) {
  if (!d || d.app !== "combines-foot" || typeof d.bets !== "object") throw new Error("ce n'est pas une sauvegarde Combinés Foot");
  const merged = Object.assign({}, d.bets, bets());
  LS.set("pf_bets", merged);
  LS.set("pf_overrides", Object.assign({}, d.overrides || {}, overrides()));
  if (d.budget) LS.set("pf_settings", Object.assign(settings(), { budget: d.budget }));
  if (d.bank && !bank()) LS.set("pf_bank", d.bank);
  if (d.style !== null && d.style !== undefined && LS.get("pf_style", null) === null) LS.set("pf_style", d.style);
  if (d.pricew !== null && d.pricew !== undefined && LS.get("pf_pricew", null) === null) LS.set("pf_pricew", d.pricew);
  return Object.keys(merged).length;
}

async function sendBackup() {
  const data = backupData();
  if (!Object.keys(data.bets).length && !data.bank) return false;
  const plain = JSON.stringify(data);
  const hash = toB64(new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(plain + backupCode())))).slice(0, 16);
  const last = LS.get("pf_backup_sent", {});
  if (last.hash === hash) return false;
  const blob = await sealBackup(Object.assign(data, { date: new Date().toISOString() }), backupCode());
  const id = toB64(crypto.getRandomValues(new Uint8Array(6))).replace(/[+/=]/g, "x");
  const parts = blob.match(new RegExp(`.{1,${BK_CHUNK}}`, "g"));
  try {
    for (let i = 0; i < parts.length; i++) {
      const r = await fetch(`https://ntfy.sh/${BK_TOPIC}`, { method: "POST", body: JSON.stringify({ b: id, i, n: parts.length, d: parts[i] }) });
      if (!r.ok) return false;
    }
  } catch { return false; }
  LS.set("pf_backup_sent", { hash, id, t: Date.now(), size: blob.length });
  renderBackupStatus();
  return true;
}
let bkTimer = null;
function scheduleBackup() { clearTimeout(bkTimer); bkTimer = setTimeout(() => sendBackup().catch(() => {}), 4000); }

async function fetchBackups() {
  try { const r = await fetch(`data/backup.json?t=${Date.now()}`, { cache: "no-store" }); BACKUPS = r.ok ? await r.json() : { saves: [] }; }
  catch { BACKUPS = { saves: [] }; }
  return BACKUPS;
}
function renderBackupStatus() {
  const el = document.getElementById("bk-status"), code = document.getElementById("bk-code");
  if (code) code.textContent = backupCode();
  if (!el) return;
  const s = LS.get("pf_backup_sent", null);
  if (!s) { el.textContent = Object.keys(bets()).length ? "Première sauvegarde en cours d'envoi…" : "Elle démarrera avec ton premier pari."; return; }
  const ago = Math.round((Date.now() - s.t) / 60000);
  const saved = (BACKUPS?.saves || []).find((x) => x.id === s.id);
  el.textContent = `Dernier envoi ${ago < 1 ? "à l'instant" : ago < 60 ? `il y a ${ago} min` : `le ${new Date(s.t).toLocaleString("fr-FR", { day: "numeric", month: "long", hour: "2-digit", minute: "2-digit" })}`}. `
    + (saved ? "Rangée par le robot : tout est à l'abri." : "Le robot la range dans le quart d'heure.");
}
async function restoreFromCloud() {
  const code = prompt("Ton code de récupération (par exemple ABCD-EFGH-JKLM-NPQR) :", "");
  if (!code) return;
  if (normCode(code).length !== 16) { toast("Ce code n'a pas le bon format : 16 lettres et chiffres."); return; }
  const saves = ((await fetchBackups()).saves || []).slice().sort((a, b) => b.t - a.t);
  if (!saves.length) { toast("Aucune sauvegarde trouvée chez le robot pour l'instant."); return; }
  for (const s of saves) {
    try {
      const d = await openBackup(s.blob, code);
      const n = restoreData(d);
      LS.set("pf_backup_code", normCode(code).match(/.{4}/g).join("-"));
      LS.set("pf_backup_sent", {});
      loadSettings(); renderAll(); scheduleLive(); syncPlayed(); renderBackupStatus();
      toast(`Récupéré : ${n} paris (sauvegarde du ${new Date(d.date || s.t * 1000).toLocaleDateString("fr-FR", { day: "numeric", month: "long" })}).`, 6000);
      return;
    } catch { /* pas ce code ou pas cette sauvegarde : on essaie la suivante */ }
  }
  toast("Code incorrect : aucune sauvegarde ne s'ouvre avec ce code.", 5000);
}
document.addEventListener("click", (e) => {
  if (e.target.closest("#bk-copy")) {
    navigator.clipboard?.writeText(backupCode()).then(() => toast("Code copié. Garde-le en lieu sûr (notes, gestionnaire de mots de passe)."), () => toast(backupCode()));
  }
  if (e.target.closest("#bk-restore")) restoreFromCloud();
  if (e.target.closest("#bk-noted")) { LS.set("pf_backup_noted", true); renderAll(); }
});
