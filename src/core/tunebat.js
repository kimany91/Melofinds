// Tunebat : clé et BPM d'un morceau sorti sur Spotify. Beaucoup de beatmakers y sortent
// aussi leurs prods (« NEMZZZ TYPE BEAT » par Nemzzz…). On ne garde un résultat que s'il
// correspond vraiment à la vidéo : même beatmaker et titre proche, ou titre proche et
// même durée (à 4 s près). Sinon rien : mieux vaut « BPM ? » qu'un faux BPM.

export const TB_SEARCH = 'https://api.tunebat.com/api/tracks/search?term=';

export const tbNorm = (s) => String(s || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase()
  .replace(/\$/g, 's').replace(/[^a-z0-9]+/g, ' ').trim();

/** Ressemblance de deux textes (coefficient de Dice sur les paires de lettres), 0 à 1. */
export function similarity(a, b) {
  a = tbNorm(a).replace(/ /g, '');
  b = tbNorm(b).replace(/ /g, '');
  if (!a || !b) return 0;
  if (a === b) return 1;
  if (a.length < 2 || b.length < 2) return 0;
  const pairs = new Map();
  for (let i = 0; i < a.length - 1; i++) { const p = a.slice(i, i + 2); pairs.set(p, (pairs.get(p) || 0) + 1); }
  let hit = 0;
  for (let i = 0; i < b.length - 1; i++) {
    const p = b.slice(i, i + 2);
    const n = pairs.get(p) || 0;
    if (n > 0) { pairs.set(p, n - 1); hit++; }
  }
  return (2 * hit) / (a.length + b.length - 2);
}

const NOISE = /\b(free|for profit|ffp|type beat|typebeat|instrumental|instru|beat|prod(?:uced)? by|prod\.?|\d{4}|hard|sad|dark|melodic|new|x)\b/gi;

/** Nom de la prod : le texte entre guillemets (« "HAZE" »), sinon le titre nettoyé. */
export function beatName(title) {
  const t = String(title || '');
  const q = t.match(/["“”«»]([^"“”«»]{2,60})["“”«»]/) || t.match(/(?:^|\W)'([^']{2,40})'(?!\w)/);
  if (q) return q[1].trim();
  return t.replace(/[\[(【][^\])】]*[\])】]/g, ' ').replace(NOISE, ' ').replace(/[|\-–—:]+/g, ' ').replace(/\s{2,}/g, ' ').trim();
}

/** Recherches à faire sur Tunebat (2 au plus : Tunebat limite le nombre de requêtes). */
export function tbQueries({ title, channel }) {
  const name = beatName(title);
  const ch = String(channel || '').replace(/\s*(beats?|prod|music|- topic)$/i, '').trim();
  const out = [];
  for (const q of [name && ch ? `${name} ${ch}` : '', name, String(title || '').replace(/[\[(【][^\])】]*[\])】]/g, ' ').trim()]) {
    const k = tbNorm(q);
    if (k.length >= 3 && !out.some((x) => tbNorm(x) === k)) out.push(q.trim());
  }
  return out.slice(0, 2);
}

/** Clé Tunebat (« A♯ minor », « D Major », « Bb minor ») → « A# min » / « D maj ». */
export function tbKey(k) {
  const m = String(k || '').replace(/♯/g, '#').replace(/♭/g, 'b').match(/^\s*([A-Ga-g])\s*(#|b)?\s*(major|minor|maj|min)/i);
  if (!m) return null;
  return `${m[1].toUpperCase()}${m[2] || ''} ${m[3].toLowerCase().startsWith('maj') ? 'maj' : 'min'}`;
}

/** Le morceau correspond-il à la vidéo ? {score} ou null.
 *  Même beatmaker et titre proche, titre proche et même durée (4 s), ou beatmaker + durée. */
export function matchScore({ n, artists = [], durMs }, { title, channel, duration }) {
  const name = beatName(title);
  const ch = tbNorm(String(channel || '').replace(/\s*(beats?|music|- topic)$/i, ''));
  n = String(n || '');
  const nameScore = Math.max(similarity(n, name), similarity(n, title), name && tbNorm(n).includes(tbNorm(name)) && tbNorm(name).length >= 4 ? 0.8 : 0);
  const artistOk = !!ch && ch.length >= 3 && artists.some((a) => {
    const an = tbNorm(String(a).replace(/^prod\.?\s*(by\s*)?/i, ''));
    return an.length >= 3 && (similarity(an, ch) >= 0.8 || ch.includes(an) || an.includes(ch));
  });
  const d = Number(durMs) / 1000;
  const durOk = Number(duration) > 0 && d > 0 && Math.abs(d - Number(duration)) <= 4;
  const ok = (artistOk && nameScore >= 0.6) || (durOk && nameScore >= 0.5) || (artistOk && durOk);
  return ok ? { score: nameScore + (artistOk ? 1 : 0) + (durOk ? 1 : 0) } : null;
}

/** Choisit le résultat Tunebat qui correspond à la vidéo, ou null. */
export function tbPick(items, { title, channel, duration }) {
  let best = null;
  for (const it of Array.isArray(items) ? items : []) {
    if (!it || typeof it !== 'object') continue;
    const n = String(it.n || '');
    const artists = Array.isArray(it.as) ? it.as.map(String) : [];
    const m = matchScore({ n, artists, durMs: it.d }, { title, channel, duration });
    if (!m) continue;
    const bpm = Math.round(Number(it.b));
    const key = tbKey(it.k);
    if (!(bpm >= 50 && bpm <= 220) && !key) continue;
    const { score } = m;
    if (!best || score > best.score) best = { score, bpm: bpm >= 50 && bpm <= 220 ? bpm : null, key, name: n, artists };
  }
  return best && { bpm: best.bpm, key: best.key, name: best.name, artists: best.artists };
}

// ---------------------------------------------------------------------------
// ReccoBeats : même catalogue (morceaux sortis sur Spotify), mais son API répond aux
// navigateurs (en-têtes CORS pour le site de l'app, sans clé) : c'est elle que l'app web
// utilise. Tunebat bloque les navigateurs (protection Cloudflare).

export const RB_API = 'https://api.reccobeats.com/v1';
const PITCH = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'];

/** Clé ReccoBeats (classe de hauteur 0-11 + mode 1 majeur / 0 mineur) → « G maj ». */
export function rbKey(key, mode) {
  const k = Number(key);
  if (!Number.isInteger(k) || k < 0 || k > 11 || (mode !== 0 && mode !== 1)) return null;
  return `${PITCH[k]} ${mode === 1 ? 'maj' : 'min'}`;
}

/** Recherches ReccoBeats : [{ searchText, artist? }] (titre de la prod, avec ou sans beatmaker). */
export function rbQueries({ title, channel }) {
  const name = beatName(title);
  const ch = String(channel || '').replace(/\s*(beats?|prod|music|- topic)$/i, '').trim();
  const out = [];
  if (tbNorm(name).length >= 3 && tbNorm(ch).length >= 3) out.push({ searchText: name, artist: ch });
  if (tbNorm(name).length >= 3) out.push({ searchText: name });
  return out;
}

/** Morceau ReccoBeats qui correspond à la vidéo, ou null : { id, name, artists, href }. */
export function rbPick(content, ctx) {
  let best = null;
  for (const it of Array.isArray(content) ? content : []) {
    if (!it || typeof it !== 'object' || !it.id) continue;
    const artists = (Array.isArray(it.artists) ? it.artists : []).map((a) => String(a?.name || '')).filter(Boolean);
    const m = matchScore({ n: it.trackTitle, artists, durMs: it.durationMs }, ctx);
    if (m && (!best || m.score > best.score)) best = { score: m.score, id: String(it.id), name: String(it.trackTitle || ''), artists, href: String(it.href || '') };
  }
  return best && { id: best.id, name: best.name, artists: best.artists, href: best.href };
}

/** Réponse « audio-features » → { bpm, key } (BPM arrondi entre 50 et 220). */
export function rbFeatures(f) {
  const t = Number(f?.tempo);
  const bpm = t >= 50 && t <= 220 ? Math.round(t) : null;
  const key = rbKey(f?.key, f?.mode);
  return bpm || key ? { bpm, key } : null;
}
