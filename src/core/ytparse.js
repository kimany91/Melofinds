// Lecture des réponses de Parallel Search (pages YouTube converties en texte).
// Testé sur de vraies réponses : voir test/ytparse.test.js.

/** Âge YouTube « 11mo ago » → « il y a 11 mois ». */
export function frAge(s) {
  const m = String(s).match(/(\d+)\s*(mo|y|w|d|h|min|s)/i);
  if (!m) return s;
  const n = Number(m[1]);
  const u = { mo: 'mois', y: n > 1 ? 'ans' : 'an', w: 'sem.', d: 'j', h: 'h', min: 'min', s: 's' }[m[2].toLowerCase()];
  return `il y a ${n} ${u}`;
}

/** Page de résultats YouTube (markdown) → [{id, title, views, age}] */
export function parseResultsPage(text) {
  const out = [];
  const seen = new Set();
  const re = /^#+\s*\[(.+)\]\((https?:\/\/(?:www\.|m\.)?youtube\.com\/watch\?v=([\w-]{11})[^\s)]*)/gm;
  let m;
  while ((m = re.exec(String(text || '')))) {
    const id = m[3];
    if (seen.has(id)) continue;
    seen.add(id);
    const after = text.slice(re.lastIndex, re.lastIndex + 200);
    const stats = after.match(/\n\s*([\d.,]+[KMB]?)\s+(\d+\s*(?:mo|y|w|d|h|min|s)\w*\s+ago)/i);
    out.push({ id, title: m[1].trim(), views: stats?.[1] || null, age: stats ? frAge(stats[2]) : null });
  }
  return out;
}

export const cleanYtTitle = (t) => String(t || '').replace(/\s*-\s*YouTube\s*$/i, '').trim();

/** Retire les liens vers d'AUTRES vidéos (suggestions, « Now playing ») : leur titre
 *  (« [SOLD]… », « [FREE FOR PROFIT]… ») fausserait le verdict de la vidéo lue. */
export function removeVideoLinks(text) {
  let t = text;
  const re = /\]\((?:https?:\/\/(?:www\.|m\.)?youtube\.com)?\/?(?:watch\?v=|shorts\/)[^)\s]*(?:\s+"[^"]*")?\)/g;
  let m;
  const cuts = [];
  while ((m = re.exec(t))) {
    // remonte jusqu'au « [ » ouvrant correspondant (les titres contiennent souvent des crochets)
    let depth = 0;
    let i = m.index;
    for (; i >= 0; i--) {
      if (t[i] === ']') depth++;
      else if (t[i] === '[') { depth--; if (depth === 0) break; }
    }
    if (i >= 0) cuts.push([t[i - 1] === '!' ? i - 1 : i, m.index + m[0].length]);
  }
  for (const [a, b] of cuts.reverse()) t = `${t.slice(0, a)} ${t.slice(b)}`;
  return t;
}

/** Texte d'une page vidéo → description du producteur (sans lecteur, transcription, compteurs). */
export function cleanDescription(text, title, max = 2500) {
  let t = removeVideoLinks(String(text || ''));
  t = t.replace(/!?\[([^\]]*)\]\(([^)]*)\)/g, (_, a) => a || ' ');
  t = t.replace(/!?\[([^\]]*)\]\(([^)]*)\)/g, (_, a) => a || ' ');
  t = t.replace(/^#+\s*(?:Video details|Chapters|Description)\s*$/gim, ' ');
  t = t.replace(/^\s*[\d.,]+[KMB]?\s+\d+\s*\w+\s+ago\s*$/gim, ' ');
  t = t.replace(/#+\s*transcript[\s\S]*$/i, ' ');
  t = t.replace(/\(time \(seconds\): [\d.]+\)/g, ' ').replace(/\\?\[Music\\?\]/gi, ' ');
  t = t.replace(/#+\s*(?:Regular|Specialized) Content/gi, ' ').replace(/#+\s*Comments(?:\s*\d+)?/gi, ' ').replace(/#+\s*In this video/gi, ' ');
  t = t.replace(/\b\d{1,2}:\d{2}(?::\d{2})?(?:\s*\/\s*\d{1,2}:\d{2}(?::\d{2})?)?/g, ' ');
  t = t.replace(/•?\s*Watch full video|Skip navigation|Search with your voice|Now playing|\.\.\.more|…more/gi, ' ');
  t = t.replace(/^\s*(?:Live|Back|Transcript|Comments|\.\.\.)\s*$/gim, ' ');
  t = t.replace(/\b[\d.,]+\s*[KMB]?\s*(?:Likes|Views|vues|likes)\b/g, ' ');
  for (const v of [title, cleanYtTitle(title)].filter((x) => x && x.length > 6)) t = t.split(v).join(' ');
  t = t.replace(/[ \t]+/g, ' ').replace(/\n\s*\n+/g, '\n').trim();
  return t.slice(0, max);
}

/** La description lue contient-elle vraiment quelque chose d'utile ? */
export function usefulDescription(t) {
  t = String(t || '').replace(/credit\s*card/gi, ' ');
  return t.replace(/\s+/g, ' ').trim().length >= 25
    && /free|profit|lease|licen|credit|crédit|bpm|key|buy|purchase|beatstars|bsta\.rs|spotify|stream|prod|instagram|contact|mail|gratuit/i.test(t);
}

/** « 56K » → 56000, « 1.2M » → 1200000, « 56,576 » → 56576, « 1,2 k » → 1200 */
export function parseCount(s) {
  if (typeof s === 'number') return Number.isFinite(s) ? s : null;
  const m = String(s || '').replace(/\s+/g, '').match(/^([\d.,]+)([KMB])?/i);
  if (!m) return null;
  let num = m[1];
  if (m[2]) num = num.replace(',', '.');
  else num = num.replace(/[.,]/g, '');
  const n = Number(num) * ({ K: 1e3, M: 1e6, B: 1e9 }[(m[2] || '').toUpperCase()] || 1);
  return Number.isFinite(n) ? Math.round(n) : null;
}

/** Page vidéo (texte) → { likes, views } : « 10K Likes 369K Views », « 56,576 views ». */
export function parseWatchStats(text) {
  const t = String(text || '');
  const likes = t.match(/([\d][\d.,]*\s*[KMB]?)\s*(?:likes?|j'aime|j’aime)\b/i);
  const views = t.match(/([\d][\d.,]*\s*[KMB]?)\s*(?:views?|vues)\b/i);
  return { likes: likes ? parseCount(likes[1]) : null, views: views ? parseCount(views[1]) : null };
}

/** Ratio likes / vues en %, ou null si on ne sait pas. */
export function likeRatio(likes, views) {
  if (!likes || !views || views <= 0) return null;
  return Math.min(100, (likes / views) * 100);
}

/** Titre affiché dans la liste : sans « [FREE FOR PROFIT] », « (FREE) », « FFP »…
 *  (l'algo a déjà lu la licence ; le titre complet reste dans les détails). */
export function displayTitle(title) {
  const orig = String(title || '');
  let t = orig
    // [FREE FOR PROFIT] (FREE) {FREE} 【FREE】 *FREE* [FFP] [100% FREE] [Free for non profit]
    .replace(/[[({【「*]\s*(?:100\s*%\s*)?(?:free|ffp|f4p|gratuit)\b[^\])}】」*\n]{0,30}[\])}】」*]/gi, ' ')
    .replace(/\b(?:100\s*%\s*)?free\s*(?:for|4)\s*(?:non[\s-]*)?profit(?:\s*(?:use|beats?|instrumental))?\b/gi, ' ')
    .replace(/\b(?:ffp|f4p|fnp)\b/gi, ' ')
    .replace(/^\s*(?:100\s*%\s*)?free\b(?:\s*(?:beat|instrumental|download|dl))?/i, ' ')
    .replace(/[|\-–—:]\s*free\s*$/i, ' ')
    .replace(/[[({]\s*[\])}]/g, ' ')
    .replace(/\s{2,}/g, ' ')
    .replace(/^[\s|\-–—:,/•]+|[\s|\-–—:,/•]+$/g, '')
    .trim();
  return t.length >= 3 ? t : orig.trim();
}

/**
 * Identifiant de playlist YouTube dans un lien collé (« youtube.com/playlist?list=… »,
 * « watch?v=…&list=… », music.youtube.com, youtu.be…), ou l'identifiant seul. Les playlists
 * non répertoriées marchent pareil : il suffit du lien. Les « mix » automatiques (RD…) ne
 * sont pas des playlists : ignorés.
 */
export function playlistIdOf(text) {
  const s = String(text || '').trim();
  let id = '';
  const m = s.match(/(?:youtube\.com|youtu\.be|youtube-nocookie\.com)\/[^\s]*?[?&]list=([A-Za-z0-9_-]{10,64})/i);
  if (m) id = m[1];
  else if (/^(?:PL|OL|UU|FL|LL)[A-Za-z0-9_-]{10,62}$/.test(s)) id = s;
  if (!id || /^(?:RD|UL|LM$|WL$)/.test(id)) return null;
  return id;
}

/**
 * Vidéos d'une page de playlist YouTube lue par Parallel Search (markdown) : chaque lien
 * « [titre](…watch?v=ID…) », dans l'ordre, sans les liens de service (« Tout lire », durées…).
 */
export function parsePlaylistPage(text) {
  const t = String(text || '');
  const out = [];
  const seen = new Set();
  const re = /\]\((?:https?:\/\/(?:www\.|m\.)?youtube\.com)?\/?watch\?v=([\w-]{11})[^\s)]*\)/g;
  let m;
  while ((m = re.exec(t))) {
    // remonte au « [ » qui ouvre ce lien (les titres ont souvent des crochets : « [FREE] … »)
    let depth = 0;
    let i = m.index;
    for (; i >= 0 && m.index - i < 300; i--) {
      if (t[i] === ']') depth++;
      else if (t[i] === '[' && --depth === 0) break;
    }
    if (i < 0 || depth !== 0) continue;
    const title = t.slice(i + 1, m.index).replace(/!\[[^\]]*\]\([^)]*\)/g, '').replace(/\s+/g, ' ').trim();
    const id = m[1];
    if (seen.has(id) || !title || /^(?:\d{1,2}:)?\d{1,2}:\d{2}$/.test(title) || /^(?:play all|tout lire|lecture|now playing|en cours|shuffle|aléatoire|\d+)$/i.test(title)) continue;
    seen.add(id);
    out.push({ id, title });
  }
  return out;
}
