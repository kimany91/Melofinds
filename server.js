// Serveur Melofinds : sert l'interface et l'API de recherche.
//   node server.js            → recherche réelle (clé API si YOUTUBE_API_KEY, sinon sans clé)
//   MELOFINDS_DEMO=1 node …   → prods fictives (pour tester sans YouTube)

import http from 'node:http';
import { readFile, stat } from 'node:fs/promises';
import { extname, join, normalize as normPath, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import { runSearch } from './src/search.js';
import { createApiProvider } from './src/youtube/api.js';
import { createScrapeProvider } from './src/youtube/scrape.js';
import { createDemoProvider } from './src/youtube/demo.js';

const ROOT = fileURLToPath(new URL('.', import.meta.url));
const PORT = Number(process.env.PORT) || 3000;
const HOST = process.env.HOST || '0.0.0.0';
const ENV_KEY = process.env.YOUTUBE_API_KEY || '';
const FORCE_DEMO = process.env.MELOFINDS_DEMO === '1';

// URL publique → dossier sur le disque
const STATIC = [
  ['/core/', join(ROOT, 'src/core')],
  ['/', join(ROOT, 'public')],
];

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.ico': 'image/x-icon',
  '.webmanifest': 'application/manifest+json',
};

function sendJson(res, status, body) {
  res.writeHead(status, { 'Content-Type': MIME['.json'], 'Cache-Control': 'no-store' });
  res.end(JSON.stringify(body));
}

function detectDevice(req, asked) {
  if (asked === 'mobile' || asked === 'desktop') return asked;
  const ua = req.headers['user-agent'] || '';
  if (req.headers['sec-ch-ua-mobile'] === '?1' || /Mobi|Android|iPhone|iPad|iPod/i.test(ua)) return 'mobile';
  return 'desktop';
}

function pickProvider(req, body) {
  if (FORCE_DEMO || body.source === 'demo') return createDemoProvider();
  const key = String(req.headers['x-youtube-key'] || '').trim() || ENV_KEY;
  if (key && body.source !== 'scrape') return createApiProvider(key);
  return createScrapeProvider();
}

async function readBody(req, limit = 64 * 1024) {
  let size = 0;
  const chunks = [];
  for await (const c of req) {
    size += c.length;
    if (size > limit) throw Object.assign(new Error('Requête trop grosse'), { status: 413 });
    chunks.push(c);
  }
  const raw = Buffer.concat(chunks).toString('utf8');
  return raw ? JSON.parse(raw) : {};
}

const ALLOWED_LICENSES = new Set(['ffp', 'upto', 'fnp', 'paid', 'unknown']);

async function handleSearch(req, res) {
  let body;
  try {
    body = await readBody(req);
  } catch (err) {
    return sendJson(res, err.status || 400, { error: 'Corps de requête invalide.' });
  }
  const params = {
    prompt: String(body.prompt || '').slice(0, 500),
    manualQuery: String(body.manualQuery || '').slice(0, 200),
    licenses: (Array.isArray(body.licenses) ? body.licenses : []).filter((l) => ALLOWED_LICENSES.has(l)),
    device: detectDevice(req, body.device),
    depth: ['rapide', 'normal', 'approfondie'].includes(body.depth) ? body.depth : undefined,
  };
  const provider = pickProvider(req, body);
  try {
    const out = await runSearch(params, provider);
    sendJson(res, 200, out);
  } catch (err) {
    sendJson(res, err.status || 500, {
      error: err.message || 'Erreur inconnue',
      source: provider.name,
      hint: provider.name === 'scrape'
        ? 'La recherche sans clé n’a pas pu lire YouTube. Ajoute une clé YouTube API (voir README) ou essaie le mode démo.'
        : provider.name === 'api' ? 'Vérifie ta clé YouTube API et ton quota.' : '',
    });
  }
}

async function serveStatic(req, res, pathname) {
  for (const [prefix, dir] of STATIC) {
    if (!pathname.startsWith(prefix)) continue;
    let rel = decodeURIComponent(pathname.slice(prefix.length)) || 'index.html';
    const file = resolve(dir, normPath(rel));
    if (file !== dir && !file.startsWith(dir + sep)) break; // pas de ../
    try {
      const s = await stat(file);
      if (!s.isFile()) continue;
      const data = await readFile(file);
      res.writeHead(200, {
        'Content-Type': MIME[extname(file)] || 'application/octet-stream',
        'Cache-Control': 'no-cache',
      });
      return res.end(data);
    } catch {
      continue;
    }
  }
  res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' });
  res.end('Introuvable');
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, 'http://localhost');
  try {
    if (url.pathname === '/api/search' && req.method === 'POST') return await handleSearch(req, res);
    if (url.pathname === '/api/status') {
      return sendJson(res, 200, {
        demo: FORCE_DEMO,
        apiKey: !!ENV_KEY,
        source: FORCE_DEMO ? 'demo' : ENV_KEY ? 'api' : 'scrape',
        device: detectDevice(req),
      });
    }
    if (req.method === 'GET' || req.method === 'HEAD') return await serveStatic(req, res, url.pathname);
    res.writeHead(405).end();
  } catch (err) {
    console.error(err);
    if (!res.headersSent) sendJson(res, 500, { error: 'Erreur serveur' });
  }
});

server.listen(PORT, HOST, () => {
  const mode = FORCE_DEMO ? 'DÉMO (prods fictives)' : ENV_KEY ? 'YouTube Data API' : 'sans clé (lecture des pages YouTube)';
  console.log(`Melofinds → http://localhost:${PORT}  [source : ${mode}]`);
});
