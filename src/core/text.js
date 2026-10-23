// Normalisation de texte partagée (serveur + navigateur).
// Les beatmakers écrivent souvent en police « fantaisie » (𝗙𝗥𝗘𝗘 𝗙𝗢𝗥 𝗣𝗥𝗢𝗙𝗜𝗧),
// avec des accents, des apostrophes typographiques, etc. On ramène tout en
// ASCII minuscule, tout en gardant une table de correspondance vers le texte
// d'origine pour pouvoir afficher l'extrait exact qui a servi à décider.

const COMBINING = /[̀-ͯ]/g;

const PUNCT_MAP = {
  '‘': "'", '’': "'", '‚': "'", '′': "'", '`': "'",
  '“': '"', '”': '"', '„': '"',
  '–': '-', '—': '-', '−': '-',
  ' ': ' ', ' ': ' ', ' ': ' ',
  'ß': 'ss',
};

function mapCodePoint(ch) {
  if (PUNCT_MAP[ch]) return PUNCT_MAP[ch];
  let out = ch.normalize('NFKC').normalize('NFD').replace(COMBINING, '');
  out = out.toLowerCase();
  // Les variantes d'emoji / sélecteurs de variation disparaissent.
  out = out.replace(/[︀-️​-‍]/g, '');
  return out;
}

/**
 * Normalise un texte et renvoie aussi `map` : map[i] = index dans l'original
 * du caractère normalisé i.
 */
export function normalizeWithMap(input) {
  const src = String(input ?? '');
  let text = '';
  const map = [];
  let i = 0;
  for (const ch of src) {
    const mapped = mapCodePoint(ch);
    for (const c of mapped) {
      text += c;
      map.push(i);
    }
    i += ch.length;
  }
  map.push(src.length);
  return { text, map, source: src };
}

export function normalize(input) {
  return normalizeWithMap(input).text;
}

/** Extrait lisible du texte original autour d'un match fait sur le texte normalisé. */
export function snippet(norm, start, end, pad = 40) {
  const { map, source } = norm;
  const s = map[Math.max(0, start)] ?? 0;
  const e = map[Math.min(map.length - 1, end)] ?? source.length;
  let from = Math.max(0, s - pad);
  let to = Math.min(source.length, e + pad);
  // Ne pas couper au milieu d'une ligne voisine : on s'arrête aux retours ligne.
  const before = source.lastIndexOf('\n', s - 1);
  if (before >= from) from = before + 1;
  const after = source.indexOf('\n', e);
  if (after !== -1 && after < to) to = after;
  let out = source.slice(from, to).trim();
  if (from > 0 && source[from - 1] !== '\n') out = '…' + out;
  if (to < source.length && source[to] !== '\n') out += '…';
  return out;
}

/** Échappe une chaîne pour l'utiliser dans une RegExp. */
export function escapeRe(s) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/** Teste si `needle` (déjà normalisé) apparaît comme mot entier dans `hay`. */
export function hasWord(hay, needle) {
  if (!needle) return false;
  const re = new RegExp(`(^|[^a-z0-9])${escapeRe(needle)}($|[^a-z0-9])`);
  return re.test(hay);
}
