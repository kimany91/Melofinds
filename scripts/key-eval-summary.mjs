// Résumé du banc d'essai : lit les lignes « R {...} » et affiche le score de chaque méthode.
import fs from 'node:fs';
const NOTES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'];
function mirex(truth, est) {
  if (!est) return 'none';
  if (truth === est) return 'ok';
  const [tn, tm] = truth.split(' '); const [en, em] = est.split(' ');
  const ti = NOTES.indexOf(tn); const ei = NOTES.indexOf(en);
  if (tm === em && ((ei - ti + 12) % 12 === 7 || (ti - ei + 12) % 12 === 7)) return 'fifth';
  if (tm === 'min' && em === 'maj' && (ti + 3) % 12 === ei) return 'relative';
  if (tm === 'maj' && em === 'min' && (ti + 9) % 12 === ei) return 'relative';
  if (ti === ei) return 'parallel';
  return 'other';
}
const W = { ok: 1, fifth: 0.5, relative: 0.3, parallel: 0.2, other: 0, none: 0 };
const rows = fs.readFileSync(process.argv[2], 'utf8').split('\n').filter((l) => l.startsWith('R ')).map((l) => JSON.parse(l.slice(2)));
const methods = [...new Set(rows.flatMap((r) => Object.keys(r)))].filter((k) => !['id', 'truth', 'ch', 'bs', 'ms22', 'err22', 'op', 'errOp'].includes(k));
const ms = rows.map((r) => r.ms22).filter(Boolean);
if (ms.length) console.log(`temps Essentia (3 profils, 45 s à 22 kHz) : ${Math.round(ms.reduce((a, b) => a + b, 0) / ms.length)} ms en moyenne`);
const errs = rows.filter((r) => r.err22);
if (errs.length) console.log(`erreurs Essentia 22 kHz : ${errs.length} (ex. ${errs[0].err22})`);
console.log(`${rows.length} morceaux (${rows.filter((r) => r.truth.endsWith('min')).length} mineurs)`);
console.log('méthode     juste  MIREX  quinte relative parallèle autre');
for (const m of methods) {
  const c = { ok: 0, fifth: 0, relative: 0, parallel: 0, other: 0, none: 0 };
  for (const r of rows) c[mirex(r.truth, r[m])]++;
  const n = rows.length || 1;
  const score = rows.reduce((a, r) => a + W[mirex(r.truth, r[m])], 0) / n;
  console.log(`${m.padEnd(11)} ${(100 * c.ok / n).toFixed(1).padStart(5)}% ${score.toFixed(3)}  ${String(c.fifth).padStart(5)} ${String(c.relative).padStart(8)} ${String(c.parallel).padStart(9)} ${String(c.other + c.none).padStart(5)}`);
}
// votes larges sur les avis variés
const vote = (ks) => { const c = new Map(); for (const k of ks) if (k) c.set(k, (c.get(k) || 0) + 1); let b = null; let n = 0; for (const [k, v] of c) if (v > n) { b = k; n = v; } return b; };
const withOp = rows.filter((r) => r.op);
if (withOp.length) {
  const sets = {
    'vote 3 passages × 3 profils': (r) => Object.entries(r.op).filter(([k]) => /^s\d_/.test(k)).map(([, v]) => v),
    'vote 15 avis': (r) => Object.values(r.op),
    'vote 15 avis + 5 profils': (r) => [...Object.values(r.op), r.edmm, r.edma, r.bgate, r.braw, r.shaath],
    'vote h36 (3 profils)': (r) => ['edmm', 'edma', 'bgate'].map((p) => r.op[`h36_${p}`]),
    'vote f8k (3 profils)': (r) => ['edmm', 'edma', 'bgate'].map((p) => r.op[`f8k_${p}`]),
  };
  for (const [name, f] of Object.entries(sets)) {
    const ok = withOp.filter((r) => vote([r.edmm, ...f(r)]) === r.truth).length;
    console.log(`${name.padEnd(30)} ${(100 * ok / withOp.length).toFixed(1)}% (${withOp.length} morceaux)`);
  }
}
