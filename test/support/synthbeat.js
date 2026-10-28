// Faux beats pour tester l'analyse BPM / clé : 808 sur la tonique, kick, snare, hi-hats,
// accords et mélodie dans la gamme. phone: true imite le haut-parleur d'un téléphone capté
// au micro (presque plus de basses, bruit de fond, niveau faible).

const NOTES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'];
const MAJ = [0, 2, 4, 5, 7, 9, 11];
const MIN = [0, 2, 3, 5, 7, 8, 10];

function rng(seed) { let s = seed >>> 0; return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 2 ** 32); }
let tune = 0;
const hz = (midi) => 440 * 2 ** ((midi + tune - 69) / 12);

export function synthBeat({ bpm, key, seconds = 20, rate = 22050, phone = false, halfTime = true, seed = 1, hats = 16, detune = 0, noise = 0.01 }) {
  tune = detune;
  const [tonic, mode] = key.split(' ');
  const t0 = NOTES.indexOf(tonic);
  const scale = mode === 'maj' ? MAJ : MIN;
  const n = Math.floor(seconds * rate);
  const x = new Float32Array(n);
  const r = rng(seed);
  const beat = 60 / bpm;
  const add = (start, len, fn) => {
    const a = Math.floor(start * rate);
    const b = Math.min(n, a + Math.floor(len * rate));
    for (let i = Math.max(0, a); i < b; i++) x[i] += fn((i - a) / rate);
  };
  // grilles courantes en rap / trap (degrés 0 = tonique) ; la mélodie revient sur la tonique
  const PROGS = mode === 'maj'
    ? [[0, 4, 5, 3], [0, 3, 0, 4], [0, 5, 3, 4], [0, 0, 3, 4]]
    : [[0, 5, 2, 6], [0, 3, 4, 0], [0, 5, 3, 4], [0, 0, 5, 6], [0, 6, 5, 6], [0, 3, 0, 5]];
  const prog = PROGS[Math.floor(r() * PROGS.length)];
  const bars = Math.ceil(seconds / (beat * 4));
  for (let bar = 0; bar < bars; bar++) {
    const b0 = bar * 4 * beat;
    const deg = prog[bar % 4];
    // accord (3 notes, timbre avec quelques harmoniques), octave 4
    for (const d of [0, 2, 4]) {
      const s = deg + d;
      const midi = 60 + t0 + scale[s % 7] + 12 * Math.floor(s / 7);
      const f = hz(midi);
      add(b0, 4 * beat, (t) => 0.08 * Math.exp(-t * 0.4) * (Math.sin(2 * Math.PI * f * t) + 0.5 * Math.sin(4 * Math.PI * f * t) + 0.25 * Math.sin(6 * Math.PI * f * t)));
    }
    // 808 sur la fondamentale de l'accord (octave 1-2), long
    const root = 36 + t0 + scale[deg % 7];
    const fr = hz(root);
    add(b0, 2.5 * beat, (t) => 0.5 * Math.exp(-t * 0.9) * (Math.sin(2 * Math.PI * fr * t) + 0.3 * Math.sin(4 * Math.PI * fr * t)));
    // mélodie : croches dans la gamme, octave 5
    for (let e = 0; e < 8; e++) {
      if (r() < 0.35) continue;
      const s = e === 0 || e === 7 || r() < 0.3 ? [0, 0, 2, 4][Math.floor(r() * 4)] : Math.floor(r() * 7);
      const f = hz(72 + t0 + scale[s]);
      add(b0 + e * beat / 2, beat / 2, (t) => 0.12 * Math.exp(-t * 6) * (Math.sin(2 * Math.PI * f * t) + 0.3 * Math.sin(4 * Math.PI * f * t)));
    }
    // batterie
    const kicks = halfTime ? [0, 1.5, 2.75] : [0, 1, 2, 3];
    const snares = halfTime ? [2] : [1, 3];
    for (const k of kicks) add(b0 + k * beat, 0.25, (t) => 0.9 * Math.exp(-t * 18) * Math.sin(2 * Math.PI * (50 + 100 * Math.exp(-t * 30)) * t));
    for (const sn of snares) add(b0 + sn * beat, 0.2, () => 0);
    for (const sn of snares) {
      const a = Math.floor((b0 + sn * beat) * rate);
      for (let i = 0; i < 0.18 * rate && a + i < n; i++) x[a + i] += 0.5 * Math.exp(-i / rate * 22) * (r() * 2 - 1);
    }
    for (let hh = 0; hh < hats; hh++) {
      const a = Math.floor((b0 + hh * 4 * beat / hats) * rate);
      let prev = 0;
      for (let i = 0; i < 0.04 * rate && a + i < n; i++) { const w = r() * 2 - 1; x[a + i] += 0.25 * Math.exp(-i / rate * 90) * (w - prev); prev = w; }
    }
  }
  if (phone) {
    // haut-parleur : coupe sous ~350 Hz ; micro : bruit de fond, niveau faible
    const a = Math.exp(-2 * Math.PI * 350 / rate);
    let yPrev = 0; let xPrev = 0;
    for (let i = 0; i < n; i++) { const y = a * (yPrev + x[i] - xPrev); xPrev = x[i]; yPrev = y; x[i] = 0.2 * y + noise * (r() * 2 - 1); }
  }
  return x;
}
