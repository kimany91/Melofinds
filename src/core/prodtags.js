// Étiquettes d'une prod (onglet Téléphone) : rappeurs « type beat », courants et ambiances,
// tirés du titre et de la description. Elles s'affichent sur la prod et servent à chercher.

import { findArtists } from './artistmatch.js';
import { classifyStyles, classifyMoods } from './planner.js';
import { MOODS } from './genres.js';

/** [« Luther type beat », « Drill », « Énergique », …] (10 au plus, sans doublon). */
export function prodTags({ title = '', description = '', bpm = null } = {}) {
  const t = String(title || '');
  const d = String(description || '');
  const out = [];
  const add = (x) => { const k = String(x || '').trim(); if (k && !out.some((o) => o.toLowerCase() === k.toLowerCase())) out.push(k); };
  // rappeurs cités dans le titre (« Ninho x Tiakola Type Beat ») : seulement ceux reconnus sûrement
  for (const a of findArtists(t).filter((x) => x.exact).slice(0, 3)) add(`${a.name} type beat`);
  for (const s of classifyStyles(t, d)) add(s.label);
  for (const id of classifyMoods(t, d)) add(MOODS[id]?.label);
  const n = Number(bpm);
  if (n >= 150 && !out.includes(MOODS.fast.label) && !out.includes(MOODS.slow.label)) add(MOODS.fast.label);
  if (n > 0 && n <= 85 && !out.includes(MOODS.slow.label) && !out.includes(MOODS.fast.label)) add(MOODS.slow.label);
  return out.slice(0, 10);
}
