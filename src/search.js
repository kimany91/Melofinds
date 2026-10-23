// Orchestration : plan → requêtes YouTube → lecture des descriptions → analyse.

import { buildPlan } from './core/planner.js';
import { analyzeVideo } from './core/analyze.js';
import { CATEGORY_ORDER } from './core/license.js';
import { pMap, TtlCache, thumb } from './youtube/util.js';

const searchCache = new TtlCache(6 * 3600 * 1000); // 6 h
const detailCache = new TtlCache(24 * 3600 * 1000); // 24 h

/**
 * @param {{prompt, manualQuery, licenses, device, depth}} params
 * @param {{name, search(q,max), details(ids)}} provider
 */
export async function runSearch(params, provider) {
  const started = Date.now();
  const plan = buildPlan(params.prompt || '', params);
  const warnings = [...plan.notes];
  const device = plan.device;

  if (!plan.queries.length) {
    return { plan, source: provider.name, results: [], warnings: ['Rien à chercher : écris une description ou une recherche directe.'], stats: {} };
  }

  // 1) Lancer les requêtes « type beat »
  const perQuery = plan.depth.perQuery;
  const lists = await pMap(plan.queries, async ({ q }) => {
    const ck = `${provider.name}|${q}|${perQuery}`;
    const hit = searchCache.get(ck);
    if (hit) return hit;
    const res = await provider.search(q, perQuery);
    searchCache.set(ck, res);
    return res;
  }, 3);

  const merged = new Map();
  lists.forEach((list, i) => {
    const q = plan.queries[i].q;
    if (list?.error) {
      warnings.push(`Requête « ${q} » en échec : ${list.error.message}`);
      plan.queries[i].count = 0;
      plan.queries[i].error = list.error.message;
      return;
    }
    plan.queries[i].count = list.length;
    list.forEach((v, rank) => {
      const cur = merged.get(v.id);
      if (cur) {
        cur.foundBy.push(q);
        cur.bestRank = Math.min(cur.bestRank, rank);
      } else {
        merged.set(v.id, { ...v, foundBy: [q], bestRank: rank });
      }
    });
  });

  if (lists.every((l) => l?.error)) {
    const msg = lists[0].error.message;
    const err = new Error(msg);
    err.status = 502;
    throw err;
  }

  // On garde d'abord les vidéos trouvées par plusieurs requêtes / bien classées.
  let candidates = [...merged.values()]
    .sort((a, b) => b.foundBy.length - a.foundBy.length || a.bestRank - b.bestRank)
    .slice(0, plan.depth.maxVideos);

  // 2) Lire la description COMPLÈTE de chaque vidéo
  const missing = candidates.map((c) => c.id).filter((id) => !detailCache.get(`${provider.name}|${id}`));
  let partial = 0;
  if (missing.length) {
    try {
      const details = await provider.details(missing);
      for (const [id, d] of details) detailCache.set(`${provider.name}|${id}`, d);
    } catch (err) {
      warnings.push(`Lecture des descriptions incomplète : ${err.message}`);
    }
  }
  candidates = candidates.map((c) => {
    const d = detailCache.get(`${provider.name}|${c.id}`);
    if (!d) partial++;
    return { ...c, ...(d || {}), foundBy: c.foundBy, fullDescription: !!d?.fullDescription };
  });
  if (partial) warnings.push(`${partial} vidéo(s) analysée(s) avec un extrait de description seulement.`);

  // 3) Analyse : licence, BPM, tonalité, courants, pertinence
  const results = candidates.map((c) => {
    const r = analyzeVideo(c, plan);
    return {
      id: r.id,
      title: r.title,
      channel: r.channel,
      description: r.description,
      fullDescription: r.fullDescription,
      views: r.views ?? null,
      duration: r.duration ?? null,
      publishedAt: r.publishedAt || null,
      publishedText: r.publishedText || null,
      thumbnail: r.demo ? null : thumb(r.id, device),
      url: r.demo ? null : `https://www.youtube.com/watch?v=${r.id}`,
      demo: !!r.demo,
      foundBy: r.foundBy,
      license: r.license,
      bpm: r.bpm,
      key: r.key,
      styles: r.styles,
      moods: r.moods,
      isBeat: r.isBeat,
      score: r.score,
    };
  });

  const counts = Object.fromEntries(CATEGORY_ORDER.map((c) => [c, 0]));
  for (const r of results) if (r.isBeat) counts[r.license.category]++;

  return {
    plan,
    source: provider.name,
    sourceLabel: provider.label,
    results,
    warnings,
    stats: {
      queries: plan.queries.length,
      found: merged.size,
      analysed: results.length,
      notBeats: results.filter((r) => !r.isBeat).length,
      withBpm: results.filter((r) => r.bpm).length,
      counts,
      ms: Date.now() - started,
    },
  };
}
