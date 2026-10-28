// Extraction du BPM et de la tonalité depuis le titre / la description.

import { normalize } from './text.js';

const BPM_PATTERNS = [
  /(?:^|[^\d])(\d{2,3})\s*-?\s*bpm\b/g, // 140 bpm, 140bpm, @140bpm
  /\bbpm\s*[:=\-|]?\s*(\d{2,3})\b/g, // bpm: 140
  /\btempo\s*[:=\-|]?\s*(\d{2,3})\b/g, // tempo 140
];

const KEY_PATTERNS = [
  /\b(?:key|tonalite|cle|scale)\s*[:=\-|]?\s*([a-g])\s*(#|b|♯|♭|sharp|flat)?\s*(minor|min|major|maj|mineur|majeur|m)?(?![a-z])/g,
  /(?:^|[\s|•·,/(\[-])([a-g])\s*(#|♯|b|♭)?\s*(minor|major|min|maj|mineur|majeur)\b/g,
];
// Collée au BPM : « 140bpm C#m », « 140 BPM | Gm », « C#m 140 BPM ». Lue dans le texte brut :
// la note doit être en majuscule et le mode écrit (« 150 BPM am I right » n'est pas une clé).
const KEY_NEAR_BPM = [
  /\d{2,3}\s*-?\s*bpm\s*[|,/•·–-]*\s*([a-g])(#|♯|b|♭)?\s?(minor|major|min|maj|mineur|majeur|m)(?![a-z])/gi,
  /(?:^|[\s|•·,/(\[-])([a-g])(#|♯|b|♭)?\s?(minor|major|min|maj|mineur|majeur|m)\s*[|,/•·–-]*\s*\d{2,3}\s*-?\s*bpm/gi,
];
// « 🔑 C#m », « 🎹 Gm », « 🎼 F# minor » (avant la mise en forme du texte, qui enlève les émojis)
const KEY_EMOJI = /(?:🔑|🗝️?|🎹|🎼)\s*(?:key\s*[:=\-|]?\s*)?([A-Ga-g])\s*(#|♯|b|♭)?\s*(minor|major|min|maj|mineur|majeur|m)?(?![a-z])/i;

function toBpm(raw) {
  const n = Number(raw);
  return n >= 50 && n <= 220 ? n : null;
}

/** Renvoie le BPM trouvé (le titre est prioritaire), ou null. */
export function extractBpm(title = '', description = '') {
  for (const src of [title, description]) {
    const t = normalize(src);
    for (const re of BPM_PATTERNS) {
      re.lastIndex = 0;
      let m;
      while ((m = re.exec(t))) {
        const bpm = toBpm(m[1]);
        if (bpm) return bpm;
      }
    }
  }
  return null;
}

function formatKey(note, acc, mode) {
  let a = '';
  if (acc === '#' || acc === '♯' || acc === 'sharp') a = '#';
  else if (acc === 'b' || acc === '♭' || acc === 'flat') a = 'b';
  let md = '';
  if (mode && /^(m|min|minor|mineur)$/.test(mode)) md = ' min';
  else if (mode && /^(maj|major|majeur)$/.test(mode)) md = ' maj';
  return `${note.toUpperCase()}${a}${md}`;
}

/** Renvoie la tonalité (ex. « C# min »), ou null. */
export function extractKey(title = '', description = '') {
  for (const src of [title, description]) {
    const e = KEY_EMOJI.exec(String(src || ''));
    if (e && (e[2] || e[3] || /key/i.test(e[0]))) return formatKey(e[1].toLowerCase(), e[2], e[3]?.toLowerCase());
    const t = normalize(src);
    for (const re of KEY_PATTERNS) {
      re.lastIndex = 0;
      const m = re.exec(t);
      if (m) return formatKey(m[1], m[2], m[3]);
    }
    for (const re of KEY_NEAR_BPM) {
      re.lastIndex = 0;
      let m;
      while ((m = re.exec(String(src || '')))) {
        if (m[1] === m[1].toUpperCase()) return formatKey(m[1].toLowerCase(), m[2], m[3].toLowerCase());
      }
    }
  }
  return null;
}
