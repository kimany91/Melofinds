// Planificateur : transforme ta description (« rapide, énergique et musicale »)
// en un plan de recherche lisible : ambiances reconnues → courants de rap →
// artistes US → requêtes « type beat » envoyées à YouTube.

import { normalize, hasWord, escapeRe } from './text.js';
import { MOODS, INSTRUMENTS, GENRES, GENRE_BY_ID } from './genres.js';
import { findArtists } from './artistmatch.js';

// Profondeur de recherche. Le mobile démarre en « rapide » (moins de requêtes,
// moins de données), le PC en « normal ». On peut forcer « approfondie ».
export const DEPTHS = {
  rapide: { id: 'rapide', label: 'Rapide', queries: 3, perQuery: 15, maxVideos: 45, genres: 2, artistsPerGenre: 1 },
  normal: { id: 'normal', label: 'Normale', queries: 5, perQuery: 20, maxVideos: 100, genres: 3, artistsPerGenre: 2 },
  approfondie: { id: 'approfondie', label: 'Approfondie', queries: 8, perQuery: 30, maxVideos: 200, genres: 3, artistsPerGenre: 3 },
};

export function defaultDepth(device) {
  return device === 'mobile' ? 'rapide' : 'normal';
}

export function resolveDepth(depth, device) {
  return DEPTHS[depth] || DEPTHS[defaultDepth(device)];
}

const NORM_MOODS = Object.entries(MOODS).map(([id, m]) => ({ id, ...m, nwords: [...new Set(m.words.map(normalize))] }));
const NORM_INSTR = Object.entries(INSTRUMENTS).map(([id, words]) => ({ id, nwords: [...new Set(words.map(normalize))] }));

// Index artistes → { name, genres[], aliases[] }
const ARTISTS = (() => {
  const map = new Map();
  for (const g of GENRES) {
    for (const name of g.artists) {
      const key = name.toLowerCase();
      if (!map.has(key)) map.set(key, { name, genres: [], aliases: new Set([normalize(name)]) });
      const a = map.get(key);
      a.genres.push(g.id);
      for (const al of g.aliasesArtists?.[name] || []) a.aliases.add(normalize(al));
    }
  }
  return [...map.values()].map((a) => ({ ...a, aliases: [...a.aliases] }));
})();

// Un artiste présent dans plusieurs courants ne compte que pour le premier
// (son courant principal), sinon chaque prod Lil Uzi serait aussi « Jersey club ».
const ARTIST_OWNER = new Map();
for (const g of GENRES) for (const name of g.artists) if (!ARTIST_OWNER.has(name)) ARTIST_OWNER.set(name, g.id);

export function licenseSuffix(licenses = []) {
  const set = new Set(licenses);
  if (set.has('ffp') || set.has('upto')) return 'free for profit';
  if (set.has('fnp')) return 'free';
  return '';
}

function detectMoods(n) {
  const out = [];
  for (const m of NORM_MOODS) {
    const matched = m.nwords.filter((w) => hasWord(n, w));
    if (matched.length) out.push({ id: m.id, label: m.label, en: m.en, matched });
  }
  return out;
}

function detectInstruments(n) {
  return NORM_INSTR.filter((i) => i.nwords.some((w) => hasWord(n, w))).map((i) => i.id);
}

// Noms de courants écrits dans un texte. Le nom le plus long l'emporte sur un
// nom plus court qu'il contient : « trap metal » → Trap metal (pas Trap),
// « uk drill » → UK drill (pas NY drill), « glitch hop » → Glitch hop.
const ALIAS_INDEX = GENRES.flatMap((g) => [...new Set(g.aliases.map(normalize))].map((a) => ({
  id: g.id, len: a.length, re: new RegExp(`(^|[^a-z0-9])${escapeRe(a)}(?=$|[^a-z0-9])`, 'g'),
})));

function aliasHits(n, minLen = 0) {
  const hits = [];
  for (const { id, len, re } of ALIAS_INDEX) {
    if (len <= minLen) continue;
    re.lastIndex = 0;
    let m;
    while ((m = re.exec(n))) {
      const s = m.index + m[1].length;
      hits.push({ id, s, e: s + len });
      re.lastIndex = s + 1;
    }
  }
  return hits.filter((h) => !hits.some((o) => o.id !== h.id && o.s <= h.s && o.e >= h.e && o.e - o.s > h.e - h.s));
}

function detectGenres(n) {
  const ids = new Set(aliasHits(n).map((h) => h.id));
  return GENRES.filter((g) => ids.has(g.id)).map((g) => g.id);
}

const US_GENRES = new Map(ARTISTS.map((a) => [a.name, a.genres]));
// Nom à taper sur YouTube (« Bu$hi » → « Bushi », apostrophes simples)
const ytName = (name) => name.replace(/[’‘]/g, "'").replace(/\$/g, 's');

function detectBpm(n) {
  const m = n.match(/(\d{2,3})\s*-?\s*bpm/) || n.match(/bpm\s*[:=]?\s*(\d{2,3})/);
  if (!m) return null;
  const v = Number(m[1]);
  return v >= 50 && v <= 220 ? v : null;
}

/**
 * Construit le plan de recherche.
 * @param {string} prompt  description libre de la prod voulue
 * @param {{licenses?: string[], device?: string, depth?: string, manualQuery?: string}} opts
 */
export function buildPlan(prompt = '', opts = {}) {
  const device = opts.device === 'mobile' ? 'mobile' : 'desktop';
  const depth = resolveDepth(opts.depth, device);
  const n = normalize(prompt);
  const notes = [];

  const moods = detectMoods(n);
  const instruments = detectInstruments(n);
  const namedGenres = detectGenres(n);
  // Rappeurs cités (FR ou US), même mal écrits : « à la luther », « la feve »…
  const found = findArtists(prompt);
  const namedArtists = found.filter((f) => f.type === 'us').map((f) => ({ name: f.name, genres: US_GENRES.get(f.name) || [f.entry.genre] }));
  const namedFr = found.filter((f) => f.type === 'fr').map((f) => f.entry.fr);
  for (const f of found) if (!f.exact) notes.push(`J’ai compris « ${f.said} » comme ${f.name}.`);
  const explicitBpm = detectBpm(n);
  const moodIds = new Set(moods.map((m) => m.id));

  // --- Score des courants
  const scored = GENRES.map((g) => {
    let score = 0;
    const why = [];
    for (const m of moods) {
      const w = g.moods[m.id] || 0;
      if (w) {
        // Courant de niche : ses ambiances comptent moins (il sort surtout quand on le cite)
        score += w > 0 ? w * g.pop : w;
        if (w > 0) why.push(m.label.toLowerCase());
      }
    }
    if (namedGenres.includes(g.id)) { score += 8; why.unshift('cité directement'); }
    if (namedArtists.some((a) => a.genres.includes(g.id))) { score += 6; why.unshift('artiste cité'); }
    for (const fr of namedFr) {
      const i = fr.styles.indexOf(g.id);
      if (i >= 0) { score += 12 - i * 3; why.unshift(`style de ${fr.name}`); }
      if (fr.us.some((u) => ARTIST_OWNER.get(u) === g.id)) score += 2;
    }
    if (explicitBpm) {
      const [lo, hi] = g.bpm;
      if (explicitBpm >= lo - 3 && explicitBpm <= hi + 3) score += 2;
      else score -= 2;
    }
    return { id: g.id, label: g.label, score: Math.round(score * 10) / 10, why, bpm: g.bpm };
  }).sort((a, b) => b.score - a.score);

  let selected;
  const top = scored[0];
  if (!top || top.score <= 0) {
    selected = [GENRE_BY_ID.trap, GENRE_BY_ID['melodic-trap']].map((g) => ({ id: g.id, label: g.label, score: 0, why: ['par défaut'], bpm: g.bpm }));
    notes.push('Aucune ambiance reconnue : recherche par défaut en trap / melodic trap. Essaie des mots comme « sombre », « rapide », « mélodique », « drill », « Lil Uzi »…');
  } else {
    const forced = scored.filter((g) => namedGenres.includes(g.id));
    const rest = scored.filter((g) => !namedGenres.includes(g.id) && g.score > 0 && g.score >= top.score * 0.6);
    selected = [...forced, ...rest].slice(0, Math.max(depth.genres, forced.length));
  }

  // --- Artistes
  const artists = [];
  const seen = new Set();
  const pushArtist = (name, genreId, reason) => {
    const k = name.toLowerCase();
    if (seen.has(k)) return;
    seen.add(k);
    artists.push({ name, genre: genreId, genreLabel: GENRE_BY_ID[genreId]?.label || '', reason });
  };
  for (const a of namedArtists) pushArtist(a.name, a.genres[0], 'cité dans ta demande');
  for (const fr of namedFr) {
    for (const u of fr.us.slice(0, depth.id === 'rapide' ? 2 : 3)) pushArtist(u, ARTIST_OWNER.get(u) || fr.styles[0], `son proche de ${fr.name}`);
  }
  for (const g of selected) {
    const list = GENRE_BY_ID[g.id].artists;
    let added = 0;
    for (const name of list) {
      if (added >= depth.artistsPerGenre) break;
      if (!seen.has(name.toLowerCase())) { pushArtist(name, g.id, `référence du courant ${g.label}`); added++; }
    }
  }

  // --- Plage de BPM conseillée
  let bpmRange;
  if (explicitBpm) {
    bpmRange = { min: explicitBpm - 5, max: explicitBpm + 5, source: `${explicitBpm} BPM demandé` };
  } else {
    let [lo, hi] = selected[0].bpm;
    const span = hi - lo;
    if (moodIds.has('fast') && !moodIds.has('slow')) lo = Math.round(lo + span * 0.4);
    if (moodIds.has('slow') && !moodIds.has('fast')) hi = Math.round(hi - span * 0.4);
    bpmRange = { min: lo, max: hi, source: `typique du ${selected[0].label}${moodIds.has('fast') ? ', côté rapide' : moodIds.has('slow') ? ', côté lent' : ''}` };
  }

  // --- Requêtes YouTube
  const suffix = licenseSuffix(opts.licenses);
  const sfx = suffix ? ` ${suffix}` : '';
  const queries = [];
  const qseen = new Set();
  const addQuery = (q, why) => {
    const clean = q.replace(/\s+/g, ' ').trim();
    const k = clean.toLowerCase();
    if (!clean || qseen.has(k)) return;
    qseen.add(k);
    queries.push({ q: clean, why });
  };

  const manual = (opts.manualQuery || '').trim();
  if (manual) {
    const hasFree = /free/i.test(manual);
    addQuery(hasFree || !suffix ? manual : `${manual}${sfx}`, 'ta recherche directe');
  }

  const moodWords = moods
    .filter((m) => ['energetic', 'dark', 'sad', 'happy', 'chill', 'aggressive', 'bouncy', 'atmospheric', 'epic', 'melodic', 'experimental'].includes(m.id))
    .map((m) => m.en);
  const firstPerGenre = selected.map((g) => artists.find((a) => a.genre === g.id)).filter(Boolean);
  const named = artists.filter((a) => a.reason === 'cité dans ta demande');
  const instrumentEn = { piano: 'piano', guitar: 'guitar', synth: 'synth', strings: 'violin', flute: 'flute', bells: 'bells', choir: 'choir', sax: 'sax', '808': '808', orchestra: 'orchestral' };

  // Les beatmakers FR font aussi des « <rappeur FR> type beat »
  for (const fr of namedFr.slice(0, 2)) addQuery(`${ytName(fr.name)} type beat${sfx}`, `type beats faits pour ${fr.name}`);
  for (const a of named) addQuery(`${a.name} type beat${sfx}`, `artiste que tu as cité`);
  for (const a of artists.filter((x) => x.reason.startsWith('son proche de'))) addQuery(`${a.name} type beat${sfx}`, `${a.reason} (${a.genreLabel})`);
  for (const a of firstPerGenre) addQuery(`${a.name} type beat${sfx}`, `artiste phare du courant ${a.genreLabel}`);
  if (selected[0]) {
    const g = GENRE_BY_ID[selected[0].id];
    const mw = moodWords.filter((w) => !g.query.includes(w)).slice(0, 2).join(' ');
    addQuery(`${mw} ${g.query} type beat${sfx}`, `courant ${g.label}${mw ? ` + ambiance « ${mw} »` : ''}`);
  }
  if (instruments.length && artists[0]) {
    addQuery(`${artists[0].name} type beat ${instruments.map((i) => instrumentEn[i]).slice(0, 2).join(' ')}${sfx}`, `instrument demandé (${instruments.join(', ')})`);
  }
  for (const a of artists) addQuery(`${a.name} type beat${sfx}`, `${a.reason}`);
  for (const g of selected.slice(1)) {
    const gg = GENRE_BY_ID[g.id];
    addQuery(`${moodWords[0] ? moodWords[0] + ' ' : ''}${gg.query} type beat${sfx}`, `courant ${gg.label}`);
  }
  if (artists.length >= 2) addQuery(`${artists[0].name} x ${artists[1].name} type beat${sfx}`, 'mélange des deux artistes principaux');
  if (explicitBpm) addQuery(`${GENRE_BY_ID[selected[0].id].query} type beat ${explicitBpm} bpm${sfx}`, 'BPM demandé');

  // Demande très ciblée : on complète avec d'autres artistes du même courant,
  // puis avec les courants voisins, pour utiliser toute la profondeur choisie.
  for (const g of selected) {
    if (queries.length >= depth.queries) break;
    for (const name of GENRE_BY_ID[g.id].artists) {
      if (queries.length >= depth.queries) break;
      if (seen.has(name.toLowerCase())) continue;
      pushArtist(name, g.id, `autre référence du courant ${g.label}`);
      addQuery(`${name} type beat${sfx}`, `autre artiste du courant ${g.label}`);
    }
  }
  for (const g of scored.filter((x) => x.score > 0 && !selected.some((s) => s.id === x.id))) {
    if (queries.length >= depth.queries) break;
    const gg = GENRE_BY_ID[g.id];
    const name = gg.artists.find((a) => !seen.has(a.toLowerCase()));
    if (!name) continue;
    pushArtist(name, g.id, `courant voisin ${gg.label}`);
    addQuery(`${name} type beat${sfx}`, `courant voisin ${gg.label} (${g.why.join(', ') || 'proche'})`);
  }

  const finalQueries = queries.slice(0, depth.queries);

  return {
    prompt,
    device,
    depth: { id: depth.id, label: depth.label, perQuery: depth.perQuery, maxVideos: depth.maxVideos },
    moods: moods.map(({ id, label, matched }) => ({ id, label, matched })),
    instruments,
    genres: selected.map(({ id, label, score, why, bpm }) => ({ id, label, score, why, bpm })),
    // Seulement les artistes vraiment utilisés dans les requêtes envoyées
    artists: artists.filter((a) => finalQueries.some((q) => q.q.toLowerCase().includes(a.name.toLowerCase()))),
    bpmRange,
    // Rappeurs reconnus dans la description, avec ce que l'algo en a déduit
    recognized: found.map((f) => (f.type === 'fr'
      ? { name: f.name, type: 'fr', said: f.said, exact: f.exact, styles: f.entry.fr.styles.map((id) => GENRE_BY_ID[id]?.label).filter(Boolean), us: f.entry.fr.us, note: f.entry.fr.note }
      : { name: f.name, type: 'us', said: f.said, exact: f.exact, styles: [GENRE_BY_ID[f.entry.genre]?.label].filter(Boolean), us: [] })),
    licenseSuffix: suffix,
    queries: finalQueries,
    notes,
  };
}

// ---------------------------------------------------------------------------
// Classification d'une vidéo trouvée : à quels courants appartient cette prod ?


const GENRE_MATCHERS = GENRES.map((g) => ({
  id: g.id,
  label: g.label,
  aliases: g.aliases.map(normalize),
  artists: g.artists
    .filter((name) => ARTIST_OWNER.get(name) === g.id)
    .flatMap((name) => [normalize(name), ...(g.aliasesArtists?.[name] || []).map(normalize)]),
}));

export function classifyStyles(title = '', description = '') {
  const t = normalize(title);
  const d = normalize(description).slice(0, 600);
  const inTitle = new Set(aliasHits(t, 2).map((h) => h.id));
  const out = [];
  for (const g of GENRE_MATCHERS) {
    let s = 0;
    if (inTitle.has(g.id)) s += 3;
    if (g.artists.some((a) => a.length > 2 && hasWord(t, a))) s += 2;
    if (g.aliases.some((a) => a.length > 3 && hasWord(d, `#${a.replace(/\s+/g, '')}`))) s += 1;
    if (s) out.push({ id: g.id, label: g.label, s });
  }
  return out.sort((a, b) => b.s - a.s).slice(0, 3).map(({ id, label }) => ({ id, label }));
}

export function classifyMoods(title = '', description = '') {
  const t = normalize(`${title} ${description.slice(0, 600)}`);
  return NORM_MOODS.filter((m) => [m.en, ...m.nwords].some((w) => w.length > 3 && hasWord(t, normalize(w)))).map((m) => m.id);
}
