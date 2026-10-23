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
    const t = normalize(src);
    for (const re of KEY_PATTERNS) {
      re.lastIndex = 0;
      const m = re.exec(t);
      if (m) return formatKey(m[1], m[2], m[3]);
    }
  }
  return null;
}
