// Petits utilitaires réseau / parsing partagés par les sources YouTube.

/** Exécute `fn` sur chaque élément avec au plus `limit` appels en parallèle. */
export async function pMap(items, fn, limit = 4) {
  const out = new Array(items.length);
  let next = 0;
  const workers = Array.from({ length: Math.min(limit, items.length) }, async () => {
    while (next < items.length) {
      const i = next++;
      try {
        out[i] = await fn(items[i], i);
      } catch (err) {
        out[i] = { error: err };
      }
    }
  });
  await Promise.all(workers);
  return out;
}

/** Cache mémoire très simple avec durée de vie. */
export class TtlCache {
  constructor(ttlMs, max = 2000) {
    this.ttl = ttlMs;
    this.max = max;
    this.map = new Map();
  }
  get(k) {
    const e = this.map.get(k);
    if (!e) return undefined;
    if (Date.now() > e.exp) { this.map.delete(k); return undefined; }
    return e.v;
  }
  set(k, v) {
    if (this.map.size >= this.max) this.map.delete(this.map.keys().next().value);
    this.map.set(k, { v, exp: Date.now() + this.ttl });
  }
}

/**
 * Extrait l'objet JSON qui suit `marker` dans une page HTML
 * (ex. « var ytInitialData = {...}; »), en respectant les chaînes.
 */
export function extractJsonAfter(html, marker) {
  const at = html.indexOf(marker);
  if (at === -1) return null;
  const start = html.indexOf('{', at + marker.length);
  if (start === -1) return null;
  let depth = 0;
  let inStr = false;
  let esc = false;
  for (let i = start; i < html.length; i++) {
    const c = html[i];
    if (inStr) {
      if (esc) esc = false;
      else if (c === '\\') esc = true;
      else if (c === '"') inStr = false;
      continue;
    }
    if (c === '"') inStr = true;
    else if (c === '{') depth++;
    else if (c === '}') {
      depth--;
      if (depth === 0) {
        try {
          return JSON.parse(html.slice(start, i + 1));
        } catch {
          return null;
        }
      }
    }
  }
  return null;
}

/** « 1,234,567 views » → 1234567 ; « 12K views » → 12000 */
export function parseViews(s) {
  if (s == null) return null;
  if (typeof s === 'number') return s;
  const t = String(s).toLowerCase().replace(/ /g, ' ');
  const m = t.match(/([\d.,\s]+)\s*([km])?/);
  if (!m) return null;
  let raw = m[1].trim();
  let v;
  if (m[2]) v = Number(raw.replace(',', '.')) * (m[2] === 'k' ? 1e3 : 1e6);
  else v = Number(raw.replace(/[.,\s]/g, ''));
  return Number.isFinite(v) ? Math.round(v) : null;
}

/** ISO 8601 (PT3M25S) → secondes */
export function parseIsoDuration(iso) {
  const m = /^P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?$/.exec(iso || '');
  if (!m) return null;
  return (+m[1] || 0) * 86400 + (+m[2] || 0) * 3600 + (+m[3] || 0) * 60 + (+m[4] || 0);
}

/** « 3:25 » → 205 */
export function parseClock(s) {
  if (!s) return null;
  const parts = String(s).split(':').map(Number);
  if (parts.some((n) => !Number.isFinite(n))) return null;
  return parts.reduce((acc, n) => acc * 60 + n, 0);
}

export function thumb(id, device) {
  return `https://i.ytimg.com/vi/${id}/${device === 'mobile' ? 'mqdefault' : 'hqdefault'}.jpg`;
}
