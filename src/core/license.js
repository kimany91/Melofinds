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
const UNIT = String.raw`(streams?|plays?|ecoutes?|listens?|views?|vues?|sales?|ventes?|units?|copies|downloads?|telechargements?)`;
const FFP = String.raw`(?:free|fr33|gratuit|gratos)\s*[-_]?\s*(?:for|4|fo|pour)?\s*[-_]?\s*(?:profit|commercial)`;

const LIMIT_PATTERNS = [
  // up to 5k streams / jusqu'à 10 000 écoutes / max 50k plays / first 100k streams
  new RegExp(String.raw`(?:up\s*-?\s*to|upto|until|till|max(?:imum)?|limit(?:ed)?(?:\s*(?:to|of|at|a|de))?|capped?\s*(?:at|to)?|first|jusqu\s*'?\s*(?:a|au)|<=?|maxi)\s*:?\s*${NUM}\s*${UNIT}`, 'g'),
  // 5k streams max / 10.000 streams limit
  new RegExp(String.raw`${NUM}\s*${UNIT}\s*(?:max(?:imum)?|limit|cap|maxi)`, 'g'),
  // after 5k streams you must buy / au-delà de 10k écoutes
  new RegExp(String.raw`(?:after|over|above|beyond|exceed(?:ing)?|past|apres|au\s*-?\s*dela\s*de|plus\s*de|passe)\s*${NUM}\s*${UNIT}`, 'g'),
  // free for profit (5k streams) / ffp 10k streams
  new RegExp(String.raw`(?:${FFP}|ffp|f4p)\s*[(\[:\-]?\s*${NUM}\s*${UNIT}`, 'g'),
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
];

const FFP_WEAK = [
  /royalty\s*-?\s*free/g,
  /libres?\s*de\s*droits?/g,
  /100\s*%\s*(?:free|gratuit)(?!\s*(?:for\s*)?non)/g,
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
 * @returns {{category, label, limit, limitUnit, spotify, creditRequired, confidence, reasons: {text, quote}[]}}
 */
export function analyzeLicense(title = '', description = '') {
  const full = `${title}\n${description}`;
  const norm = normalizeWithMap(full);
  const t = norm.text;
  const titleLen = normalizeWithMap(title).text.length;
  const reasons = [];
  const quote = (h) => snippet(norm, h.start, h.end);

  const ffpHitsAll = findAll(FFP_STRONG, t, { skipNegated: true });
  const ffpHits = ffpHitsAll.filter((h) => !h.negated);
  const ffpNegated = ffpHitsAll.filter((h) => h.negated);
  const ffpWeak = findAll(FFP_WEAK, t);
  const fnpHits = findAll(FNP, t);
  const buyHits = findAll(BUY_REQUIRED, t);
  const limit = findStreamLimit(t);
  const creditHits = findAll(CREDIT, t);
  const paidHits = findAll(PAID, t);
  const soldInTitle = paidHits.some((h) => h.start < titleLen && /sold|vendu/.test(h.match[0]));

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
    reasons.push({ text: 'Prod marquée « SOLD » / vendue dans le titre.', quote: quote(paidHits.find((h) => h.start < titleLen)) });
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
      text: `Limite détectée : gratuit jusqu’à ${formatCount(limit.value)} ${limit.unit}, ensuite il faut une licence.`,
      quote: quote(limit),
    });
  } else if (ffpHits.length && buyHits.length) {
    // « Free for profit » mais la description exige un achat pour sortir le son :
    // la clause d'achat est plus précise, elle l'emporte.
    category = 'fnp';
    confidence = 'moyenne';
    reasons.push({ text: 'Le titre/la description dit « free for profit »…', quote: quote(ffpHits[0]) });
    reasons.push({ text: '…mais il faut quand même acheter une licence pour sortir le son sur les plateformes.', quote: quote(buyHits[0]) });
  } else if (ffpHits.length) {
    category = 'ffp';
    confidence = 'haute';
    reasons.push({ text: 'Mention free for profit / usage commercial libre.', quote: quote(ffpHits[0]) });
    if (ffpHits.length > 1) reasons.push({ text: `${ffpHits.length} mentions au total, aucune clause d’achat obligatoire pour sortir le son.`, quote: '' });
  } else if (fnpHits.length || buyHits.length) {
    category = fnpHits.length || freeHits.length || ffpWeak.length ? 'fnp' : 'paid';
    confidence = fnpHits.length ? 'haute' : 'moyenne';
    if (fnpHits.length) reasons.push({ text: 'Gratuit seulement pour un usage non-commercial.', quote: quote(fnpHits[0]) });
    if (buyHits.length) reasons.push({ text: 'Il faut acheter une licence pour sortir le son (Spotify, streaming…).', quote: quote(buyHits[0]) });
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

  const cat = CATEGORIES[category];
  return {
    category,
    label: category === 'upto' ? `Up to ${formatCount(limitValue)} ${limitUnit}` : cat.label,
    limit: limitValue,
    limitUnit,
    spotify: cat.spotify,
    creditRequired,
    confidence,
    reasons,
  };
}
