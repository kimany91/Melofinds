// Nom de fichier d'une prod, exactement comme Melofinds PC (pc/mf_core.py : build_name) :
// « Titre [C# min, 150 BPM] [FFP] ». Jamais « free », « ffp », « gratuit »… dans le nom ; ce
// que Tunebat a trouvé va dans son groupe « [(Finded) …] ». Sans caractère dangereux.

const FREE_BRACKETS = /[\[({【「*]\s*(?:100\s*%\s*)?(?:free|ffp|f4p|fnp|gratuit|royalty)[^\])}】」*\n]{0,40}[\])}】」*]/gi;
const FREE_WORDS = [
  /\b(?:100\s*%\s*)?free\s*(?:for|4)\s*(?:non[\s-]*)?(?:profit|commercial)(?:\s*(?:use|beats?|instrumental))?\b/gi,
  /\b(?:non[\s-]*)?(?:for\s*)?profit\s*use\b/gi,
  /\broyalty[\s-]*free\b|\blibre\s*de\s*droits?\b/gi,
  /\b(?:ffp|f4p|fnp)\b/gi,
  /\bfree\s*(?:beat|instrumental|instru|download|dl)s?\b/gi,
  /\b(?:100\s*%\s*)?free\b/gi,
  /\bgratuite?s?\b/gi,
];
const ALLOWED = /[^\p{L}\p{N}_\s\-[\]()',.&+!#]/gu;
export const FOUND_TAG = '(Finded)';

export function cleanProdTitle(title) {
  let t = String(title || '').normalize('NFC');
  t = t.replace(/[“”«»]/g, '"');
  t = t.replace(FREE_BRACKETS, ' ');
  for (const rx of FREE_WORDS) t = t.replace(rx, ' ');
  t = t.replace(/"/g, "'");
  t = t.replace(ALLOWED, ' ');
  t = t.replace(/[[(]\s*[\])]|'\s*'/g, ' ');
  t = t.replace(/\s*([|\-–—:,])\s*([|\-–—:,]\s*)+/g, ' $1 ');
  t = t.replace(/\s{2,}/g, ' ');
  t = t.replace(/^[\s|\-–—:,/.+&]+|[\s|\-–—:,/.+&]+$/g, '');
  return t.trim() || 'Prod';
}

/** « B min » → « Key B minor ». */
export function keyWords(key) {
  const m = String(key || '').match(/^([A-G][#b]?) (min|maj)$/);
  return m ? `Key ${m[1]} ${m[2] === 'min' ? 'minor' : 'major'}` : `Key ${key}`;
}

export function tagGroups(key = null, bpm = null, tbKey = false, tbBpm = false) {
  const b = bpm ? `${bpm} BPM` : null;
  const own = [[key, tbKey], [b, tbBpm]].filter(([x, tb]) => x && !tb).map(([x]) => x);
  const found = [[key ? keyWords(key) : null, tbKey], [b, tbBpm]].filter(([x, tb]) => x && tb).map(([x]) => x);
  const parts = [];
  if (own.length) parts.push(`[${own.join(', ')}]`);
  if (found.length) parts.push(`[${FOUND_TAG} ${found.join(', ')}]`);
  return parts.join(' ');
}

export function licenceTag(lic, limit) {
  if (lic === 'ffp') return 'FFP';
  if (lic === 'fnp') return 'F';
  if (lic === 'upto') {
    const n = Number.parseInt(limit, 10);
    return n > 0 && n < 1e10 ? `FFP, UPTO ${n}` : 'FFP, UPTO';
  }
  return null;
}

/** « Titre [Clé, BPM] [Licence] » (sans extension). */
export function prodFileName({ title, key = null, bpm = null, lic = null, limit = null, tbKey = false, tbBpm = false } = {}) {
  const base = cleanProdTitle(title).slice(0, 110).replace(/[\s\-,.]+$/, '');
  const tags = tagGroups(key, bpm, tbKey, tbBpm);
  let name = tags ? `${base} ${tags}` : base;
  const lt = licenceTag(lic, limit);
  if (lt) name = `${name} [${lt}]`;
  if (/^(con|prn|aux|nul|com\d|lpt\d)(\s.*)?$/i.test(name)) name = `Prod ${name}`;
  return name.replace(/[\s.]+$/, '') || 'Prod';
}
