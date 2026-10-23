// Analyse de licence : lit le titre + TOUTE la description d'une vidéo et
// décide si la prod peut être sortie sur Spotify gratuitement.
//
// Catégories :
//   ffp     → Free for profit, sans limite : Spotify & co OK sans rien payer
//   upto    → Free for profit « up to » : gratuit jusqu'à X streams, ensuite licence
//   fnp     → Free (non-profit) : gratuit pour YouTube/SoundCloud, payer pour Spotify
//   paid    → Payant : il faut acheter une licence (ou prod vendue)
//   unknown → Rien de clair dans la description

import { normalizeWithMap, snippet } from './text.js';

export const CATEGORIES = {
  ffp: {
    id: 'ffp',
    label: 'Free for profit',
    short: 'FFP',
    help: 'Utilisable sur Spotify & co sans payer (souvent avec crédit).',
    spotify: 'oui',
  },
  upto: {
    id: 'upto',
    label: 'Up to',
    short: 'Up to',
    help: 'Free for profit jusqu’à une limite de streams, ensuite il faut une licence.',
    spotify: 'limité',
  },
  fnp: {
    id: 'fnp',
    label: 'Free (non-profit)',
    short: 'Free',
    help: 'Gratuit pour YouTube/SoundCloud sans monétisation. Pour Spotify il faut payer.',
    spotify: 'non',
  },
  paid: {
    id: 'paid',
    label: 'Payant',
    short: 'Payant',
    help: 'Il faut acheter une licence (lease / exclu), ou la prod est déjà vendue.',
    spotify: 'non',
  },
  unknown: {
    id: 'unknown',
    label: 'Inconnu',
    short: '?',
    help: 'La description ne dit rien de clair sur les droits.',
    spotify: '?',
  },
};

export const CATEGORY_ORDER = ['ffp', 'upto', 'fnp', 'paid', 'unknown'];

// ---------------------------------------------------------------------------
// Briques de regex (sur texte normalisé : minuscules, sans accents, ASCII)

const NUM = String.raw`(\d{1,3}(?:[.,\s]\d{3})+|\d+(?:[.,]\d+)?)\s*(k|m|mil+ions?|millions?|thousand|mille|000)?`;
const UNIT = String.raw`(?:\(\s*[\d.,]+\s*[km]?\s*\)\s*)?(?:(?:monetized|monetised|paid|total|spotify|online|audio)\s*)?(streams?|plays?|ecoutes?|listens?|views?|vues?|sales?|ventes?|units?|copies|downloads?|telechargements?)`;
const FFP = String.raw`(?:free|fr33|gratuit|gratos)\s*[-_]?\s*(?:for|4|fo|pour)?\s*[-_]?\s*(?:profit|commercial)`;

const LIMIT_PATTERNS = [
  // up to 5k streams / jusqu'à 10 000 écoutes / max 50k plays / first 100k streams
  new RegExp(String.raw`(?:up\s*-?\s*to|upto|until|till|max(?:imum)?(?:\s*(?:of|de))?|limit(?:ed)?(?:\s*(?:to|of|at|a|de))?|capped?\s*(?:at|to)?|first|jusqu\s*'?\s*(?:a|au)|<=?|maxi)\s*:?\s*${NUM}\s*${UNIT}`, 'g'),
  // 5k streams max / 10.000 streams limit
  new RegExp(String.raw`${NUM}\s*${UNIT}\s*(?:max(?:imum)?|limit|cap|maxi)`, 'g'),
  // after 5k streams you must buy / au-delà de 10k écoutes
  new RegExp(String.raw`(?:after|over|above|beyond|exceed(?:s|ing)?|surpass(?:es|ing)?|reach(?:es|ing)?|hits?|past|apres|au\s*-?\s*dela\s*de|plus\s*de|passe|depasse)\s*${NUM}\s*${UNIT}`, 'g'),
  // free for profit (5k streams) / ffp 10k streams
  new RegExp(String.raw`(?:${FFP}|ffp|f4p)[ \t]*[(\[:\-]?[ \t]*${NUM}[ \t]*${UNIT}`, 'g'),
];

const NEGATION_BEFORE = /(?:\bnot|n't|\bno|\bpas|\bnon|\bnever|\bisnt|\barent|\bwithout)\s*(?:\w+\s*){0,2}$/;
const NEGATION_AFTER = /^\s*[?:\-]*\s*(?:no\b|non\b|nope|❌|✖|✗|x\b)/;

const FFP_STRONG = [
  new RegExp(FFP, 'g'),
  /\bf\s*4\s*p\b/g,
  /\bffp\b/g,
  /free\s*(?:to\s*use\s*)?for\s*commercial\s*use/g,
  /commercial\s*use\s*(?:is\s*)?(?:allowed|ok|free|permitted|authorized)/g,
  /(?:usage|utilisation)\s*commercial(?:e)?\s*(?:autorise|ok|libre|gratuit)/g,
  /free\s*to\s*(?:use|release|monetize|monetise|upload|distribute)\s*(?:it\s*)?(?:on|to|for)\s*(?:spotify|streaming|all\s*platforms|apple\s*music|dsps?|profit)/g,
  /(?:you\s*can|feel\s*free\s*to|allowed\s*to)\s*(?:use|release|upload|monetize|monetise|put|drop)\s*(?:it|this|this\s*beat|the\s*beat|this\s*instrumental)?\s*(?:on|to|for|in)\s*(?:spotify|streaming|all\s*platforms|apple\s*music|commercial|profit|dsps?)/g,
  /(?:tu\s*peux|vous\s*pouvez)\s*(?:l'?\s*)?(?:utiliser|sortir|mettre|publier)[^.\n]{0,30}(?:spotify|streaming|plateformes|commercial)/g,
  /no\s*need\s*to\s*(?:buy|purchase|pay|lease)/g,
  /(?:pas\s*besoin|aucun\s*besoin)\s*d'?\s*(?:acheter|payer)/g,
  /free\s*(?:for\s*)?(?:all|any)\s*(?:uses?|purposes?|platforms?)/g,
  // Spotify ✅ / streaming: yes / ok pour spotify
  /(?:spotify|streaming|all\s*platforms|dsps?)\s*[:\-=]?\s*(?:✅|✔|☑|💯|yes\b|ok\b|allowed|oui\b|autorise)/g,
  /(?:ok|allowed|autorise|good)\s*(?:on|for|to\s*use\s*on|sur|pour)\s*spotify/g,
  // « My beats can be used on all platforms including Spotify »
  /(?:can|may)\s*be\s*used\s*(?:on|for|in)\s*(?:all\s*platforms|any\s*platforms?|spotify|streaming|commercial)/g,
  /(?:use|used)\s*(?:it|them|this\s*beat)?\s*(?:for|in)\s*(?:whatever|any)\s*(?:purpose|project|thing)/g,
  // licence YouTube « Creative Commons Attribution (réutilisation autorisée) »
  /creative\s*commons\s*attribution/g,
];

const FFP_WEAK = [
  /royalty\s*-?\s*free/g,
  /libres?\s*de\s*droits?/g,
  /100\s*%\s*(?:free|gratuit)(?!\s*(?:for\s*)?non)/g,
  /\bfree\s*to\s*use\b|#\s*freetouse/g,
];

const FNP = [
  /(?:free|gratuit)\s*[-_]?\s*(?:for|4|pour)?\s*[-_]?\s*(?:non|not)\s*[-_]?\s*(?:profit|commercial|lucratif)/g,
  /\bfnp\b/g,
  /non\s*-?\s*(?:profit|commercial)\s*(?:use\s*)?only/g,
  /(?:only|uniquement)\s*(?:for\s*|pour\s*)?(?:non\s*-?\s*(?:profit|commercial)|youtube|soundcloud)/g,
  /free\s*(?:for|on)\s*(?:youtube|soundcloud)(?:\s*(?:and|&|\/)\s*(?:youtube|soundcloud))?\s*only/g,
  /not\s*(?:free\s*)?for\s*(?:profit|commercial)/g,
  /(?:pas|non)\s*(?:libre|gratuit)e?\s*(?:pour|en)?\s*(?:usage|utilisation)?\s*commercial/g,
  /usage\s*non\s*-?\s*commercial/g,
];

const BUY_REQUIRED = [
  // must buy a lease to release on spotify
  /(?:must|need\s*to|needs\s*to|have\s*to|has\s*to|required\s*to|require[sd]?|please|should|gotta)\s*(?:to\s*)?(?:buy|purchase|lease|get|acquire|pay\s*for|obtain)[^.\n]{0,70}(?:release|spotify|stream|apple\s*music|commercial|profit|monetiz|monetis|distribut|dsp|sell|platform)/g,
  // to release on spotify, purchase a lease / for profit use buy a license
  /(?:to|for|before|if\s*you\s*(?:want|plan|wish)\s*to)\s*(?:release|upload|put|use|drop|monetiz|monetis|distribut)[^.\n]{0,60}(?:spotify|streaming|platforms|commercial|profit|monetiz|monetis|distribut|dsp)[^.\n]{0,60}(?:buy|purchase|lease|licen[cs]e|pay)/g,
  /(?:for\s*)?(?:profit|commercial)\s*(?:use|purposes?|releases?)\s*[:,\-]?\s*(?:you\s*)?(?:must|need\s*to|have\s*to|please|should)?\s*(?:buy|purchase|lease|get\s*a\s*licen[cs]e)/g,
  /licen[cs]e\s*(?:is\s*)?(?:required|needed|necessary|mandatory)/g,
  /(?:il\s*faut|faut|tu\s*dois|vous\s*devez|obligatoire\s*d'?)\s*(?:l'?\s*)?(?:acheter|payer|louer|prendre\s*une\s*licence)/g,
  /achat\s*(?:de\s*(?:la\s*)?licence\s*)?obligatoire/g,
];

// La description interdit / limite Spotify & co (même si le titre dit « free for profit »)
const SPOTIFY_NO = [
  // Spotify ❌ / streaming: no / apple music - not allowed
  /(?:spotify|streaming|apple\s*music|dsps?|distribution|plateformes?)\s*[:\-=]?\s*(?:❌|✖|✗|⛔|🚫|no\b|nope|non\b|not\s*(?:allowed|permitted|included)|interdit|pas\s*autorise)/g,
  // not allowed on spotify / can't upload to spotify
  /(?:not\s*(?:allowed|permitted)|can'?t|cannot|can\s*not|do\s*not|don'?t|forbidden\s*to)\s*(?:to\s*)?(?:upload\w*|releas\w*|put\w*|us\w*|drop\w*|distribut\w*|moneti[sz]\w*)?\s*(?:it\s*|this\s*(?:beat)?\s*)?(?:on|to|for)\s*(?:spotify|streaming|apple\s*music|dsps?|all\s*platforms)/g,
  // free for profit ... youtube only / ffp (soundcloud only)
  /(?:free\s*(?:for|4)?\s*profit|ffp|f4p)[^.\n]{0,40}(?:youtube|soundcloud|tiktok|instagram)\s*only/g,
  /(?:only|uniquement|seulement)\s*(?:on|for|sur|pour)\s*(?:youtube|soundcloud|tiktok)/g,
  // pas sur spotify / interdit sur spotify
  /(?:pas|interdit|non\s*autorise)\s*(?:de\s*(?:le\s*)?(?:sortir|mettre|publier)\s*)?(?:sur|pour)\s*(?:spotify|les\s*plateformes|le\s*streaming)/g,
  // contact me before releasing on spotify
  /(?:contact|dm|email|e-mail|message|hit\s*me\s*up|hmu)\s*(?:me\s*)?[^.\n]{0,30}(?:before|to|if\s*you\s*want\s*to|avant\s*de)\s*(?:releas|upload|put|drop|us|sortir|publi)\w*[^.\n]{0,30}(?:spotify|streaming|platforms?|apple\s*music|commercial|profit|plateformes)/g,
  // for spotify / apple music you need a lease / pour spotify il faut acheter
  /(?:for|on|to|sur|pour)\s*(?:spotify|apple\s*music|streaming\s*(?:platforms|services|sites)?|dsps?|distrokid|tunecore|digital\s*platforms|les\s*plateformes)[^.\n|]{0,40}(?:need|must|have\s*to|requires?|required|il\s*faut|faut|dois|devez|obligatoire|=|->|→)\s*(?:to\s*)?(?:buy|purchase|get|grab|prendre)?\s*(?:a\s*|an\s*|la\s*|une\s*)?(?:buy|purchase|lease|licen[cs]e|licence|paid|pay|acheter|payer)/g,
  // for streaming platforms buy a lease (impératif, seulement après « for / pour »)
  /(?:for|pour)\s*(?:spotify|apple\s*music|streaming\s*(?:platforms|services|sites)?|dsps?|digital\s*platforms|les\s*plateformes)\s*[,:]?\s*(?:please\s*)?(?:buy|purchase|grab|get|achete|prends)\s*(?:a|an|the|my|une|la)?\s*(?:lease|licen[cs]e|licence)/g,
];

// « no lease needed », « sans licence »… : annule une clause d'achat
const NO_NEED = /no\s*(?:need|lease|licen[cs]e)|without\s*(?:a\s*)?(?:lease|licen[cs]e|buying|paying)|don'?t\s*(?:need|have)\s*to|pas\s*besoin|sans\s*(?:pay|achet|licen|rien\s*payer)|not\s*required|free\s*(?:of\s*charge)?\s*(?:on|for)\s*spotify/;

const FREE_ANY = [
  /\[\s*free\s*\]|\(\s*free\s*\)|\{\s*free\s*\}|「\s*free\s*」/g,
  /\bfree\s*(?:download|dl|beat|instrumental|instru|type\s*beat)\b/g,
  /^\s*free\b/g,
  /\bgratuit(?:e|es|s)?\b/g,
  /\bfree\b/g,
];

const PAID = [
  /\bsold\b|\bvendue?\b|\(\s*sold\s*\)|\[\s*sold\s*\]/g,
  /\b(?:buy|purchase|lease|leasing|exclusive\s*rights?|exclu(?:sive)?|acheter|achat)\b/g,
  /beatstars\.com|bsta\.rs|airbit\.com|traktrain\.com|soundee\.com|beatstore|beat\s*store|player\.beatstars/g,
  /\$\s*\d+|\b\d+(?:[.,]\d{2})?\s*(?:\$|€|usd|eur|euros?)\b/g,
];

const CREDIT = [
  /(?:must|need\s*to|have\s*to|please|you\s*should|required\s*to)\s*(?:give\s*)?credit/g,
  /credit\s*(?:is\s*)?[("'\[]?\s*(?:required|needed|mandatory|me\b|the\s*producer|prod)/g,
  /\b(?:just|simply|only|juste)\s*(?:give\s*)?credit/g,
  /(?:as\s*long\s*as|if|provided)\s*you\s*(?:give\s*(?:me\s*)?|include\s*)?credit/g,
  /credit\s*must\s*be\s*given/g,
  /(?:put|add|include|write|mettre|mets)\s*["'(]?\s*(?:prod\.?|produced)\s*(?:by|par)/g,
  /(?:credit|credits|credite?r?)\s*(?:obligatoire|requis|svp|stp)/g,
  /(?:prod\.?|produced)\s*(?:by|par)\s*@?[\w.\- ]{2,30}\s*(?:in\s*(?:the\s*)?title|dans\s*le\s*titre)/g,
];

const PRICE_RE = /\$\s*\d|\b\d+(?:[.,]\d{2})?\s*(?:\$|€|usd|eur|euros?)\b|€\s*\d/;

// ---------------------------------------------------------------------------

function parseNumber(raw, suffix) {
  let s = raw.trim();
  let value;
  if (/^\d{1,3}(?:[.,\s]\d{3})+$/.test(s)) {
    value = Number(s.replace(/[.,\s]/g, ''));
  } else {
    value = Number(s.replace(',', '.'));
  }
  if (!Number.isFinite(value)) return null;
  const suf = (suffix || '').trim();
  if (suf === 'k' || suf === 'thousand' || suf === 'mille') value *= 1000;
  else if (suf === 'm' || /^mil+ions?$|^millions?$/.test(suf)) value *= 1_000_000;
  else if (suf === '000') value *= 1000;
  return Math.round(value);
}

function unitLabel(u) {
  if (/^(stream|play|ecoute|listen)/.test(u)) return 'streams';
  if (/^(view|vue)/.test(u)) return 'vues';
  if (/^(sale|vente|unit|cop)/.test(u)) return 'ventes';
  if (/^(download|telecharg)/.test(u)) return 'téléchargements';
  return u;
}

function findAll(patterns, text, { skipNegated = false } = {}) {
  const hits = [];
  for (const re of patterns) {
    re.lastIndex = 0;
    let m;
    while ((m = re.exec(text))) {
      if (m[0].length === 0) { re.lastIndex++; continue; }
      const start = m.index;
      const end = start + m[0].length;
      if (skipNegated) {
        const before = text.slice(Math.max(0, start - 25), start);
        const after = text.slice(end, end + 12);
        if (NEGATION_BEFORE.test(before) || NEGATION_AFTER.test(after)) {
          hits.push({ start, end, match: m, negated: true });
          continue;
        }
      }
      hits.push({ start, end, match: m, negated: false });
    }
  }
  hits.sort((a, b) => a.start - b.start);
  return hits;
}

export function formatCount(n) {
  if (n == null) return '';
  if (n >= 1_000_000) return `${+(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1000) return `${+(n / 1000).toFixed(1)}K`;
  return String(n);
}

/** Cherche une limite de streams (« up to 5k streams »). */
export function findStreamLimit(text) {
  const found = [];
  for (const re of LIMIT_PATTERNS) {
    re.lastIndex = 0;
    let m;
    while ((m = re.exec(text))) {
      const value = parseNumber(m[1], m[2]);
      if (value == null || value < 100) continue;
      // Une ligne avec un prix = un palier de lease payant (MP3 lease 29$ : 10k streams),
      // pas une limite gratuite.
      const lineStart = text.lastIndexOf('\n', m.index) + 1;
      let lineEnd = text.indexOf('\n', m.index);
      if (lineEnd === -1) lineEnd = text.length;
      const line = text.slice(lineStart, lineEnd);
      if (PRICE_RE.test(line) || /\b(?:mp3|wav|trackouts?|stems|premium|basic|unlimited)\s*(?:lease|licen[cs]e)/.test(line)) continue;
      found.push({ value, unit: unitLabel(m[3]), start: m.index, end: m.index + m[0].length });
    }
  }
  if (!found.length) return null;
  // On préfère une limite en streams (c'est ce qui compte pour Spotify).
  const streams = found.filter((f) => f.unit === 'streams');
  const pool = streams.length ? streams : found;
  pool.sort((a, b) => a.start - b.start);
  return pool[0];
}

/**
 * Analyse complète.
 * Principe : la DESCRIPTION fait foi. Le titre « free for profit » ne compte
 * que si la description ne dit pas le contraire (payer pour Spotify, YouTube
 * only, Spotify ❌…). Dans ce cas la prod est marquée « titre trompeur ».
 */
export function analyzeLicense(title = '', description = '') {
  const full = `${title}\n${description}`;
  const norm = normalizeWithMap(full);
  const t = norm.text;
  const titleLen = normalizeWithMap(title).text.length;
  const inTitle = (h) => h.start < titleLen;
  const inDesc = (h) => h.start > titleLen;
  const reasons = [];
  const quote = (h) => snippet(norm, h.start, h.end);
  const hasDescription = description.trim().length > 0;

  const ffpHitsAll = findAll(FFP_STRONG, t, { skipNegated: true });
  const ffpHits = ffpHitsAll.filter((h) => !h.negated);
  const ffpNegated = ffpHitsAll.filter((h) => h.negated);
  const ffpWeak = findAll(FFP_WEAK, t);
  const fnpHits = findAll(FNP, t);
  // On regarde aussi un peu après la clause : « …sur Spotify sans payer ».
  const noNeed = (h) => NO_NEED.test(t.slice(Math.max(0, h.start - 12), h.end + 25));
  const buyHits = findAll(BUY_REQUIRED, t).filter((h) => !noNeed(h));
  // « can't upload to Spotify without a lease » : la négation confirme la restriction.
  const spotifyNo = findAll(SPOTIFY_NO, t).filter((h) => /not|n't|cannot|forbidden|interdit|pas|❌|✖|✗|⛔|🚫/.test(h.match[0]) || !noNeed(h));
  const limit = findStreamLimit(t);
  const creditHits = findAll(CREDIT, t);
  const paidHits = findAll(PAID, t);
  const soldInTitle = paidHits.some((h) => inTitle(h) && /sold|vendu/.test(h.match[0]));

  // Ce qui restreint l'usage commercial (surtout dans la description)
  const restrict = [...spotifyNo, ...buyHits, ...fnpHits].sort((a, b) => a.start - b.start);
  const ffpTitle = ffpHits.filter(inTitle);
  const ffpDesc = ffpHits.filter(inDesc);

  // Les mentions « free » qui ne sont pas déjà des free for profit / non profit
  const covered = [...ffpHitsAll, ...fnpHits];
  const freeHits = findAll(FREE_ANY, t).filter(
    (h) => !covered.some((c) => h.start >= c.start && h.start < c.end),
  );

  const creditRequired = creditHits.length > 0;
  let category = 'unknown';
  let confidence = 'faible';
  let limitValue = null;
  let limitUnit = null;

  if (soldInTitle) {
    category = 'paid';
    confidence = 'haute';
    reasons.push({ text: 'Prod marquée « SOLD » / vendue dans le titre.', quote: quote(paidHits.find(inTitle)) });
  } else if (ffpNegated.length && !ffpHits.length) {
    category = freeHits.length || fnpHits.length ? 'fnp' : 'paid';
    confidence = 'haute';
    reasons.push({ text: 'La description dit explicitement que ce n’est PAS free for profit.', quote: quote(ffpNegated[0]) });
  } else if (limit && (ffpHits.length || ffpWeak.length || (freeHits.length && !fnpHits.length))) {
    category = 'upto';
    confidence = ffpHits.length ? 'haute' : 'moyenne';
    limitValue = limit.value;
    limitUnit = limit.unit;
    if (ffpHits.length) reasons.push({ text: 'Mention free for profit trouvée.', quote: quote(ffpHits[0]) });
    reasons.push({
      text: `Limite détectée dans la description : gratuit jusqu’à ${formatCount(limit.value)} ${limit.unit}, ensuite il faut une licence.`,
      quote: quote(limit),
    });
  } else if ((ffpHits.length || ffpWeak.length) && restrict.length) {
    // « Free for profit » annoncé, mais la description exige de payer pour
    // Spotify / le limite à YouTube : la clause restrictive l'emporte.
    category = 'fnp';
    confidence = 'haute';
    const claim = ffpHits[0] || ffpWeak[0];
    reasons.push({ text: `${inTitle(claim) ? 'Le titre' : 'La description'} annonce « free for profit »…`, quote: quote(claim) });
    reasons.push({ text: '…mais la description dit qu’il faut payer / qu’il n’est pas libre pour Spotify & co.', quote: quote(restrict[0]) });
  } else if (ffpHits.length) {
    category = 'ffp';
    if (ffpDesc.length) {
      confidence = 'haute';
      reasons.push({ text: 'La description confirme : free for profit / usage commercial libre.', quote: quote(ffpDesc[0]) });
      if (ffpTitle.length) reasons.push({ text: 'Le titre dit la même chose.', quote: quote(ffpTitle[0]) });
    } else {
      confidence = 'moyenne';
      reasons.push({ text: '« Free for profit » dans le titre.', quote: quote(ffpTitle[0]) });
      reasons.push({
        text: hasDescription
          ? 'La description ne le confirme pas, mais ne demande pas non plus de payer. Vérifie avant de sortir le son.'
          : 'Description vide : rien pour confirmer. Vérifie avant de sortir le son.',
        quote: '',
      });
    }
    reasons.push({ text: 'Aucune clause « payer pour Spotify » trouvée dans la description.', quote: '' });
  } else if (restrict.length) {
    category = fnpHits.length || freeHits.length || ffpWeak.length ? 'fnp' : 'paid';
    confidence = fnpHits.length || spotifyNo.length ? 'haute' : 'moyenne';
    if (fnpHits.length) reasons.push({ text: 'Gratuit seulement pour un usage non-commercial.', quote: quote(fnpHits[0]) });
    const pay = [...spotifyNo, ...buyHits].sort((a, b) => a.start - b.start)[0];
    if (pay) reasons.push({ text: 'Il faut payer une licence pour sortir le son (Spotify, streaming…).', quote: quote(pay) });
  } else if (ffpWeak.length) {
    category = 'ffp';
    confidence = 'moyenne';
    reasons.push({ text: 'Mention « libre de droits » / « 100% free » (moins explicite que « free for profit »).', quote: quote(ffpWeak[0]) });
  } else if (freeHits.length) {
    category = 'fnp';
    confidence = 'faible';
    reasons.push({
      text: '« FREE » sans préciser « for profit » : par convention, c’est gratuit pour un usage non-commercial seulement.',
      quote: quote(freeHits[0]),
    });
  } else if (paidHits.length) {
    category = 'paid';
    confidence = 'moyenne';
    reasons.push({ text: 'Lien d’achat / prix / lease sans aucune mention de gratuité.', quote: quote(paidHits[0]) });
  } else {
    reasons.push({ text: 'Aucune info de licence trouvée dans le titre ni la description.', quote: '' });
  }

  if (creditRequired) {
    reasons.push({ text: 'Crédit du producteur obligatoire (ex. « prod. by … » dans le titre).', quote: quote(creditHits[0]) });
  }

  // Titre trompeur : « free for profit » dans le titre, mais la description dit autre chose.
  const misleading = ffpTitle.length > 0 && !['ffp', 'upto'].includes(category);

  const cat = CATEGORIES[category];
  return {
    category,
    label: category === 'upto' ? `Up to ${formatCount(limitValue)} ${limitUnit}` : cat.label,
    limit: limitValue,
    limitUnit,
    spotify: cat.spotify,
    creditRequired,
    confidence,
    misleading,
    descriptionChecked: hasDescription,
    reasons,
  };
}

// ---------------------------------------------------------------------------
// Infos clés : les lignes de la description qui parlent de droits, crédit,
// tempo, contact… (pour ne pas avoir à lire tout le pavé).

const KEY_LINE_TYPES = [
  { type: 'licence', re: /spotify|stream|profit|lease|licen[cs]e|licence|commercial|monetiz|monetis|royalty|droits?|purchase|buy\b|acheter|payer|free|gratuit|sold|exclusive|apple\s*music|distrib|youtube\s*only|soundcloud\s*only|untagged/ },
  { type: 'credit', re: /credit|prod\.?\s*(?:by|par)|produced\s*by|tag\b/ },
  { type: 'tempo', re: /\bbpm\b|tempo|\bkey\b|tonalite|scale|\b[a-g](?:#|b)?\s*(?:minor|major|min|maj)\b/ },
  { type: 'contact', re: /contact|e-?mail|@[a-z0-9._-]+\.[a-z]{2,}|business|dm\b|instagram|insta\b/ },
];

export function extractKeyLines(description = '', max = 8) {
  const out = [];
  const seen = new Set();
  for (const raw of String(description).split(/\r?\n/)) {
    const line = raw.trim();
    if (line.length < 3) continue;
    const n = normalizeWithMap(line).text;
    if (/^#\S+(\s+#\S+)*$/.test(n)) continue; // lignes de hashtags
    const hit = KEY_LINE_TYPES.find((k) => k.re.test(n));
    if (!hit || seen.has(n)) continue;
    seen.add(n);
    out.push({ type: hit.type, text: line.length > 220 ? `${line.slice(0, 217)}…` : line });
    if (out.length >= max) break;
  }
  return out;
}
