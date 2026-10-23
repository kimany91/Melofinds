// Filtres et tris appliqués aux résultats (côté navigateur : instantané).

import { CATEGORY_ORDER } from './license.js';
import { normalize } from './text.js';

/**
 * Recherche dans les descriptions : « spotify wav », « "free for profit" »,
 * « drill -lease » (le « - » exclut un mot).
 */
export function parseTextQuery(q = '') {
  const include = [];
  const exclude = [];
  const re = /(-?)"([^"]+)"|(-?)(\S+)/g;
  let m;
  while ((m = re.exec(q))) {
    const neg = m[1] || m[3];
    const term = normalize(m[2] ?? m[4]).trim();
    if (!term || term === '-') continue;
    (neg ? exclude : include).push(term);
  }
  return { include, exclude };
}

export function matchesText(r, parsed) {
  if (!parsed || (!parsed.include.length && !parsed.exclude.length)) return true;
  const hay = normalize(`${r.title}\n${r.channel || ''}\n${r.description || ''}`);
  return parsed.include.every((t) => hay.includes(t)) && !parsed.exclude.some((t) => hay.includes(t));
}

/**
 * @param {object[]} results  vidéos analysées
 * @param {object} f
 *   licenses:   ids de catégories gardées (ffp, upto, fnp, paid, unknown)
 *   uptoMin:    pour « Up to », limite minimale de streams (ex. 5000)
 *   bpm:        { enabled, min, max, requireBpm }
 *   style:      id de courant ('' = tous)
 *   noCredit:   true = écarter les prods où le crédit est obligatoire
 *   text:       recherche dans titre + description
 *   beatsOnly:  true = écarter ce qui ne ressemble pas à une prod
 */
export function filterResults(results, f = {}) {
  const licenses = new Set(f.licenses?.length ? f.licenses : CATEGORY_ORDER);
  const parsed = f.text ? parseTextQuery(f.text) : null;
  return results.filter((r) => {
    if (f.beatsOnly !== false && !r.isBeat) return false;
    if (!licenses.has(r.license.category)) return false;
    if (r.license.category === 'upto' && f.uptoMin && (r.license.limit || 0) < f.uptoMin) return false;
    if (f.noCredit && r.license.creditRequired) return false;
    if (f.style && !r.styles.some((s) => s.id === f.style)) return false;
    if (parsed && !matchesText(r, parsed)) return false;
    if (f.bpm?.enabled) {
      if (r.bpm == null) return !f.bpm.requireBpm;
      if (f.bpm.min && r.bpm < f.bpm.min) return false;
      if (f.bpm.max && r.bpm > f.bpm.max) return false;
    }
    return true;
  });
}

const SORTS = {
  pertinence: (a, b) => b.score - a.score,
  'bpm-asc': (a, b) => (a.bpm ?? 999) - (b.bpm ?? 999) || b.score - a.score,
  'bpm-desc': (a, b) => (b.bpm ?? -1) - (a.bpm ?? -1) || b.score - a.score,
  vues: (a, b) => (b.views || 0) - (a.views || 0),
  recent: (a, b) => String(b.publishedAt || '').localeCompare(String(a.publishedAt || '')),
  limite: (a, b) => (b.license.limit || (b.license.category === 'ffp' ? Infinity : 0)) - (a.license.limit || (a.license.category === 'ffp' ? Infinity : 0)) || b.score - a.score,
};

export function sortResults(results, sort = 'pertinence') {
  return [...results].sort(SORTS[sort] || SORTS.pertinence);
}

/** Regroupe par catégorie de licence, dans l'ordre FFP → Up to → Free → Payant → Inconnu. */
export function groupByCategory(results) {
  const groups = Object.fromEntries(CATEGORY_ORDER.map((c) => [c, []]));
  for (const r of results) groups[r.license.category].push(r);
  return CATEGORY_ORDER.map((c) => ({ category: c, items: groups[c] })).filter((g) => g.items.length);
}

/** Liste des courants présents dans les résultats (pour le filtre « style »). */
export function stylesIn(results) {
  const m = new Map();
  for (const r of results) for (const s of r.styles) m.set(s.id, { ...s, count: (m.get(s.id)?.count || 0) + 1 });
  return [...m.values()].sort((a, b) => b.count - a.count);
}
