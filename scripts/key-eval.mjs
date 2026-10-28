// Banc d'essai de la détection de clé sur de VRAIS morceaux annotés (GiantSteps+ Key :
// 600 extraits de musique électronique, clés vérifiées à la main ; CC BY-SA 4.0).
// Lancé sur GitHub (.github/workflows/key-eval.yml) : l'audio n'est pas dans le dépôt.
//   node scripts/key-eval.mjs <dossier audio> <dossier clés> [part] [nb parts]
// Compare : l'algorithme de Melofinds (src/core/audiokey.js) et Essentia (KeyExtractor,
// plusieurs profils). Même conditions que l'appli : 45 s au milieu du morceau.
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { analyzeAudio, chroma, resample } from '../src/core/audiokey.js';

const require = createRequire(import.meta.url);
const [audioDir, keyDir, partS = '0', partsS = '1'] = process.argv.slice(2);
const part = Number(partS); const parts = Number(partsS);
const NOTES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'];
const FLAT = { DB: 'C#', EB: 'D#', GB: 'F#', AB: 'G#', BB: 'A#', CB: 'B', FB: 'E', 'E#': 'F', 'B#': 'C' };
const MINORISH = /^(minor|min|m|aeolian|dorian|phrygian|locrian)$/i;
const MAJORISH = /^(major|maj|ionian|mixolydian|lydian)$/i;

function normKey(raw) {
  const m = String(raw || '').trim().match(/^([A-Ga-g])\s*([#b♯♭]?)\s*[:\s]?\s*([A-Za-z]*)/);
  if (!m) return null;
  let n = m[1].toUpperCase() + (m[2] === '♯' ? '#' : m[2] === '♭' ? 'b' : m[2] || '');
  n = FLAT[n.toUpperCase()] || n;
  const mode = m[3] || '';
  const md = MINORISH.test(mode) ? 'min' : MAJORISH.test(mode) || mode === '' ? 'maj' : null;
  if (!md || !NOTES.includes(n)) return null;
  return `${n} ${md}`;
}
// Score MIREX : juste 1, quinte 0,5, relative 0,3, parallèle 0,2
function mirex(truth, est) {
  if (!est) return { s: 0, kind: 'none' };
  if (truth === est) return { s: 1, kind: 'ok' };
  const [tn, tm] = truth.split(' '); const [en, em] = est.split(' ');
  const ti = NOTES.indexOf(tn); const ei = NOTES.indexOf(en);
  if (tm === em && ((ei - ti + 12) % 12 === 7 || (ti - ei + 12) % 12 === 7)) return { s: 0.5, kind: 'fifth' };
  if (tm === 'min' && em === 'maj' && (ti + 3) % 12 === ei) return { s: 0.3, kind: 'relative' };
  if (tm === 'maj' && em === 'min' && (ti + 9) % 12 === ei) return { s: 0.3, kind: 'relative' };
  if (ti === ei) return { s: 0.2, kind: 'parallel' };
  return { s: 0, kind: 'other' };
}
const essKey = (r) => (r?.key ? normKey(`${r.key} ${r.scale}`) : null);

function decode(file, rate) {
  const buf = execFileSync('ffmpeg', ['-v', 'error', '-i', file, '-ac', '1', '-ar', String(rate), '-f', 'f32le', '-'], { maxBuffer: 1 << 28 });
  return new Float32Array(buf.buffer, buf.byteOffset, buf.byteLength / 4);
}
function middle(x, rate, sec) {
  const len = Math.min(x.length, Math.round(sec * rate));
  const from = Math.max(0, Math.floor((x.length - len) / 2));
  return x.subarray(from, from + len);
}

const { Essentia, EssentiaWASM } = require('essentia.js');
const ess = new Essentia(EssentiaWASM);
const PROFILES = ['edma', 'edmm', 'bgate', 'braw', 'shaath'];
const VOTE = ['edmm', 'edma', 'bgate'];
// vote des 3 profils « musique électronique » ; égalité → edmm
function vote(keys) {
  const c = new Map();
  for (const k of keys) if (k) c.set(k, (c.get(k) || 0) + 1);
  let best = null; let n = 0;
  for (const [k, v] of c) if (v > n) { best = k; n = v; }
  return best;
}
// le vecteur vit dans la mémoire WASM : toujours le libérer (sinon plus de mémoire après
// quelques morceaux, et les analyses suivantes échouent)
function essRun(x, rate, prof) {
  const v = ess.arrayToVector(x);
  try { return essKey(ess.KeyExtractor(v, true, 4096, 4096, 12, 3500, 60, 25, 0.2, prof, rate, 0.0001, 440, 'cosine', 'hann')); } finally { v.delete?.(); }
}

const keyFiles = new Map();
for (const f of fs.readdirSync(keyDir, { recursive: true })) {
  const p = path.join(keyDir, String(f));
  if (fs.statSync(p).isFile()) keyFiles.set(path.basename(String(f)).replace(/\.[^.]+$/, '').replace(/\.LOFI$/i, ''), p);
}
const audio = fs.readdirSync(audioDir, { recursive: true }).map(String).filter((f) => /\.mp3$/i.test(f)).sort();
let shown = 0;
const mine = audio.filter((_, i) => i % parts === part);
for (const f of mine) {
  const id = path.basename(f).replace(/\.mp3$/i, '').replace(/\.LOFI$/i, '');
  const kf = keyFiles.get(id);
  if (!kf) continue;
  const raw = fs.readFileSync(kf, 'utf8').split('\n')[0];
  const truth = normKey(raw);
  if (shown < 5 && part === 0) { console.log(`exemple d'annotation : ${JSON.stringify(raw)} → ${truth}`); shown++; }
  if (!truth) continue;
  let full;
  try { full = decode(path.join(audioDir, f), 44100); } catch { continue; }
  const x44 = middle(full, 44100, 45);
  const half = (a) => { const o = new Float32Array(Math.floor(a.length / 2)); for (let i = 0; i < o.length; i++) o[i] = (a[2 * i] + a[2 * i + 1]) / 2; return o; };
  // l'appli : 45 s mono, 22 050 Hz (moyenne de 2 échantillons, comme le décodeur Android)
  const x22 = half(x44);
  const x22l = half(middle(full, 44100, 60));
  const res = { id, truth };
  try { res.ours = analyzeAudio(x22, 22050)?.key || null; } catch { res.ours = null; }
  const v = ess.arrayToVector(x44);
  for (const prof of PROFILES) {
    try { res[prof] = essKey(ess.KeyExtractor(v, true, 4096, 4096, 12, 3500, 60, 25, 0.2, prof, 44100, 0.0001, 440, 'cosine', 'hann')); } catch { res[prof] = null; }
  }
  res.vote44 = vote(VOTE.map((p) => res[p]));
  // conditions de l'appli : 22 kHz (45 s et 60 s), temps de calcul mesuré
  try {
    const t0 = Date.now();
    const k22 = VOTE.map((p) => essRun(x22, 22050, p));
    res.ms22 = Date.now() - t0;
    res.edmm22 = k22[0];
    res.vote22 = vote(k22);
    res.vote22l = vote(VOTE.map((p) => essRun(x22l, 22050, p)));
  } catch (e) { res.err22 = String(e?.message || e).slice(0, 80); }
  // traits pour régler l'algorithme hors ligne : chroma moyen et chroma des basses (Melofinds)
  try {
    const x = resample(x22, 22050, 11025);
    let pk = 0; for (const s of x) pk = Math.max(pk, Math.abs(s));
    if (pk > 0) for (let i = 0; i < x.length; i++) x[i] /= pk;
    res.ch = chroma(x, 11025).map((c) => +c.toFixed(2));
    res.bs = chroma(x, 11025, 4096, 1024, 260).map((c) => +c.toFixed(2));
  } catch { /* rien */ }
  v.delete?.();
  console.log(`R ${JSON.stringify(res)}`);
}
