// Source « sans clé » : lit directement les pages publiques de YouTube.
// 1) page de résultats → liste des vidéos
// 2) page de chaque vidéo → description complète (shortDescription)
//
// Pas besoin de clé, mais plus lent et dépend du format des pages YouTube
// (qui peut changer). Si ça casse, mets une clé API (voir README).

import { extractJsonAfter, parseViews, parseClock, pMap } from './util.js';

const HEADERS = {
  'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36',
  'Accept-Language': 'en-US,en;q=0.9',
  // Évite la page de consentement cookies (UE).
  Cookie: 'CONSENT=YES+cb.20240101-00-p0.en+FX+000; SOCS=CAI',
};

async function getHtml(url) {
  const res = await fetch(url, { headers: HEADERS, redirect: 'follow' });
  if (!res.ok) throw new Error(`YouTube a répondu ${res.status}`);
  return res.text();
}

const text = (o) => o?.simpleText ?? (o?.runs || []).map((r) => r.text).join('') ?? '';

/** Parcourt ytInitialData et récupère tous les videoRenderer. */
export function collectVideoRenderers(node, out = []) {
  if (!node || typeof node !== 'object') return out;
  if (Array.isArray(node)) {
    for (const n of node) collectVideoRenderers(n, out);
    return out;
  }
  if (node.videoRenderer?.videoId) out.push(node.videoRenderer);
  for (const k of Object.keys(node)) {
    if (k !== 'videoRenderer') collectVideoRenderers(node[k], out);
  }
  return out;
}

export function parseSearchPage(html) {
  const data = extractJsonAfter(html, 'ytInitialData');
  if (!data) throw new Error('Impossible de lire la page de résultats YouTube (format changé ou page de consentement).');
  return collectVideoRenderers(data).map((v) => ({
    id: v.videoId,
    title: text(v.title),
    channel: text(v.ownerText || v.longBylineText || v.shortBylineText),
    views: parseViews(text(v.viewCountText)),
    publishedText: text(v.publishedTimeText),
    duration: parseClock(text(v.lengthText)),
    description: (v.detailedMetadataSnippets?.[0]?.snippetText ? text(v.detailedMetadataSnippets[0].snippetText) : text(v.descriptionSnippet)) || '',
  }));
}

export function parseWatchPage(html) {
  const player = extractJsonAfter(html, 'ytInitialPlayerResponse');
  const vd = player?.videoDetails;
  if (!vd) return null;
  const micro = player?.microformat?.playerMicroformatRenderer || {};
  return {
    id: vd.videoId,
    title: vd.title || '',
    description: vd.shortDescription || '',
    channel: vd.author || '',
    channelId: vd.channelId || '',
    views: vd.viewCount ? Number(vd.viewCount) : null,
    duration: vd.lengthSeconds ? Number(vd.lengthSeconds) : null,
    tags: vd.keywords || [],
    publishedAt: micro.publishDate || micro.uploadDate || null,
    fullDescription: true,
  };
}

export function createScrapeProvider() {
  return {
    name: 'scrape',
    label: 'Pages YouTube (sans clé)',
    async search(q, max = 20) {
      const url = `https://www.youtube.com/results?search_query=${encodeURIComponent(q)}&sp=EgIQAQ%253D%253D&hl=en`;
      const html = await getHtml(url);
      return parseSearchPage(html).slice(0, max);
    },
    async details(ids) {
      const out = new Map();
      const pages = await pMap(ids, async (id) => parseWatchPage(await getHtml(`https://www.youtube.com/watch?v=${id}&hl=en`)), 6);
      pages.forEach((p, i) => {
        if (p && !p.error) out.set(ids[i], p);
      });
      return out;
    },
  };
}
