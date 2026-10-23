// Source « API officielle » : YouTube Data API v3 (clé gratuite sur
// console.cloud.google.com). search.list trouve les vidéos, puis videos.list
// récupère la description COMPLÈTE (search.list ne renvoie qu'un extrait).
//
// Quota : 10 000 unités / jour. Une requête de recherche coûte 100 unités,
// la lecture des descriptions 1 unité par paquet de 50 vidéos.

import { parseIsoDuration } from './util.js';

const BASE = 'https://www.googleapis.com/youtube/v3';

async function call(path, params, key) {
  const url = new URL(`${BASE}/${path}`);
  for (const [k, v] of Object.entries({ ...params, key })) url.searchParams.set(k, v);
  const res = await fetch(url, { headers: { Accept: 'application/json' } });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const reason = body?.error?.errors?.[0]?.reason || '';
    if (reason === 'quotaExceeded' || reason === 'dailyLimitExceeded') {
      throw new Error('Quota YouTube API épuisé pour aujourd’hui (10 000 unités/jour). Réessaie demain ou passe en recherche sans clé.');
    }
    if (reason === 'keyInvalid' || res.status === 400 && /API key/i.test(body?.error?.message || '')) {
      throw new Error('Clé YouTube API invalide.');
    }
    throw new Error(`YouTube API ${res.status} : ${body?.error?.message || res.statusText}`);
  }
  return body;
}

export function createApiProvider(key) {
  return {
    name: 'api',
    label: 'YouTube Data API',
    async search(q, max = 20) {
      const body = await call('search', {
        part: 'snippet',
        type: 'video',
        maxResults: String(Math.min(50, max)),
        q,
        safeSearch: 'none',
      }, key);
      return (body.items || [])
        .filter((it) => it.id?.videoId)
        .map((it) => ({
          id: it.id.videoId,
          title: decodeEntities(it.snippet?.title || ''),
          channel: it.snippet?.channelTitle || '',
          publishedAt: it.snippet?.publishedAt || null,
          description: it.snippet?.description || '',
        }));
    },
    async details(ids) {
      const out = new Map();
      for (let i = 0; i < ids.length; i += 50) {
        const chunk = ids.slice(i, i + 50);
        const body = await call('videos', { part: 'snippet,contentDetails,statistics', id: chunk.join(','), maxResults: '50' }, key);
        for (const v of body.items || []) {
          out.set(v.id, {
            id: v.id,
            title: v.snippet?.title || '',
            description: v.snippet?.description || '',
            channel: v.snippet?.channelTitle || '',
            channelId: v.snippet?.channelId || '',
            publishedAt: v.snippet?.publishedAt || null,
            tags: v.snippet?.tags || [],
            duration: parseIsoDuration(v.contentDetails?.duration),
            views: v.statistics?.viewCount ? Number(v.statistics.viewCount) : null,
            fullDescription: true,
          });
        }
      }
      return out;
    },
  };
}

function decodeEntities(s) {
  return s
    .replace(/&amp;/g, '&')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>');
}
