// Reconnaît les rappeurs cités dans une description, même mal écrits :
// « une prod à la luther », « la feve », « jok air », « bu$hi », « coeur co »,
// « travis scot », « pop smok »…

import { normalize } from './text.js';
import { GENRES, MOODS, INSTRUMENTS } from './genres.js';
import { FR_ARTISTS } from './frartists.js';

/** Clé de comparaison : minuscules, sans accents, sans espaces ni ponctuation ($ → s). */
export const artistKey = (s) => normalize(s).replace(/\$/g, 's').replace(/[^a-z0-9]/g, '');

// Mots courants qui ne doivent jamais être pris pour un artiste
const COMMON = ['type', 'beat', 'beats', 'prod', 'prods', 'instru', 'instrumental', 'free', 'profit', 'style', 'comme', 'genre',
  'avec', 'sans', 'une', 'des', 'les', 'pour', 'dans', 'plus', 'tres', 'son', 'sons', 'rap', 'trap', 'musique', 'music', 'vibe',
  'facon', 'mode', 'ambiance', 'truc', 'quelque', 'chose', 'veux', 'cherche', 'voudrais', 'faut', 'bien', 'mais', 'aussi',
  'love', 'hard', 'dark', 'sad', 'fast', 'slow', 'piano', 'guitar', 'guitare', 'drill', 'rage', 'plugg', 'jerk', 'cloud'];
const STOP = new Set([
  ...COMMON,
  ...Object.values(MOODS).flatMap((m) => m.words.map(artistKey)),
  ...Object.values(INSTRUMENTS).flat().map(artistKey),
  ...GENRES.flatMap((g) => g.aliases.map(artistKey)),
]);

// Index : clé → artiste
const ENTRIES = [];
const BY_KEY = new Map();
function addEntry(name, type, aliases, extra) {
  const keys = [...new Set([name, ...aliases].map(artistKey))].filter((k) => k && !STOP.has(k));
  const e = { name, type, keys, ...extra };
  ENTRIES.push(e);
  for (const k of keys) if (!BY_KEY.has(k)) BY_KEY.set(k, e);
}
for (const a of FR_ARTISTS) addEntry(a.name, 'fr', a.aliases, { fr: a });
const seenUs = new Set();
for (const g of GENRES) {
  for (const name of g.artists) {
    if (seenUs.has(name)) continue;
    seenUs.add(name);
    addEntry(name, 'us', g.aliasesArtists?.[name] || [], { genre: g.id });
  }
}
const FUZZY_KEYS = [...BY_KEY.keys()].filter((k) => k.length >= 5);

function levenshtein(a, b, max) {
  if (Math.abs(a.length - b.length) > max) return max + 1;
  let prev = Array.from({ length: b.length + 1 }, (_, i) => i);
  for (let i = 1; i <= a.length; i++) {
    const cur = [i];
    let best = i;
    for (let j = 1; j <= b.length; j++) {
      cur[j] = Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
      best = Math.min(best, cur[j]);
    }
    if (best > max) return max + 1;
    prev = cur;
  }
  return prev[b.length];
}

/**
 * Trouve les artistes cités dans un texte.
 * @returns {{name, type: 'fr'|'us', exact: boolean, said: string, entry}[]}
 */
export function findArtists(text) {
  const tokens = normalize(text).replace(/\$/g, 's').split(/[^a-z0-9]+/).filter(Boolean);
  const cands = [];
  for (let i = 0; i < tokens.length; i++) {
    for (let n = Math.min(4, tokens.length - i); n >= 1; n--) {
      const gram = tokens.slice(i, i + n).join('');
      if (!gram || STOP.has(gram)) continue;
      const exact = BY_KEY.get(gram);
      if (exact) { cands.push({ i, n, score: 100 + n * 10 + gram.length, entry: exact, exact: true }); continue; }
      if (gram.length < 5 || n > 3) continue;
      const max = gram.length >= 9 ? 2 : 1;
      let best = null;
      for (const k of FUZZY_KEYS) {
        const d = levenshtein(gram, k, max);
        if (d <= max && (!best || d < best.d)) best = { k, d };
      }
      if (best) cands.push({ i, n, score: 60 + n * 10 - best.d * 15, entry: BY_KEY.get(best.k), exact: false });
    }
  }
  cands.sort((a, b) => b.score - a.score);
  const used = new Set();
  const out = [];
  for (const c of cands) {
    const span = Array.from({ length: c.n }, (_, k) => c.i + k);
    if (span.some((t) => used.has(t))) continue;
    if (out.some((o) => o.name === c.entry.name)) continue;
    span.forEach((t) => used.add(t));
    out.push({ name: c.entry.name, type: c.entry.type, exact: c.exact, said: tokens.slice(c.i, c.i + c.n).join(' '), entry: c.entry, pos: c.i });
  }
  return out.sort((a, b) => a.pos - b.pos);
}

/** Suggestions pendant la frappe : artistes dont le nom commence par ce qui est tapé. */
export function suggestArtists(partial, limit = 6) {
  const k = artistKey(partial);
  if (k.length < 2) return [];
  const seen = new Set();
  const out = [];
  for (const e of ENTRIES) {
    if (seen.has(e.name)) continue;
    const hit = e.keys.some((key) => key.startsWith(k));
    if (hit) { seen.add(e.name); out.push({ name: e.name, type: e.type, entry: e }); }
  }
  // les noms qui commencent exactement par la saisie d'abord, puis les FR
  out.sort((a, b) => (artistKey(b.name).startsWith(k) - artistKey(a.name).startsWith(k)) || (a.type === 'fr' ? -1 : 1) - (b.type === 'fr' ? -1 : 1) || a.name.length - b.name.length);
  return out.slice(0, limit);
}

export const ARTIST_COUNT = { fr: FR_ARTISTS.length, us: seenUs.size };
