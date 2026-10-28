// « Déjà posé dessus » : les morceaux de rappeurs qui ont utilisé la prod. On cherche sur
// YouTube et SoundCloud le nom de la prod et le beatmaker, on écarte les autres prods
// (type beats, instrus) et les vidéos du beatmaker lui-même, puis l'appli compare le son
// (empreinte, comme Shazam). On n'affiche que ce qui est sûr : confirmé au son, ou qui cite
// la prod ET le beatmaker.

import { tbNorm, similarity } from './tunebat.js';

/** Nom de la prod, seulement s'il est entre guillemets (« "HAZE" ») : sinon on ne le connaît pas. */
export function quotedName(title) {
  const t = String(title || '');
  const q = t.match(/["“”«»]([^"“”«»]{2,60})["“”«»]/) || t.match(/(?:^|\W)'([^']{2,40})'(?!\w)/);
  const n = q ? q[1].replace(/\s+/g, ' ').trim() : '';
  // « "FREE" », « "Type Beat" »… ne sont pas des noms
  return n && !/^(?:free|ffp|free\s*for\s*profit|type\s*beat|instrumental|beat|\d+)$/i.test(n) ? n : '';
}

const PROD_CREDIT = /\b(?:prod(?:uced)?\.?\s*(?:by\s*)?|beat\s*by\s*)[:\-–]?\s*@?([^\]\)\[(|,"“”«»\-–—/]{2,40})/i;

/** Le beatmaker : « prod. X » dans le titre, sinon le nom de la chaîne nettoyé. */
export function producersOf({ title, channel, description } = {}) {
  const out = [];
  const add = (s) => {
    const n = String(s || '').replace(/^@/, '').replace(/\s*(?:on the beat|beats?|prod(?:uction)?s?|music|officiel|official|- topic)\s*$/i, '').replace(/\s+/g, ' ').trim();
    if (tbNorm(n).length >= 2 && !out.some((x) => tbNorm(x) === tbNorm(n))) out.push(n);
  };
  const m = String(title || '').match(PROD_CREDIT);
  if (m) add(m[1]);
  add(channel);
  const d = String(description || '').match(PROD_CREDIT);
  if (d && out.length < 2) add(d[1]);
  return out.slice(0, 2);
}

/** Recherches à faire (YouTube et SoundCloud). */
export function usedByQueries(item) {
  const name = quotedName(item?.title);
  const [p] = producersOf(item || {});
  const qs = [];
  if (name && p) qs.push(`${name} prod ${p}`, `"${name}" ${p}`);
  if (p) qs.push(`prod. ${p}`, `prod by ${p}`);
  else if (name) qs.push(`"${name}" prod`);
  const seen = new Set();
  return qs.filter((q) => { const k = tbNorm(q); if (k.length < 3 || seen.has(k)) return false; seen.add(k); return true; }).slice(0, 4);
}

/** Une prod (type beat, instru, free…) ou un tuto, pas un son posé dessus. */
export function isBeatUpload(title) {
  return /type\s*beat|typebeat|\binstru(?:mental|mentale)?\b|\bbeat\s*(?:tape|pack)\b|free\s*for\s*profit|\bffp\b|[\[(]\s*free\s*[\])]|^\s*free\b|\bbpm\b|\bremake\b|\btuto(?:rial)?\b|how\s*i\s*made|cook(?:ing)?\s*up|making\s*(?:of|a)\b|fl\s*studio|\bdrum\s*kit\b|\bloop\s*kit\b|\bsample\s*pack\b|\bkaraok/i.test(String(title || ''));
}

const words = (s) => tbNorm(s).split(' ').filter(Boolean);
/** Le texte contient-il ces mots, à la suite ? */
function hasPhrase(text, phrase) {
  const t = words(text);
  const p = words(phrase);
  if (!p.length || p.join('').length < 3) return false;
  outer: for (let i = 0; i + p.length <= t.length; i++) {
    for (let j = 0; j < p.length; j++) if (t[i + j] !== p[j]) continue outer;
    return true;
  }
  return false;
}
const sameName = (a, b) => {
  const x = tbNorm(a).replace(/ /g, '');
  const y = tbNorm(b).replace(/ /g, '');
  return x.length >= 3 && y.length >= 3 && (x === y || similarity(x, y) >= 0.85);
};

/**
 * Tri d'un résultat : null (à écarter) ou { level } :
 * 'strong' = cite la prod et le beatmaker, 'credit' = crédite le beatmaker, 'name' = le nom seul.
 */
export function rateHit(hit, beat) {
  if (!hit || typeof hit !== 'object') return null;
  const title = String(hit.title || '');
  if (!title || (hit.id && hit.id === beat.id)) return null;
  if (isBeatUpload(title)) return null;
  const dur = Number(hit.duration);
  if (dur > 0 && (dur < 40 || dur > 480)) return null;
  const producers = beat.producers || [];
  // le beatmaker qui poste ses propres vidéos (autres prods, extraits) : écarté
  if (producers.some((p) => sameName(hit.uploader, p)) || (beat.channel && sameName(hit.uploader, beat.channel))) return null;
  const nameHit = !!beat.name && hasPhrase(title, beat.name);
  const credit = producers.some((p) => hasPhrase(title, p) && (/\bprod|\bbeat\s*by|@/i.test(title) || nameHit));
  const level = nameHit && credit ? 'strong' : credit ? 'credit' : nameHit ? 'name' : null;
  return level ? { level } : null;
}

const RANK = { strong: 0, credit: 1, name: 2 };

/** Résultats à garder et à vérifier au son, les plus sûrs d'abord (12 au plus). */
export function pickHits(items, item) {
  const beat = { id: item?.id, name: quotedName(item?.title), producers: producersOf(item || {}), channel: item?.channel || '' };
  const out = [];
  const seen = new Set();
  for (const hit of Array.isArray(items) ? items : []) {
    const r = rateHit(hit, beat);
    if (!r) continue;
    const k = `${hit.service}:${hit.id || hit.url}`;
    // le même son posté deux fois (YouTube / SoundCloud, ou deux chaînes) : une seule fois
    const t = `${tbNorm(hit.title)}`;
    if (seen.has(k) || seen.has(t)) continue;
    seen.add(k);
    seen.add(t);
    out.push({ ...hit, level: r.level });
  }
  out.sort((a, b) => RANK[a.level] - RANK[b.level] || (Number(b.views) || 0) - (Number(a.views) || 0));
  const yt = out.filter((x) => x.service === 'yt').slice(0, 10);
  const sc = out.filter((x) => x.service === 'sc').slice(0, 5);
  return [...yt, ...sc].sort((a, b) => RANK[a.level] - RANK[b.level] || (Number(b.views) || 0) - (Number(a.views) || 0));
}

/**
 * Ce qu'on affiche pour un résultat, d'après le son :
 * 'same' (vérifié au son), 'text' (cite la prod et le beatmaker, son pas vérifiable),
 * 'differs' (cite la prod et le beatmaker mais le son ne colle pas : prod modifiée ?), ou null.
 */
export function usedVerdict(level, sound) {
  if (sound?.status === 'ok' && sound.same) return 'same';
  if (level !== 'strong') return null;
  if (sound?.status === 'ok') return 'differs';
  return 'text';
}

/** Liens de recherche (site sans l'appli). */
export function usedByLinks(item) {
  const [q] = usedByQueries(item);
  if (!q) return [];
  const e = encodeURIComponent(q.replace(/"/g, ''));
  return [
    { label: 'YouTube', url: `https://www.youtube.com/results?search_query=${e}` },
    { label: 'SoundCloud', url: `https://soundcloud.com/search/sounds?q=${e}` },
    { label: 'Spotify', url: `https://open.spotify.com/search/${e}` },
  ];
}
