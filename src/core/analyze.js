// Analyse d'une vidéo : licence, BPM, tonalité, courants, pertinence.

import { analyzeLicense, extractKeyLines } from './license.js';
import { extractBpm, extractKey } from './bpm.js';
import { classifyStyles, classifyMoods } from './planner.js';
import { normalize, hasWord } from './text.js';

const BEAT_WORDS = /\b(type\s*beat|beat|beats|instrumental|instru|prod\.?|produced\s*by|free\s*for\s*profit|bpm|riddim|instrumentale)\b/;

/** Une prod, ou un vrai morceau / un clip / une vidéo hors sujet ? */
export function looksLikeBeat(title = '', description = '') {
  const t = normalize(title);
  if (BEAT_WORDS.test(t)) return true;
  const d = normalize(description).slice(0, 400);
  return /\b(type\s*beat|instrumental|free\s*for\s*profit|bpm)\b/.test(d);
}

/**
 * @param {object} video  {id, title, description, channel, views, publishedAt, ...}
 * @param {object} plan   plan renvoyé par buildPlan
 */
export function analyzeVideo(video, plan) {
  const title = video.title || '';
  const description = video.description || '';
  const license = analyzeLicense(title, description);
  const bpm = extractBpm(title, description);
  const key = extractKey(title, description);
  const styles = classifyStyles(title, description);
  const moods = classifyMoods(title, description);
  const isBeat = looksLikeBeat(title, description);

  // --- Pertinence
  let score = 0;
  const nt = normalize(title);
  score += (video.foundBy?.length || 1) * 10;
  if (plan) {
    if (plan.artists.some((a) => hasWord(nt, normalize(a.name)))) score += 8;
    if (styles.some((s) => plan.genres.some((g) => g.id === s.id))) score += 6;
    const wanted = new Set(plan.moods.map((m) => m.id));
    score += moods.filter((m) => wanted.has(m)).length * 3;
    if (bpm && plan.bpmRange) {
      if (bpm >= plan.bpmRange.min && bpm <= plan.bpmRange.max) score += 6;
      else score -= 3;
    }
  }
  if (license.confidence === 'haute') score += 4;
  if (video.views) score += Math.min(8, Math.log10(video.views + 1) * 1.3);
  if (!isBeat) score -= 30;

  const keyLines = extractKeyLines(description);
  return { ...video, license, bpm, key, styles, moods, isBeat, keyLines, score: Math.round(score * 10) / 10 };
}
