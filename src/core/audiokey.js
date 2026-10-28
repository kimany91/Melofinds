// Analyse du son d'une prod : BPM et clé, calculés dans le navigateur (aucun service
// extérieur). Le son vient du micro (la prod qui joue sur le téléphone) ou d'un fichier.
//
//  - BPM : « force des attaques » (flux spectral : kick, snare, hi-hats), puis on cherche la
//    période qui revient le plus (autocorrélation + peigne sur 4 temps), entre 60 et 190 BPM.
//  - Clé : énergie des 12 notes (chroma, pics du spectre seulement, basses renforcées), puis
//    comparaison avec les profils des 24 gammes (Krumhansl-Kessler + Temperley).
// Une estimation, pas une certitude : la confiance est donnée avec le résultat.

const RATE = 11025; // assez pour les notes (jusqu'à ~2 kHz) et les attaques

/** Mono au taux voulu (moyenne par paquets : filtre anti-repliement simple). */
export function resample(x, from, to = RATE) {
  if (from === to) return Float32Array.from(x);
  const ratio = from / to;
  const n = Math.floor(x.length / ratio);
  const out = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    const a = Math.floor(i * ratio);
    const b = Math.max(a + 1, Math.floor((i + 1) * ratio));
    let s = 0;
    for (let j = a; j < b && j < x.length; j++) s += x[j];
    out[i] = s / (b - a);
  }
  return out;
}

// FFT radix 2 en place (re, im de longueur 2^k)
function fft(re, im) {
  const n = re.length;
  for (let i = 1, j = 0; i < n; i++) {
    let bit = n >> 1;
    for (; j & bit; bit >>= 1) j ^= bit;
    j ^= bit;
    if (i < j) { [re[i], re[j]] = [re[j], re[i]]; [im[i], im[j]] = [im[j], im[i]]; }
  }
  for (let len = 2; len <= n; len <<= 1) {
    const ang = (-2 * Math.PI) / len;
    const wr = Math.cos(ang);
    const wi = Math.sin(ang);
    for (let i = 0; i < n; i += len) {
      let cr = 1;
      let ci = 0;
      for (let j = 0; j < len / 2; j++) {
        const a = i + j;
        const b = a + len / 2;
        const tr = re[b] * cr - im[b] * ci;
        const ti = re[b] * ci + im[b] * cr;
        re[b] = re[a] - tr; im[b] = im[a] - ti;
        re[a] += tr; im[a] += ti;
        const nr = cr * wr - ci * wi;
        ci = cr * wi + ci * wr;
        cr = nr;
      }
    }
  }
}

/** Spectres d'amplitude (fenêtre de Hann) : tableau de Float32Array (size/2). */
function spectra(x, size, hop) {
  const win = new Float32Array(size);
  for (let i = 0; i < size; i++) win[i] = 0.5 - 0.5 * Math.cos((2 * Math.PI * i) / size);
  const out = [];
  const re = new Float32Array(size);
  const im = new Float32Array(size);
  for (let s = 0; s + size <= x.length; s += hop) {
    for (let i = 0; i < size; i++) { re[i] = x[s + i] * win[i]; im[i] = 0; }
    fft(re, im);
    const mag = new Float32Array(size / 2);
    for (let k = 0; k < size / 2; k++) mag[k] = Math.hypot(re[k], im[k]);
    out.push(mag);
  }
  return out;
}

// ---------------------------------------------------------------------------
// BPM

/** Courbe des attaques (flux spectral en log, rectifié), une valeur toutes les hop / rate s. */
export function onsetEnvelope(x, rate = RATE, size = 1024, hop = 128) {
  const sp = spectra(x, size, hop);
  const env = new Float32Array(sp.length);
  const lowK = Math.round(200 / (rate / size));
  let prev = null;
  for (let f = 0; f < sp.length; f++) {
    const cur = sp[f].map((v) => Math.log1p(100 * v));
    if (prev) {
      let s = 0;
      // sous ~200 Hz (kick, 808) : poids réduit ; leurs rythmes syncopés brouillent la grille,
      // que marquent mieux la snare et les hi-hats
      for (let k = 1; k < cur.length; k++) { const d = cur[k] - prev[k]; if (d > 0) s += k < lowK ? 0.25 * d : d; }
      env[f] = s;
    }
    prev = cur;
  }
  // on retire la tendance lente (moyenne glissante ~1 s) : restent les attaques
  const fps = rate / hop;
  const w = Math.max(1, Math.round(fps));
  const out = new Float32Array(env.length);
  let acc = 0;
  for (let i = 0; i < env.length; i++) {
    acc += env[i];
    if (i >= w) acc -= env[i - w];
    out[i] = Math.max(0, env[i] - acc / Math.min(i + 1, w));
  }
  return { env: out, fps };
}

/**
 * BPM d'une courbe d'attaques. Renvoie { bpm, confidence (0-1), alt } : alt = moitié ou
 * double plausible (les prods trap se jouent souvent « en demi-temps »).
 */
export function tempoFromEnvelope(env, fps, { min = 60, max = 190 } = {}) {
  const n = env.length;
  let mean = 0;
  for (const v of env) mean += v;
  mean /= n || 1;
  const x = Float32Array.from(env, (v) => v - mean);
  const maxLag = Math.min(n - 1, Math.ceil((fps * 60) / (min / 4)));
  const ac = new Float32Array(maxLag + 1);
  for (let lag = 0; lag <= maxLag; lag++) {
    let s = 0;
    for (let i = 0; i + lag < n; i++) s += x[i] * x[i + lag];
    ac[lag] = s / (n - lag);
  }
  const at = (l) => { // autocorrélation à un retard non entier
    const a = Math.floor(l);
    if (a + 1 > maxLag) return 0;
    const t = l - a;
    return ac[a] * (1 - t) + ac[a + 1] * t;
  };
  // peigne : le temps, 2, 3 et 4 temps plus loin, et ses subdivisions (croche, double
  // croche) — une grille de hi-hats rend aussi « régulier » un faux tempo (4/3, 4/7 du vrai),
  // mais ses subdivisions, elles, tombent à côté.
  const score = (bpm) => {
    const lag = (fps * 60) / bpm;
    return at(lag) + 0.5 * at(2 * lag) + 0.33 * at(3 * lag) + 0.25 * at(4 * lag) + 0.5 * at(lag / 2) + 0.25 * at(lag / 4);
  };
  const cands = [];
  for (let b = min; b <= max; b += 0.25) cands.push({ bpm: b, s: score(b) });
  cands.sort((p, q) => q.s - p.s);
  if (!cands.length || cands[0].s <= 0) return null;
  let best = cands[0];
  // affinage autour du meilleur (au centième)
  for (let b = best.bpm - 0.5; b <= best.bpm + 0.5; b += 0.02) { const s = score(b); if (s > best.s) best = { bpm: b, s }; }
  // moitié / double : même périodicité, on ne peut pas trancher sur le son seul (une trap à
  // 150 en demi-temps a les mêmes écarts qu'un son à 75). Convention des prods : 85-175 BPM
  // si cette valeur tient la route ; l'autre est donnée en « ou … ».
  const octave = [best.bpm / 2, best.bpm, best.bpm * 2].filter((b) => b >= min && b <= max).map((b) => ({ bpm: b, s: score(b) }));
  const top = Math.max(...octave.map((o) => o.s));
  const zone = octave.filter((o) => o.bpm >= 85 && o.bpm <= 175 && o.s >= 0.5 * top).sort((p, q) => q.s - p.s);
  const pick = zone[0] || octave.sort((p, q) => q.s - p.s)[0];
  const bpm = pick.bpm;
  const other = octave.filter((o) => o.bpm !== bpm && o.s >= 0.5 * top).sort((p, q) => q.s - p.s)[0];
  const alt = other ? other.bpm : null;
  const second = cands.find((c) => [bpm / 2, bpm, bpm * 2].every((o) => Math.abs(c.bpm - o) > 3));
  const confidence = Math.max(0, Math.min(1, second ? 1 - second.s / best.s : 1));
  return { bpm: Math.round(bpm), confidence: Math.round(confidence * 100) / 100, alt: alt ? Math.round(alt) : null };
}

// ---------------------------------------------------------------------------
// Clé

const NOTES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'];
const KK = { maj: [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88], min: [6.33, 2.68, 3.52, 5.38, 2.6, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17] };
const TP = { maj: [5, 2, 3.5, 2, 4.5, 4, 2, 4.5, 2, 3.5, 1.5, 4], min: [5, 2, 3.5, 4.5, 2, 4, 2, 4.5, 3.5, 2, 1.5, 4] };

function corr(a, b) {
  const n = a.length;
  const ma = a.reduce((s, v) => s + v, 0) / n;
  const mb = b.reduce((s, v) => s + v, 0) / n;
  let num = 0; let da = 0; let db = 0;
  for (let i = 0; i < n; i++) { num += (a[i] - ma) * (b[i] - mb); da += (a[i] - ma) ** 2; db += (b[i] - mb) ** 2; }
  return da && db ? num / Math.sqrt(da * db) : 0;
}

function median(arr) {
  const a = Array.from(arr).sort((p, q) => p - q);
  return a[a.length >> 1];
}

/** Énergie des 12 notes (do = 0). On garde la partie « tenue » du son (accords, 808,
 *  mélodie) et on écarte la batterie : séparation harmonique / percussive par médianes
 *  (dans le temps pour les notes, en fréquence pour les frappes). Pics seulement ; basses ×2. */
export function chroma(x, rate = RATE, size = 4096, hop = 1024, fMax = 2100) {
  const sp = spectra(x, size, hop);
  const out = new Float64Array(12);
  const binHz = rate / size;
  const kMin = Math.ceil(40 / binHz);
  const kMax = Math.min(size / 2 - 2, Math.floor(fMax / binHz));
  const T = sp.length;
  const peaks = [];
  const H = 4; // ±4 trames (~0,8 s)
  const F = 8; // ±8 cases en fréquence
  for (let f = 0; f < T; f++) {
    const mag = sp[f];
    const harm = new Float32Array(kMax + 2);
    let maxH = 0;
    for (let k = kMin - 1; k <= kMax + 1; k++) {
      const col = [];
      for (let g = Math.max(0, f - H); g <= Math.min(T - 1, f + H); g++) col.push(sp[g][k]);
      const h = median(col);
      const row = mag.subarray(Math.max(0, k - F), Math.min(mag.length, k + F + 1));
      const p = median(row);
      harm[k] = h >= p ? mag[k] * (h * h) / (h * h + p * p + 1e-12) : 0;
      if (harm[k] > maxH) maxH = harm[k];
    }
    if (maxH <= 0) continue;
    const list = [];
    for (let k = kMin; k <= kMax; k++) {
      const m = harm[k];
      if (m < 0.04 * maxH || !(m > harm[k - 1] && m >= harm[k + 1])) continue; // un pic net = une note
      const a = harm[k - 1]; const c = harm[k + 1];
      const d = (a - c) / (2 * (a - 2 * m + c) || 1);
      const fr = (k + d) * binHz;
      list.push({ midi: 69 + 12 * Math.log2(fr / 440), w: Math.sqrt(m) * (fr < 300 ? 2 : 1) });
    }
    if (list.length) peaks.push(list);
  }
  // accordage : une prod n'est pas toujours en La 440 (samples pitchés) → décalage moyen des
  // pics par rapport aux demi-tons (moyenne circulaire), puis notes recalées dessus
  let cs = 0; let sn = 0;
  for (const list of peaks) for (const p of list) { const a = 2 * Math.PI * (p.midi - Math.round(p.midi)); cs += p.w * Math.cos(a); sn += p.w * Math.sin(a); }
  const tuning = cs || sn ? Math.atan2(sn, cs) / (2 * Math.PI) : 0;
  for (const list of peaks) {
    const frame = new Float64Array(12);
    let tot = 0;
    for (const p of list) {
      const midi = p.midi - tuning;
      const near = Math.round(midi);
      const off = Math.abs(midi - near);
      if (off > 0.35) continue; // entre deux notes : bruit, pas une note
      const w = p.w * (1 - off);
      frame[((near % 12) + 12) % 12] += w;
      tot += w;
    }
    if (tot > 0) for (let i = 0; i < 12; i++) out[i] += frame[i] / tot;
  }
  return Array.from(out);
}

const MAJ_SET = [0, 2, 4, 5, 7, 9, 11];

/**
 * Clé d'un chroma : { key: « F# min », confidence (0-1), second }.
 * 1) la gamme (les 7 notes) : très fiable une fois la batterie écartée ;
 * 2) la tonique entre les deux gammes « jumelles » (majeure / relative mineure, mêmes notes) :
 *    profils de Krumhansl-Kessler et Temperley, avec une préférence pour le mineur (la grande
 *    majorité des prods rap / trap). `bass` : chroma des basses (808), qui tranche souvent.
 */
export function keyFromChroma(ch, bass = null) {
  if (!ch || ch.every((v) => !v)) return null;
  const tot = ch.reduce((a, b) => a + b, 0);
  // 1) gamme : part de l'énergie dans les 7 notes
  const sets = [];
  for (let t = 0; t < 12; t++) {
    const inSet = MAJ_SET.reduce((a, i) => a + ch[(t + i) % 12], 0);
    sets.push({ t, fit: inSet / tot });
  }
  sets.sort((a, b) => b.fit - a.fit);
  const best = sets[0];
  const majT = best.t;
  const minT = (majT + 9) % 12;
  // 2) tonique : corrélation avec les profils, pour la majeure et la relative mineure
  const prof = (t, mode) => {
    const rot = (p) => p.map((_, i) => p[(i - t + 12) % 12]);
    return (corr(ch, rot(KK[mode])) + corr(ch, rot(TP[mode]))) / 2;
  };
  let sMaj = prof(majT, 'maj');
  let sMin = prof(minT, 'min') + 0.06; // préférence mineur (rap / trap)
  if (bass && bass.some((v) => v > 0)) {
    const bt = bass.reduce((a, b) => a + b, 0);
    sMaj += 0.25 * (bass[majT] / bt);
    sMin += 0.25 * (bass[minT] / bt);
  }
  const major = sMaj > sMin;
  const key = `${NOTES[major ? majT : minT]} ${major ? 'maj' : 'min'}`;
  const relative = `${NOTES[major ? minT : majT]} ${major ? 'min' : 'maj'}`;
  // confiance : netteté de la gamme × écart entre les deux toniques
  const scaleSure = Math.max(0, Math.min(1, (best.fit - sets[1].fit) * 6 + (best.fit - 0.75) * 2));
  const tonicSure = Math.max(0, Math.min(1, Math.abs(sMaj - sMin) * 5));
  return { key, confidence: Math.round(scaleSure * (0.5 + 0.5 * tonicSure) * 100) / 100, second: relative, scaleFit: Math.round(best.fit * 100) / 100 };
}

/** Analyse complète : mono (Float32Array) au taux `rate` → { bpm, bpmConf, bpmAlt, key, keyConf, keyAlt, seconds }. */
export function analyzeAudio(mono, rate) {
  const x = resample(mono, rate, RATE);
  // niveau ramené à 1 (micro faible / fort)
  let peak = 0;
  for (const v of x) peak = Math.max(peak, Math.abs(v));
  if (peak < 1e-4) return null;
  for (let i = 0; i < x.length; i++) x[i] /= peak;
  const { env, fps } = onsetEnvelope(x, RATE);
  const t = tempoFromEnvelope(env, fps);
  const k = keyFromChroma(chroma(x, RATE), chroma(x, RATE, 4096, 1024, 260));
  return {
    bpm: t?.bpm || null, bpmConf: t?.confidence ?? 0, bpmAlt: t?.alt || null,
    key: k?.key || null, keyConf: k?.confidence ?? 0, keyAlt: k?.second || null,
    seconds: Math.round(x.length / RATE),
  };
}
