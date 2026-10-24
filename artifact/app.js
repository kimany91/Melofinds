(() => {
'use strict';
// Melofinds, version page Claude. Le moteur (buildPlan, analyzeVideo…) est chargé
// juste avant ce script. Ici : l'interface et la recherche YouTube via Parallel Search.

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const SVGNS = 'http://www.w3.org/2000/svg';
function icon(name) {
  const s = document.createElementNS(SVGNS, 'svg');
  s.setAttribute('aria-hidden', 'true');
  const u = document.createElementNS(SVGNS, 'use');
  u.setAttribute('href', `#i-${name}`);
  s.append(u);
  return s;
}
const h = (tag, attrs = {}, ...kids) => {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k === 'style') el.setAttribute('style', v);
    else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? '' : v);
  }
  for (const k of kids.flat()) if (k != null && k !== false) el.append(k instanceof Node ? k : String(k));
  return el;
};

// Deux versions : la page Claude (recherche via le connecteur Parallel Search,
// pas de lecteur possible) et la version web (API YouTube + lecteur intégré).
const WEB = window.MF_TARGET === 'web';
const WEB_URL = 'https://kimany91.github.io/Melofinds/';

const local = {
  get(k, fallback) { try { const v = localStorage.getItem(`mf.${k}`); return v == null ? fallback : JSON.parse(v); } catch { return fallback; } },
  set(k, v) { try { localStorage.setItem(`mf.${k}`, JSON.stringify(v)); } catch { /* indisponible */ } },
};

let toastTimer;
function toast(msg, action) {
  const t = $('#toast');
  $('#toastMsg').textContent = msg;
  const btn = $('#toastAction');
  btn.hidden = !action;
  btn.onclick = null;
  if (action) { btn.textContent = action.label; btn.onclick = () => { t.classList.remove('show'); action.run(); }; }
  t.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove('show'), action ? 5000 : 2200);
}

// ---------------------------------------------------------------------------
// Données gardées dans le compte Claude (sinon dans ce navigateur)

const state = { history: local.get('history', []), beats: local.get('beats', []) };
const MAX = { history: 80, beats: 120 };
const DESC_MAX = WEB ? 5000 : 2500;

const persist = {
  mode: 'local', refs: {}, timers: {},
  chain: { history: Promise.resolve(), beats: Promise.resolve() },
  async init() {
    const c = window.claude;
    if (!c?.use) return;
    try {
      const [db, user] = await Promise.all([c.use('db'), c.use('user')]);
      if (!db || !user) return;
      const uid = await user.id();
      if (!uid) return;
      for (const key of ['history', 'beats']) {
        const ref = db.doc(`data/users/${uid}/${key}`);
        this.refs[key] = ref;
        let first = true;
        ref.onSnapshot((snap) => {
          if (snap.metadata.hasPendingWrites) return;
          if (snap.exists) {
            const items = snap.data()?.items;
            if (Array.isArray(items)) { state[key] = JSON.parse(JSON.stringify(items)).filter((x) => x && typeof x === 'object' && (key === 'beats' ? x.id : true)); local.set(key, state[key]); refreshFor(key); }
          } else if (first && state[key].length) this.save(key);
          first = false;
        }, () => { this.mode = 'local'; });
      }
      this.mode = 'db';
    } catch { this.mode = 'local'; }
  },
  save(key) {
    state[key] = state[key].slice(0, MAX[key]);
    local.set(key, state[key]);
    if (this.mode !== 'db' || !this.refs[key]) return;
    clearTimeout(this.timers[key]);
    this.timers[key] = setTimeout(() => {
      const body = { items: state[key], updatedAt: new Date().toISOString() };
      this.chain[key] = this.chain[key].then(() => this.refs[key].set(body)).catch((e) => {
        if (e?.code === 'quota_exceeded') toast('Tes favoris sont pleins : retires-en quelques-uns.');
        else if (['invalid_argument', 'revoked', 'not_granted'].includes(e?.code)) this.mode = 'local';
      });
    }, 500);
  },
};
function refreshFor(key) {
  if (key === 'history') { renderHistory(); renderSavedSearches(); }
  else { renderSavedProds(); syncHearts(); }
  updateDots();
}

// ---------------------------------------------------------------------------
// Appareil : mise en page + volume de recherche adaptés

function detectDevice() {
  const ua = /Mobi|Android|iPhone|iPad|iPod/i.test(navigator.userAgent);
  return ua || window.innerWidth < 760 ? 'mobile' : 'desktop';
}
let device = detectDevice();
function applyDevice() {
  document.body.classList.toggle('mobile', device === 'mobile');
  document.body.classList.toggle('desktop', device === 'desktop');
}
let resizeTimer;
window.addEventListener('resize', () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => { const d = detectDevice(); if (d !== device) { device = d; applyDevice(); } }, 200);
});
// Version web : chaque recherche YouTube coûte 100 unités de quota (10 000 / jour),
// mais elle rapporte 50 vidéos dont on lit toutes les descriptions.
const LIMITS = () => (WEB
  ? (device === 'mobile' ? { firstQueries: 3, moreQueries: 2, read: 120 } : { firstQueries: 4, moreQueries: 3, read: 160 })
  : (device === 'mobile' ? { firstQueries: 3, moreQueries: 3, read: 36 } : { firstQueries: 5, moreQueries: 4, read: 60 }));

// ---------------------------------------------------------------------------
// Navigation

const VIEWS = ['search', 'saved', 'history', ...(window.MF_TARGET === 'web' ? ['recs', 'pc'] : [])];
function showView(name) {
  if (!VIEWS.includes(name)) name = 'search';
  $$('.nav-item').forEach((t) => { const on = t.dataset.view === name; t.classList.toggle('active', on); t.setAttribute('aria-selected', on); });
  $$('.view').forEach((v) => v.classList.toggle('active', v.id === `view-${name}`));
  local.set('view', name);
  if (name === 'saved') { renderSavedProds(); renderSavedSearches(); }
  if (name === 'history') renderHistory();
  if (name === 'recs') renderRecs();
  if (name === 'pc') { listenPc(); renderPcView(); askPcLib(); }
  window.scrollTo({ top: 0, behavior: 'smooth' });
}
$$('.nav-item').forEach((t) => t.addEventListener('click', () => showView(t.dataset.view)));
$('#brand').addEventListener('click', () => showView('search'));

// ---------------------------------------------------------------------------
// Outils d'affichage

const CAT_ICON = { ffp: '✓', upto: '⏳', fnp: '♪', paid: '$', unknown: '?' };
const SHORT = { ffp: 'Free for profit', upto: 'Up to', fnp: 'Free', paid: 'Payant', unknown: 'Inconnu' };
const KW_RE = /(free\s*(?:for|4)\s*profit|non[\s-]*profit|spotify|apple\s*music|streaming(?:\s*services)?|youtube\s*only|lease|licen[cs]e|licence|cr[eé]dit|untagged|purchase|buy|[\d.,]+\s*k?\s*(?:\([^)]*\)\s*)?(?:monetized\s*)?(?:streams?|plays?|écoutes))/gi;
const strip = (s) => String(s || '').normalize('NFD').replace(/[̀-ͯ]/g, '');
const ytSearchUrl = (q) => `https://www.youtube.com/results?search_query=${encodeURIComponent(q)}`;
const youtubeId = (url) => (String(url || '').match(/(?:youtu\.be\/|[?&]v=|\/shorts\/|\/embed\/|\/live\/)([\w-]{11})/) || [])[1] || null;

function highlight(text, terms = []) {
  const frag = document.createDocumentFragment();
  if (!text) return frag;
  const ranges = [];
  const plain = strip(text).toLowerCase();
  for (const t of terms) {
    if (!t) continue;
    let i = plain.indexOf(t);
    while (i !== -1) { ranges.push([i, i + t.length, 'q']); i = plain.indexOf(t, i + t.length); }
  }
  KW_RE.lastIndex = 0;
  let m;
  while ((m = KW_RE.exec(text))) ranges.push([m.index, m.index + m[0].length, 'kw']);
  ranges.sort((a, b) => a[0] - b[0] || (a[2] === 'q' ? -1 : 1));
  let pos = 0;
  for (const [s, e, kind] of ranges) {
    if (s < pos) continue;
    frag.append(text.slice(pos, s), h('mark', { class: kind === 'kw' ? 'kw' : null }, text.slice(s, e)));
    pos = e;
  }
  frag.append(text.slice(pos));
  return frag;
}

function chipLabel(L) {
  if (L.category === 'upto') return `Up to ${formatCount(L.limit)}`;
  if (L.misleading) return 'Payant · titre trompeur';
  return SHORT[L.category];
}
function verdictCopy(L, unread) {
  let t; let s;
  switch (L.category) {
    case 'ffp': t = 'Free for profit'; s = 'Tu peux sortir ton son sur Spotify sans payer.'; break;
    case 'upto': t = `Gratuit jusqu’à ${formatCount(L.limit)} ${L.limitUnit || 'streams'}`; s = 'Au-delà, il faut acheter une licence.'; break;
    case 'fnp': t = L.misleading ? 'Payer pour Spotify' : 'Free (non-profit)'; s = L.misleading ? 'Le titre dit « free for profit », mais la description demande une licence pour sortir le son.' : 'Gratuit pour YouTube / SoundCloud. Licence payante pour Spotify.'; break;
    case 'paid': t = 'Payant'; s = 'Il faut acheter une licence, ou la prod est déjà vendue.'; break;
    default: t = 'À vérifier'; s = 'La description ne dit rien de clair sur les droits.';
  }
  if (unread) s = 'Description illisible : verdict d’après le titre seulement. Ouvre la vidéo pour vérifier.';
  return { t, s };
}
function partialNote(item) {
  return item.partial ? h('p', { class: 'partial-note' }, 'Je n’ai lu que le début de la description. Vérifie la fin sur YouTube avant de sortir ton son.') : null;
}
async function copyText(text) {
  try { await navigator.clipboard.writeText(text); toast('Lien copié'); } catch { toast('Copie impossible ici : sélectionne le lien à la main.'); }
}

// Analyse (avec cache par prod)
// Tunebat : BPM / clé manquants, cherchés sur Tunebat (morceaux sortis sur Spotify).
// Ce qui vient de Tunebat s'affiche en bleu. Résultats gardés dans ce navigateur.
const tbCache = (() => { const c = local.get('tbCache', {}); return c && typeof c === 'object' ? c : {}; })();
function tbFor(id) {
  const t = tbCache[id];
  return t && (t.bpm || t.key) ? t : null;
}
function tbStore(id, t) {
  tbCache[id] = t;
  const ids = Object.keys(tbCache);
  if (ids.length > 800) for (const k of ids.slice(0, ids.length - 800)) delete tbCache[k];
  local.set('tbCache', tbCache);
}
async function tbLookup(item) {
  if (!WEB || !item?.id || tbCache[item.id] || tbLookup.busy?.has(item.id)) return;
  (tbLookup.busy ||= new Set()).add(item.id);
  try {
    for (const q of tbQueries({ title: item.title, channel: item.channel })) {
      const res = await fetch(TB_SEARCH + encodeURIComponent(q), { headers: { accept: 'application/json' } });
      if (!res.ok) throw new Error(`tunebat ${res.status}`);
      const pick = tbPick((await res.json())?.data?.items, { title: item.title, channel: item.channel, duration: item.duration });
      if (pick) {
        tbStore(item.id, { bpm: pick.bpm, key: pick.key, at: Date.now() });
        refreshItem(item);
        return;
      }
    }
    tbStore(item.id, { none: true, at: Date.now() });
  } catch {
    tbStore(item.id, { fail: true, at: Date.now() }); // Tunebat injoignable d'ici : le PC essaiera au téléchargement
  } finally { tbLookup.busy.delete(item.id); }
}
function refreshItem(item) {
  if (session?.items?.has(item.id)) renderResults();
  if ($('#drawer').classList.contains('open') && $('#drawer').dataset.item === item.id) openBeat(item, session?.plan || null);
}

function analyzed(item, plan) {
  const tb = tbFor(item.id);
  const key = `${(item.description || '').length}|${item.title}|${plan ? 1 : 0}|${tb ? `${tb.bpm}/${tb.key}` : ''}`;
  if (item._r && item._key === key) return item._r;
  const r = analyzeVideo({ id: item.id, title: item.title, description: item.description || '', foundBy: item.foundBy }, plan || null);
  if (tb) {
    if (!r.bpm && tb.bpm) { r.bpm = tb.bpm; r.bpmTb = true; }
    if (!r.key && tb.key) { r.key = tb.key; r.keyTb = true; }
  }
  Object.defineProperty(item, '_r', { value: r, writable: true, enumerable: false, configurable: true });
  Object.defineProperty(item, '_key', { value: key, writable: true, enumerable: false, configurable: true });
  return r;
}
function safeRow(item, plan) {
  try { return { ...analyzed(item, plan), _item: item }; } catch (e) { console.error('Melofinds : prod ignorée', item?.id, e); return null; }
}
function cardLine(item, r) {
  if (item.status === 'unread') return { text: 'Description illisible : verdict d’après le titre.', warn: false };
  if (r.license.misleading) return { text: '⚠ Titre trompeur : licence payante pour Spotify.', warn: true };
  const lic = (r.keyLines || []).find((l) => l.type === 'licence');
  if (lic) return { text: lic.text, warn: false };
  return { text: r.license.reasons[0]?.text || '', warn: false };
}

// ---------------------------------------------------------------------------
// Carte prod (grille) + panneau de détails

function isSaved(id) { return state.beats.some((b) => b.id === id); }
function toggleSaved(item) {
  if (isSaved(item.id)) {
    state.beats = state.beats.filter((b) => b.id !== item.id);
    toast('Retirée des favoris');
  } else {
    const { id, url, title, description, views, viewCount, likeCount, age, status } = item;
    state.beats = [{ id, url, title, description, views, viewCount, likeCount, age, status, savedAt: new Date().toISOString() }, ...state.beats];
    toast('Ajoutée aux favoris', { label: 'Voir', run: () => { showView('saved'); setSeg('prods'); } });
  }
  persist.save('beats');
  syncHearts();
  updateDots();
  return isSaved(item.id);
}
function syncHearts() {
  $$('.heart[data-id]').forEach((b) => { const on = isSaved(b.dataset.id); b.classList.toggle('on', on); b.setAttribute('aria-pressed', String(on)); });
}

function renderCard(item, r, { isNew = false, index = 0, plan = null } = {}) {
  const L = r.license;
  const cat = L.category;
  const vid = ytIdOf(item);
  if (vid) cardItems.set(vid, item);
  const card = h('article', { class: `card cat-${cat}${isNew ? ' new' : ''}${item.status === 'unread' ? ' unread' : ''}${vid && vid === player.vid ? ' playing' : ''}`, style: `--i:${index}`, 'data-vid': vid });
  const style = r.styles?.[0]?.label || 'Type beat';
  const coverAttrs = WEB
    ? { type: 'button', class: `cover${vid ? ' has-thumb' : ''}`, 'aria-label': `Écouter « ${item.title} »`, onclick: () => playItem(item), onpointerenter: () => warmPlayer(item), onpointerdown: () => warmPlayer(item), onfocus: () => warmPlayer(item) }
    : { class: 'cover', href: ytWatchUrl(item), target: '_blank', rel: 'noopener', 'aria-label': `Écouter « ${item.title} » sur YouTube` };
  card.append(h(WEB ? 'button' : 'a', coverAttrs,
    WEB && vid ? h('img', { class: 'thumb', src: `https://i.ytimg.com/vi/${vid}/hqdefault.jpg`, alt: '', loading: 'lazy', decoding: 'async', onerror: (e) => { e.currentTarget.closest('.cover')?.classList.remove('has-thumb'); e.currentTarget.remove(); } }) : null,
    h('span', { class: 'lic-chip' }, chipLabel(L)),
    item.status === 'unread' ? h('span', { class: 'unread-chip' }, 'non vérifiée') : null,
    h('span', { class: 'play' }, icon('play'), icon('pause'), h('span', { class: 'eq', 'aria-hidden': 'true' }, h('i'), h('i'), h('i'))),
    h('span', { class: 'cover-meta' }, style, r.key ? h('small', { class: r.keyTb ? 'tb' : null, title: r.keyTb ? 'Trouvé avec Tunebat' : null }, r.key) : null),
    r.bpm ? h('span', { class: `cover-bpm${r.bpmTb ? ' tb' : ''}`, title: r.bpmTb ? 'Trouvé avec Tunebat' : null }, r.bpm, h('small', {}, r.bpmTb ? 'BPM · TB' : 'BPM')) : h('span', { class: 'cover-bpm none' }, 'BPM ?')));
  const heart = h('button', { type: 'button', class: `heart${isSaved(item.id) ? ' on' : ''}`, 'data-id': item.id, 'aria-label': 'Ajouter aux favoris', 'aria-pressed': String(isSaved(item.id)) }, icon('heart'));
  heart.addEventListener('click', (e) => { e.stopPropagation(); toggleSaved(item); });
  card.append(heart);
  const line = cardLine(item, r);
  const ratio = ratioOf(item);
  const tier = ratio == null ? '' : ratio >= 5 ? ' hi' : ratio >= 2.5 ? ' mid' : ' lo';
  const meta = [item.duration > 0 ? fmtTime(item.duration) : null, item.views ? `${item.views} vues` : null, item.age].filter(Boolean).join(' · ');
  const main = h('div', { class: 'card-main', role: 'button', tabindex: '0', 'aria-label': `Détails de ${item.title}` },
    h('h3', { class: 'title', title: item.title }, displayTitle(item.title)),
    line.text ? h('p', { class: `line${line.warn ? ' warn' : ''}` }, line.text) : null,
    h('div', { class: 'meta' },
      h('span', { class: 'meta-txt' }, meta || ' '),
      ratio != null ? h('span', { class: `ratio${tier}`, title: `${item.likeCount.toLocaleString('fr-FR')} likes pour ${(item.viewCount ?? parseCount(item.views)).toLocaleString('fr-FR')} vues` }, icon('heart'), `${fmtPct(ratio)} likes`) : null,
      h('span', { class: 'more' }, 'Détails →')));
  card.append(h('div', { class: 'card-links' },
    WEB && vid ? pcButton(item) : null,
    h('a', { class: 'yt-link', href: ytWatchUrl(item), target: '_blank', rel: 'noopener', 'aria-label': `Ouvrir « ${item.title} » sur YouTube` }, 'YouTube', icon('ext'))));
  const open = () => openBeat(item, plan);
  main.addEventListener('click', open);
  main.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open(); } });
  card.append(main);
  return card;
}

// ---------------------------------------------------------------------------
// Lecteur intégré (version web) : un lecteur YouTube invisible, piloté par la
// mini-barre. Il reste chargé : passer d'une prod à l'autre est instantané.
// Il se prépare dès que la souris passe sur une prod (ou au toucher).
// La page Claude interdit tout lecteur externe : là-bas, on ouvre YouTube.

function ytIdOf(item) {
  const m = (item?.url || '').match(/[?&]v=([\w-]{11})/);
  if (m) return m[1];
  return /^[\w-]{11}$/.test(item?.id || '') ? item.id : null;
}
const ytWatchUrl = (item) => item?.url || (ytIdOf(item) ? `https://www.youtube.com/watch?v=${ytIdOf(item)}` : ytSearchUrl(item?.title || ''));
const YT_ERRORS = {
  2: 'Vidéo introuvable.',
  5: 'Ce navigateur ne peut pas lire cette vidéo.',
  100: 'Vidéo supprimée ou privée.',
  101: 'Le beatmaker a interdit la lecture en dehors de YouTube.',
  150: 'Le beatmaker a interdit la lecture en dehors de YouTube.',
  153: 'YouTube refuse la lecture intégrée sur cette page.',
};
const player = { item: null, vid: null, frame: null, ready: false, loadedVid: null, state: -1, time: 0, timeAt: 0, dur: 0, status: 'idle', message: '', timers: [], listen: null };
// Position actuelle de la prod (YouTube n'envoie la position que ~4 fois par seconde)
const playerNow = () => player.time + (isPlaying() && player.timeAt ? (performance.now() - player.timeAt) / 1000 : 0);
const fmtTime = (s) => (s > 0 ? `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}` : '0:00');
const isPlaying = () => player.state === 1 || player.state === 3;

function ytSend(func, args = []) {
  try { player.frame?.contentWindow?.postMessage(JSON.stringify({ event: 'command', func, args, id: 1, channel: 'widget' }), '*'); } catch { /* cadre parti */ }
}
function later(fn, ms) { player.timers.push(setTimeout(fn, ms)); }
function clearLater() { player.timers.forEach(clearTimeout); player.timers = []; }
function destroyFrame() {
  clearInterval(player.listen);
  player.listen = null;
  player.frame?.remove();
  Object.assign(player, { frame: null, ready: false, loadedVid: null, state: -1 });
}

function createFrame(vid, autoplay) {
  destroyFrame();
  const params = new URLSearchParams({ autoplay: autoplay ? '1' : '0', enablejsapi: '1', controls: '0', playsinline: '1', rel: '0', iv_load_policy: '3', fs: '0', disablekb: '1' });
  if (location.origin && location.origin !== 'null') params.set('origin', location.origin);
  const f = document.createElement('iframe');
  f.src = `https://www.youtube-nocookie.com/embed/${vid}?${params}`;
  f.allow = 'autoplay; encrypted-media';
  f.referrerPolicy = 'strict-origin-when-cross-origin';
  f.title = 'Lecteur audio';
  f.tabIndex = -1;
  // Comme l'API officielle : on se signale jusqu'à ce que le lecteur réponde.
  const hello = () => { try { f.contentWindow?.postMessage(JSON.stringify({ event: 'listening', id: 1, channel: 'widget' }), '*'); } catch { /* pas prêt */ } };
  f.addEventListener('load', hello);
  player.listen = setInterval(hello, 250);
  $('#ytHost').replaceChildren(f);
  player.frame = f;
  player.loadedVid = vid;
}

// Préparer le lecteur avant le clic (survol, toucher, focus)
function warmPlayer(item) {
  if (!WEB || player.frame) return;
  const vid = ytIdOf(item);
  if (vid) createFrame(vid, false);
}
// Dès que des prods s'affichent, on charge le lecteur en avance (sans son)
function prewarmPlayer() {
  if (!WEB || player.frame) return;
  setTimeout(() => {
    const first = $('#grid .card[data-vid]') || $('#savedGrid .card[data-vid]');
    if (first && !player.frame) createFrame(first.dataset.vid, false);
  }, 1200);
}

function playItem(item) {
  pcStop(true);
  const vid = ytIdOf(item);
  if (!vid) { toast('Pas de vidéo YouTube pour cette prod'); return; }
  player.userPaused = false;
  bgStart(item);
  if (player.item && player.vid === vid && player.frame && player.status !== 'blocked') { togglePlay(); return; }
  clearLater();
  Object.assign(player, { item, vid, status: 'loading', message: '', time: 0, dur: 0 });
  if (!player.frame) createFrame(vid, true);
  else if (player.ready) startVideo();
  // sinon : le lecteur finit de charger, onPlayerReady lancera la vidéo
  later(() => { if (!player.ready) playerBlocked('Le lecteur YouTube ne répond pas. Vérifie ta connexion.', true); }, 9000);
  renderMini();
}

function startVideo() {
  if (player.loadedVid !== player.vid) {
    player.state = -1;
    ytSend('loadVideoById', [player.vid, 0]);
    player.loadedVid = player.vid;
  } else {
    ytSend('playVideo');
  }
  // Lecture auto refusée (souvent sur iPhone) : on relance, puis on demande un toucher.
  later(() => { if (player.item && !isPlaying() && player.state !== 0 && player.state !== 2) ytSend('playVideo'); }, 2200);
  later(() => { if (player.item && !isPlaying() && player.state !== 0 && player.state !== 2) { player.status = 'tap'; renderMini(); } }, 4500);
}

function onPlayerReady() {
  if (player.ready) return;
  player.ready = true;
  clearInterval(player.listen);
  if (player.item && player.status !== 'blocked') startVideo();
  renderMini();
}

function togglePlay() {
  if (!player.item) return;
  if (!player.frame || player.status === 'blocked') { const it = player.item; player.item = null; playItem(it); return; }
  if (isPlaying()) { player.userPaused = true; bgPause(); ytSend('pauseVideo'); player.state = 2; renderMini(); return; }
  player.userPaused = false;
  bgStart(player.item);
  if (player.state === 0) ytSend('seekTo', [0, true]);
  ytSend('playVideo');
  if (player.status === 'tap') {
    later(() => { if (player.item && !isPlaying()) playerBlocked('Ton navigateur bloque le son ici. Ouvre la prod sur YouTube.'); }, 2500);
  }
}

function playerBlocked(msg, killFrame = false) {
  clearLater();
  if (killFrame) destroyFrame(); else ytSend('stopVideo');
  player.status = 'blocked';
  player.message = msg;
  renderMini();
}

function stopPlayer() {
  clearLater();
  player.userPaused = true;
  bgStop();
  ytSend('stopVideo');
  Object.assign(player, { item: null, vid: null, status: 'idle', time: 0, dur: 0 });
  renderMini();
}

// ---------------------------------------------------------------------------
// Téléphone verrouillé / appli en arrière-plan (au mieux de ce que permet un
// lecteur YouTube caché) : commandes sur l'écran verrouillé quand le téléphone les
// propose, tentative de relance si le système coupe la prod, reprise au retour
// sur l'appli, et prod suivante de la liste à la fin.

const cardItems = new Map(); // vid → prod affichée (pour suivante / précédente)
const bg = { resumes: 0, lastResume: 0 };
// Pas de « son silencieux » pour garder la page active : il sifflait (note aiguë) et ne
// suffit pas à empêcher le téléphone de couper le lecteur YouTube.
function bgStart(item) {
  if (WEB) mediaSessionFor(item);
}
function bgPause() { msState(); }
function bgStop() {
  if ('mediaSession' in navigator) { try { navigator.mediaSession.metadata = null; navigator.mediaSession.playbackState = 'none'; } catch { /* rien */ } }
}
let msHandlersSet = false;
function mediaSessionFor(item) {
  if (!('mediaSession' in navigator) || !item) return;
  const vid = ytIdOf(item);
  try {
    navigator.mediaSession.metadata = new MediaMetadata({
      title: displayTitle(item.title || 'Prod'), artist: 'Melofinds', album: 'Type beats',
      artwork: vid ? [{ src: `https://i.ytimg.com/vi/${vid}/hqdefault.jpg`, sizes: '480x360', type: 'image/jpeg' }] : [],
    });
  } catch { /* navigateur ancien */ }
  if (msHandlersSet) return;
  msHandlersSet = true;
  const on = (action, fn) => { try { navigator.mediaSession.setActionHandler(action, fn); } catch { /* action non gérée */ } };
  on('play', () => { if (player.item && !isPlaying()) togglePlay(); });
  on('pause', () => { if (player.item && isPlaying()) togglePlay(); });
  on('stop', () => stopPlayer());
  on('nexttrack', () => playNeighbour(1));
  on('previoustrack', () => { if (playerNow() > 5) seekBeat(0); else playNeighbour(-1); });
  on('seekto', (e) => { if (e?.seekTime != null && player.frame) seekBeat(e.seekTime); });
  on('seekforward', () => seekBeat(playerNow() + 10));
  on('seekbackward', () => seekBeat(Math.max(0, playerNow() - 10)));
}
function msState() {
  if (!('mediaSession' in navigator)) return;
  try {
    navigator.mediaSession.playbackState = player.item ? (isPlaying() ? 'playing' : 'paused') : 'none';
    if (player.dur > 0) navigator.mediaSession.setPositionState({ duration: player.dur, position: Math.min(player.dur, Math.max(0, playerNow())), playbackRate: 1 });
  } catch { /* position non gérée */ }
}
function playNeighbour(dir) {
  const view = $('.view.active') || document;
  const vids = $$('.card[data-vid]', view).map((c) => c.dataset.vid);
  const i = vids.indexOf(player.vid);
  const next = i >= 0 ? cardItems.get(vids[i + dir]) : null;
  if (!next) return false;
  playItem(next);
  return true;
}
function onStateChanged(was, st) {
  msState();
  if (!player.item || player.status === 'blocked' || rec.state !== 'idle' || take.id) return;
  if (st === 0) { // fin de la prod : on enchaîne sur la suivante de la liste
    if (!playNeighbour(1)) { bgPause(); }
    return;
  }
  // Mise en pause par le téléphone (écran verrouillé), pas par toi : on relance.
  if ((st === 2 || st === -1 || st === 5) && document.hidden && !player.userPaused) {
    const now = Date.now();
    if (bg.resumes < 30 && now - bg.lastResume > 1500) {
      bg.resumes++;
      bg.lastResume = now;
      ytSend('playVideo');
    }
  }
}
document.addEventListener('visibilitychange', () => {
  bg.resumes = 0;
  if (!document.hidden && player.item && !player.userPaused && !isPlaying() && player.status !== 'blocked' && rec.state === 'idle' && !take.id) {
    ytSend('playVideo'); // de retour sur l'appli : on reprend si le téléphone avait coupé
  }
});

window.addEventListener('message', (e) => {
  if (!player.frame || e.source !== player.frame.contentWindow) return;
  if (!/^https:\/\/(?:www\.)?youtube(?:-nocookie)?\.com$/.test(e.origin)) return;
  let d = e.data;
  if (typeof d === 'string') { try { d = JSON.parse(d); } catch { return; } }
  if (!d || typeof d !== 'object') return;
  if (d.event === 'onReady' || d.event === 'initialDelivery') onPlayerReady();
  if ((d.event === 'infoDelivery' || d.event === 'initialDelivery') && d.info && typeof d.info === 'object') {
    const i = d.info;
    if (typeof i.playerState === 'number') player.state = i.playerState;
    if (typeof i.currentTime === 'number') { player.time = i.currentTime; player.timeAt = performance.now(); }
    if (typeof i.duration === 'number' && i.duration > 0) player.dur = i.duration;
    if (!player.ready) onPlayerReady();
  }
  if (d.event === 'onStateChange' && typeof d.info === 'number') player.state = d.info;
  if (d.event === 'onError') { if (player.item) playerBlocked(YT_ERRORS[d.info] || 'Lecture impossible ici. Ouvre la prod sur YouTube.'); return; }
  if (player.state !== player.prevState) { const was = player.prevState; player.prevState = player.state; onStateChanged(was, player.state); }
  if (isPlaying() && player.status !== 'blocked') player.status = 'ready';
  if (player.item) renderMini();
});

let miniHideTimer = null;
let msTick = 0;
function renderMini() {
  if (Date.now() - msTick > 1000) { msTick = Date.now(); msState(); }
  const mini = $('#mini');
  const on = Boolean(player.item);
  document.body.classList.toggle('has-mini', on);
  clearTimeout(miniHideTimer);
  if (!on) {
    mini.classList.remove('show');
    miniHideTimer = setTimeout(() => { if (!player.item) mini.hidden = true; }, 320);
  } else if (mini.hidden) {
    mini.hidden = false;
    requestAnimationFrame(() => mini.classList.add('show'));
  } else mini.classList.add('show');
  if (on) {
    const playing = isPlaying();
    mini.classList.toggle('playing', playing);
    mini.classList.toggle('blocked', player.status === 'blocked');
    mini.classList.toggle('loading', player.status === 'loading' && !playing);
    $('#miniTitle').textContent = displayTitle(player.item.title || 'Prod');
    const sub = player.status === 'blocked' ? player.message
      : player.status === 'loading' && !playing ? 'Chargement…'
      : player.status === 'tap' && !playing ? 'Touche ▶ pour lancer le son'
      : player.state === 0 ? 'Terminé'
      : `${fmtTime(player.time)} / ${fmtTime(player.dur)}`;
    $('#miniSub').textContent = sub;
    const pct = player.dur ? Math.min(100, (player.time / player.dur) * 100) : 0;
    $('#miniFill').style.width = `${pct}%`;
    $('#miniBar').setAttribute('aria-valuenow', String(Math.round(pct)));
    $('#miniExt').href = ytWatchUrl(player.item);
    const tg = $('#miniToggle');
    tg.hidden = player.status === 'blocked';
    $('#miniRec').hidden = !WEB || player.status === 'blocked';
    $('#miniRec').classList.toggle('live', rec.state === 'rec');
    tg.setAttribute('aria-label', playing ? 'Pause' : 'Lecture');
  }
  $$('.card[data-vid]').forEach((c) => {
    const me = on && c.dataset.vid === player.vid && player.status !== 'blocked';
    c.classList.toggle('playing', me);
    c.classList.toggle('paused', me && !isPlaying());
  });
}

$('#miniToggle').addEventListener('click', togglePlay);
$('#miniRec').addEventListener('click', () => { if (player.item) openStudio(player.item); });
$('#miniClose').addEventListener('click', stopPlayer);
function seekFromBar(clientX) {
  if (!player.dur || !player.frame) return;
  const r = $('#miniBar').getBoundingClientRect();
  const t = Math.max(0, Math.min(1, (clientX - r.left) / r.width)) * player.dur;
  player.time = t;
  ytSend('seekTo', [t, true]);
  renderMini();
}
$('#miniBar').addEventListener('click', (e) => seekFromBar(e.clientX));
$('#miniBar').addEventListener('keydown', (e) => {
  if (!player.dur || !player.frame) return;
  const step = e.key === 'ArrowRight' ? 5 : e.key === 'ArrowLeft' ? -5 : 0;
  if (!step) return;
  e.preventDefault();
  player.time = Math.max(0, Math.min(player.dur, player.time + step));
  ytSend('seekTo', [player.time, true]);
  renderMini();
});
document.addEventListener('keydown', (e) => {
  if (e.code !== 'Space' || !player.item || player.status === 'blocked') return;
  if (e.target.closest('input, textarea, select, button, a, [contenteditable], [role="button"], [role="slider"]')) return;
  e.preventDefault();
  togglePlay();
});

let lastFocus = null;
// ---------------------------------------------------------------------------
// Rec (version web) : tu rappes sur la prod comme sur un dictaphone.
// La prod joue dans le lecteur invisible, le micro enregistre ta voix. Chaque
// prise retient où elle commence dans la prod : à la réécoute, la voix repart
// calée sur la prod (réglage fin du calage si besoin). Les prises restent dans
// ce navigateur (IndexedDB) et se téléchargent.

const rec = { state: 'idle', stream: null, ctx: null, analyser: null, cap: null, recorder: null, chunks: [], mime: '', offset: 0, startAt: 0, beat: null, raf: 0, tick: 0, autoStop: 0 };
const take = { id: null, audio: null, url: '', offset: 0, sync: 0, beatId: null, duration: 0 };
const takePos = new Map(); // position de lecture de chaque prise (pause / reprise, barre)

// --- Volume de la voix. Échelle affichée : 150 % = gain ×3,1 ; jusqu'à 300 % (×6,2).
// Après le gain, un limiteur ne touche que les crêtes qui dépasseraient -1 dB : pas de
// compression, pas de souffle remonté. Le son est calculé sur le fichier (le même à
// l'écoute et dans le .wav téléchargé).
const GAIN_PER_PCT = 3.1 / 150;
const MAX_PCT = 300;
const MAX_GAIN = MAX_PCT * GAIN_PER_PCT;
const AUTO_MAX_GAIN = 4;
const CEIL = 0.891; // -1 dBFS
const gainToPct = (g) => Math.round((g || 0) / GAIN_PER_PCT);
let audioCtxRef = null;
const audioCtx = () => (audioCtxRef ||= new (window.AudioContext || window.webkitAudioContext)());

// Limiteur « brickwall » avec anticipation de 5 ms et relâchement de 120 ms.
// En dessous de -1 dB le son n'est pas modifié (à part le gain choisi).
function limitInPlace(chans, rate, gain) {
  const n = chans[0].length;
  if (!n) return chans;
  const look = Math.max(1, Math.round(rate * 0.005));
  const rel = Math.exp(-1 / (rate * 0.12));
  const req = new Float32Array(n); // gain maximal permis à chaque échantillon
  for (let i = 0; i < n; i++) {
    let pk = 0;
    for (const c of chans) { const v = Math.abs(c[i] * gain); if (v > pk) pk = v; }
    req[i] = pk > CEIL ? CEIL / pk : 1;
  }
  // minimum glissant sur [i, i + look] (file monotone)
  const env = new Float32Array(n);
  const dq = new Int32Array(n);
  let qh = 0; let qt = 0; let j = 0;
  for (let i = 0; i < n; i++) {
    const last = Math.min(n - 1, i + look);
    while (j <= last) { while (qt > qh && req[dq[qt - 1]] >= req[j]) qt--; dq[qt++] = j++; }
    while (dq[qh] < i) qh++;
    env[i] = req[dq[qh]];
  }
  let g = 1;
  for (let i = 0; i < n; i++) { g = Math.min(env[i], 1 - (1 - g) * rel); env[i] = g; }
  // lissage sur la fenêtre d'anticipation : reste sous le besoin de chaque crête
  let sum = 0;
  for (let i = 0; i < n; i++) {
    sum += env[i];
    if (i > look) sum -= env[i - look - 1];
    const k = (sum / Math.min(i + 1, look + 1)) * gain;
    for (const c of chans) c[i] = Math.max(-CEIL, Math.min(CEIL, c[i] * k));
  }
  return chans;
}

// WAV PCM 24 bits (sans perte)
function encodeWav(chans, rate) {
  const ch = chans.length;
  const len = chans[0].length;
  const bytes = new Uint8Array(44 + len * ch * 3);
  const dv = new DataView(bytes.buffer);
  const str = (o, t) => { for (let i = 0; i < t.length; i++) bytes[o + i] = t.charCodeAt(i); };
  str(0, 'RIFF'); dv.setUint32(4, 36 + len * ch * 3, true); str(8, 'WAVE'); str(12, 'fmt ');
  dv.setUint32(16, 16, true); dv.setUint16(20, 1, true); dv.setUint16(22, ch, true);
  dv.setUint32(24, rate, true); dv.setUint32(28, rate * ch * 3, true);
  dv.setUint16(32, ch * 3, true); dv.setUint16(34, 24, true); str(36, 'data'); dv.setUint32(40, len * ch * 3, true);
  let o = 44;
  for (let i = 0; i < len; i++) {
    for (let c = 0; c < ch; c++) {
      const v = Math.max(-1, Math.min(1, chans[c][i]));
      const x = Math.round(v < 0 ? v * 0x800000 : v * 0x7fffff);
      bytes[o] = x & 255; bytes[o + 1] = (x >> 8) & 255; bytes[o + 2] = (x >> 16) & 255;
      o += 3;
    }
  }
  return new Blob([bytes], { type: 'audio/wav' });
}

// Lecture directe d'un WAV (sans rééchantillonnage du navigateur)
function parseWav(buf) {
  const dv = new DataView(buf);
  if (dv.byteLength < 44 || dv.getUint32(0) !== 0x52494646 || dv.getUint32(8) !== 0x57415645) return null;
  let p = 12;
  let fmt = null;
  while (p + 8 <= dv.byteLength) {
    const id = dv.getUint32(p);
    const size = dv.getUint32(p + 4, true);
    const body = p + 8;
    if (id === 0x666d7420) {
      fmt = { tag: dv.getUint16(body, true), ch: dv.getUint16(body + 2, true), rate: dv.getUint32(body + 4, true), bits: dv.getUint16(body + 14, true) };
    } else if (id === 0x64617461 && fmt) {
      const bps = fmt.bits / 8;
      const float = fmt.bits === 32 && fmt.tag === 3;
      if (![2, 3, 4].includes(bps) || !fmt.ch) return null;
      const n = Math.floor(Math.min(size, dv.byteLength - body) / (bps * fmt.ch));
      const chans = Array.from({ length: fmt.ch }, () => new Float32Array(n));
      let o = body;
      for (let i = 0; i < n; i++) {
        for (let c = 0; c < fmt.ch; c++) {
          let v;
          if (bps === 2) v = dv.getInt16(o, true) / 0x8000;
          else if (bps === 3) v = (((dv.getUint8(o) | (dv.getUint8(o + 1) << 8) | (dv.getUint8(o + 2) << 16)) << 8) >> 8) / 0x800000;
          else v = float ? dv.getFloat32(o, true) : dv.getInt32(o, true) / 0x80000000;
          chans[c][i] = v;
          o += bps;
        }
      }
      return { chans, rate: fmt.rate };
    }
    p = body + size + (size & 1);
  }
  return null;
}

// Prise décodée { chans, rate } (gardée en mémoire pour les réglages de volume)
const decoded = new Map();
async function decodeTake(r) {
  if (decoded.has(r.id)) return decoded.get(r.id);
  const buf = await r.blob.arrayBuffer();
  let d = /wav/.test(r.mime || r.blob.type || '') ? parseWav(buf) : null;
  if (!d) {
    const ab = await new Promise((resolve, reject) => {
      const pr = audioCtx().decodeAudioData(buf, resolve, reject);
      if (pr?.then) pr.then(resolve, reject);
    });
    d = { chans: Array.from({ length: ab.numberOfChannels }, (_, c) => ab.getChannelData(c).slice()), rate: ab.sampleRate };
  }
  decoded.set(r.id, d);
  while (decoded.size > 3) decoded.delete(decoded.keys().next().value);
  return d;
}
function peakOf(chans) {
  let peak = 0;
  for (const d of chans) for (let i = 0; i < d.length; i++) { const v = Math.abs(d[i]); if (v > peak) peak = v; }
  return peak;
}
const autoGainFor = (peak) => (peak > 0.002 ? Math.min(AUTO_MAX_GAIN, Math.max(1, CEIL / peak)) : 1); // ≈ -1 dB
async function measureTake(r) {
  try { const peak = peakOf((await decodeTake(r)).chans); return { peak, autoGain: autoGainFor(peak) }; } catch { return { peak: null, autoGain: 1 }; }
}
const beatVol = () => Math.max(0, Math.min(100, Number(local.get('recBeatVol', 100)) || 0));
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
async function waitFor(cond, ms = 8000) {
  const end = Date.now() + ms;
  while (Date.now() < end) { if (cond()) return true; await wait(50); }
  return cond();
}
const recLatency = () => Number(local.get('recLatency', 0)) || 0;
const fmtDur = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;

// --- Stockage des prises (IndexedDB, sinon en mémoire le temps de la visite)
const recStore = {
  db: null, mem: [],
  open() {
    if (this.db !== null) return this.db;
    this.db = new Promise((resolve) => {
      try {
        const req = indexedDB.open('melofinds-recs', 1);
        req.onupgradeneeded = () => req.result.createObjectStore('takes', { keyPath: 'id' });
        req.onsuccess = () => resolve(req.result);
        req.onerror = () => resolve(null);
      } catch { resolve(null); }
    });
    return this.db;
  },
  async tx(mode, fn) {
    const db = await this.open();
    if (!db) return fn(null);
    return new Promise((resolve, reject) => {
      const t = db.transaction('takes', mode);
      const out = fn(t.objectStore('takes'));
      t.oncomplete = () => resolve(out?.result ?? out);
      t.onerror = () => reject(t.error);
    });
  },
  async all() {
    try {
      const rows = await this.tx('readonly', (st) => (st ? st.getAll() : null));
      return (Array.isArray(rows) ? rows : this.mem).slice().sort((a, b) => b.at - a.at);
    } catch { return this.mem.slice().sort((a, b) => b.at - a.at); }
  },
  async put(r) {
    try { await this.tx('readwrite', (st) => { if (st) st.put(r); else this.mem.push(r); }); } catch { this.mem.push(r); toast('Prise gardée seulement jusqu’à la fermeture de la page'); }
  },
  async del(id) {
    this.mem = this.mem.filter((r) => r.id !== id);
    try { await this.tx('readwrite', (st) => st?.delete(id)); } catch { /* déjà absente */ }
  },
};

// --- Capture du micro sans perte : les échantillons bruts (PCM) sont copiés tels
// quels, sans encodage. AudioWorklet si possible, sinon ScriptProcessor ;
// MediaRecorder (compressé) seulement si le navigateur n'a pas Web Audio.
const CAPTURE_WORKLET = `class MfCapture extends AudioWorkletProcessor {
  constructor() { super(); this.on = false; this.buf = null; this.n = 0;
    this.port.onmessage = (e) => {
      if (e.data === 'start') this.on = true;
      else if (e.data === 'stop') { this.flush(); this.on = false; this.port.postMessage({ end: true }); }
    };
  }
  flush() {
    if (this.buf && this.n) { const ch = this.buf.map((b) => b.slice(0, this.n)); this.port.postMessage({ ch }, ch.map((b) => b.buffer)); }
    this.buf = null; this.n = 0;
  }
  process(inputs) {
    if (!this.on) return true;
    let inp = inputs[0];
    if (!inp || !inp.length) inp = [new Float32Array(128)];
    const len = inp[0].length;
    if (this.buf && (this.buf.length !== inp.length || this.n + len > 16384)) this.flush();
    if (!this.buf) this.buf = inp.map(() => new Float32Array(16384));
    for (let c = 0; c < inp.length; c++) this.buf[c].set(inp[c], this.n);
    this.n += len;
    return true;
  }
}
registerProcessor('mf-capture', MfCapture);`;

async function setupCapture(ctx, stream) {
  if (!ctx) return null;
  try { if (ctx.state !== 'running') await ctx.resume(); } catch { /* bloqué */ }
  if (ctx.state !== 'running') return null;
  const src = ctx.createMediaStreamSource(stream);
  const sink = ctx.createGain();
  sink.gain.value = 0; // rien n'est renvoyé dans le casque
  sink.connect(ctx.destination);
  const cap = { rate: ctx.sampleRate, chunks: [], frames: 0, on: false, node: null, ended: null };
  const push = (chs) => { if (cap.on && chs?.[0]?.length) { cap.chunks.push(chs); cap.frames += chs[0].length; } };
  try {
    if (!ctx.audioWorklet || typeof AudioWorkletNode === 'undefined') throw new Error('pas de worklet');
    const url = URL.createObjectURL(new Blob([CAPTURE_WORKLET], { type: 'application/javascript' }));
    try { await ctx.audioWorklet.addModule(url); } finally { URL.revokeObjectURL(url); }
    const node = new AudioWorkletNode(ctx, 'mf-capture', { numberOfInputs: 1, numberOfOutputs: 1, outputChannelCount: [1] });
    node.port.onmessage = (e) => { if (e.data?.ch) push(e.data.ch); if (e.data?.end) cap.ended?.(); };
    src.connect(node).connect(sink);
    cap.node = node;
    cap.start = () => { cap.on = true; node.port.postMessage('start'); };
    cap.stop = () => new Promise((res) => {
      const done = () => { cap.on = false; res(); };
      cap.ended = done;
      node.port.postMessage('stop');
      setTimeout(done, 1500);
    });
  } catch {
    if (!ctx.createScriptProcessor) return null;
    const node = ctx.createScriptProcessor(4096, 2, 1);
    node.onaudioprocess = (e) => { const b = e.inputBuffer; push(Array.from({ length: b.numberOfChannels }, (_, c) => b.getChannelData(c).slice())); };
    src.connect(node).connect(sink);
    cap.node = node;
    cap.start = () => { cap.on = true; };
    cap.stop = async () => { cap.on = false; };
  }
  return cap;
}

// Une seule piste (la voix) : micro stéréo → moyenne, ou le seul côté qui capte
// (carte son avec le micro branché sur une entrée).
function captureToMono(cap) {
  const n = cap.frames;
  const chCount = Math.max(1, ...cap.chunks.map((c) => c.length));
  const energy = new Array(chCount).fill(0);
  for (const ck of cap.chunks) for (let c = 0; c < chCount; c++) { const d = ck[c] || ck[0]; for (let i = 0; i < d.length; i++) energy[c] += d[i] * d[i]; }
  const loud = energy.indexOf(Math.max(...energy));
  const solo = chCount === 1 || energy.some((e, c) => c !== loud && e < energy[loud] * 0.05);
  const out = new Float32Array(n);
  let o = 0;
  for (const ck of cap.chunks) {
    const len = ck[0].length;
    if (solo) out.set(ck[loud] || ck[0], o);
    else for (let i = 0; i < len; i++) { let v = 0; for (let c = 0; c < chCount; c++) v += (ck[c] || ck[0])[i]; out[o + i] = v / chCount; }
    o += len;
  }
  return out;
}

// Micro brut : pas d'anti-écho, pas de réduction de bruit, pas de gain auto.
// L'anti-écho (option, sans écouteurs) passe le micro en mode « appel » et abîme la voix.
const micConstraints = (echo) => ({
  echoCancellation: !!echo, noiseSuppression: false, autoGainControl: false, voiceIsolation: false,
  sampleRate: { ideal: 48000 }, sampleSize: { ideal: 24 },
});

function recExt(mime) { return /mp4|aac|m4a/.test(mime) ? 'm4a' : /ogg/.test(mime) ? 'ogg' : /wav/.test(mime) ? 'wav' : 'webm'; }
function pickMime() {
  if (typeof MediaRecorder === 'undefined') return null;
  for (const m of ['audio/webm;codecs=opus', 'audio/mp4', 'audio/webm', 'audio/ogg;codecs=opus']) {
    try { if (MediaRecorder.isTypeSupported(m)) return m; } catch { /* navigateur ancien */ }
  }
  return '';
}

// Charge la prod dans le lecteur (sans forcément la lancer) et attend qu'il soit prêt.
async function loadBeat(item) {
  const vid = ytIdOf(item);
  if (player.vid !== vid || !player.frame || player.status === 'blocked') {
    if (player.item && player.vid === vid && player.status === 'blocked') player.item = null;
    playItem(item);
  }
  const ok = await waitFor(() => player.ready && player.loadedVid === vid && player.status !== 'blocked' && (player.state === 1 || player.state === 2 || player.state === 5 || player.state === 3), 12000);
  return ok && player.status !== 'blocked';
}
function seekBeat(t) {
  ytSend('seekTo', [Math.max(0, t), true]);
  player.time = Math.max(0, t);
  player.timeAt = performance.now();
}

// --- Enregistrement
async function startRec(item, { fromStart, countdown, echo }, ui) {
  if (rec.state !== 'idle') return;
  stopTake();
  const AC = window.AudioContext || window.webkitAudioContext;
  const mime = pickMime();
  if (!navigator.mediaDevices?.getUserMedia || (!AC && mime === null)) { toast('Ce navigateur ne sait pas enregistrer le micro'); return; }
  rec.state = 'arming';
  ui.update();
  // Contexte audio créé au toucher (sur iPhone il ne démarre que comme ça)
  try { rec.ctx = AC ? new AC({ latencyHint: 'interactive' }) : null; rec.ctx?.resume().catch(() => {}); } catch { rec.ctx = null; }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: micConstraints(echo) });
    if (rec.state !== 'arming') { stream.getTracks().forEach((t) => t.stop()); return; } // panneau fermé entre-temps
    rec.stream = stream;
  } catch (e) {
    releaseMic();
    rec.state = 'idle';
    ui.update();
    toast(e?.name === 'NotAllowedError' ? 'Micro refusé : autorise-le dans les réglages du navigateur (icône à gauche de l’adresse)' : 'Micro introuvable');
    return;
  }
  // Niveau du micro
  try {
    rec.cap = await setupCapture(rec.ctx, rec.stream);
  } catch { rec.cap = null; }
  if (rec.state !== 'arming') return;
  if (!rec.cap && mime === null) { cancelRec(); ui.update(); toast('Ce navigateur ne sait pas enregistrer le micro'); return; }
  try {
    if (!rec.ctx) throw new Error('pas de Web Audio');
    await rec.ctx.resume();
    rec.analyser = rec.ctx.createAnalyser();
    rec.analyser.fftSize = 1024;
    rec.ctx.createMediaStreamSource(rec.stream).connect(rec.analyser);
    const buf = new Float32Array(rec.analyser.fftSize);
    const loop = () => {
      rec.analyser.getFloatTimeDomainData(buf);
      let peak = 0;
      for (const v of buf) peak = Math.max(peak, Math.abs(v));
      ui.level(peak);
      rec.raf = requestAnimationFrame(loop);
    };
    loop();
  } catch { /* pas de vumètre, l'enregistrement marche quand même */ }

  ui.say('Chargement de la prod…');
  const loaded = await loadBeat(item);
  if (rec.state !== 'arming') return;
  if (!loaded) { cancelRec(); ui.update(); toast('La prod ne se lance pas ici : impossible d’enregistrer dessus'); return; }
  ytSend('pauseVideo');
  const start = fromStart ? 0 : Math.max(0, playerNow() - 2);
  seekBeat(start);
  if (countdown) {
    rec.state = 'count';
    for (const n of [3, 2, 1]) { ui.count(n); await wait(1000); if (rec.state !== 'count') return; }
    ui.count(0);
  }
  if (rec.state !== 'arming' && rec.state !== 'count') return;
  ytSend('setVolume', [beatVol()]);
  ytSend('playVideo');
  const started = await waitFor(() => isPlaying(), 8000);
  if (rec.state !== 'arming' && rec.state !== 'count') return;
  if (!started) { cancelRec(); ui.update(); toast('La prod ne démarre pas : réessaie'); return; }
  rec.chunks = [];
  rec.mime = mime;
  rec.beat = { id: ytIdOf(item), title: item.title || '', url: ytWatchUrl(item) };
  if (rec.cap) {
    rec.cap.start(); // PCM brut, sans perte
  } else {
    rec.recorder = mime ? new MediaRecorder(rec.stream, { mimeType: mime, audioBitsPerSecond: 320000 }) : new MediaRecorder(rec.stream);
    rec.recorder.ondataavailable = (e) => { if (e.data?.size) rec.chunks.push(e.data); };
    rec.recorder.start(250);
  }
  rec.offset = playerNow();
  rec.startAt = performance.now();
  rec.state = 'rec';
  rec.tick = setInterval(() => ui.time((performance.now() - rec.startAt) / 1000), 200);
  rec.autoStop = setTimeout(() => stopRec(ui), 10 * 60e3);
  ui.update();
  renderMini();
}

function releaseMic() {
  cancelAnimationFrame(rec.raf);
  clearInterval(rec.tick);
  clearTimeout(rec.autoStop);
  rec.stream?.getTracks().forEach((t) => t.stop());
  try { rec.cap?.node?.disconnect(); } catch { /* déjà débranché */ }
  try { rec.ctx?.close(); } catch { /* déjà fermé */ }
  Object.assign(rec, { stream: null, ctx: null, analyser: null, cap: null, raf: 0, tick: 0, autoStop: 0 });
}
function cancelRec() {
  if (rec.cap) rec.cap.on = false;
  try { if (rec.recorder?.state === 'recording') rec.recorder.stop(); } catch { /* déjà arrêté */ }
  releaseMic();
  rec.recorder = null;
  rec.state = 'idle';
  renderMini();
}

async function stopRec(ui) {
  if (rec.state === 'count' || rec.state === 'arming') { cancelRec(); ui?.update(); return null; }
  if (rec.state !== 'rec') return null;
  rec.state = 'saving';
  let duration = (performance.now() - rec.startAt) / 1000;
  let blob;
  if (rec.cap) {
    const cap = rec.cap;
    await cap.stop();
    ytSend('pauseVideo');
    ytSend('setVolume', [100]);
    player.state = 2;
    releaseMic();
    const mono = captureToMono(cap);
    duration = mono.length / cap.rate;
    blob = mono.length ? encodeWav([mono], cap.rate) : new Blob([]);
  } else {
    const done = new Promise((r) => { rec.recorder.onstop = r; });
    try { rec.recorder.stop(); } catch { /* déjà arrêté */ }
    await Promise.race([done, wait(3000)]);
    ytSend('pauseVideo');
    ytSend('setVolume', [100]);
    player.state = 2;
    releaseMic();
    blob = new Blob(rec.chunks, { type: rec.recorder?.mimeType || rec.mime || 'audio/webm' });
  }
  rec.recorder = null;
  rec.state = 'idle';
  renderMini();
  if (duration < 1 || !blob.size) { ui?.update(); toast('Prise trop courte'); return null; }
  const all = await recStore.all();
  const n = all.filter((r) => r.beatId === rec.beat.id).length + 1;
  const r = { id: `rec-${Date.now().toString(36)}`, at: Date.now(), beatId: rec.beat.id, beatTitle: rec.beat.title, beatUrl: rec.beat.url, offset: rec.offset, duration, mime: blob.type, blob, name: `Prise ${n}` };
  const m = await measureTake(r);
  r.peak = m.peak;
  r.autoGain = m.autoGain;
  r.gain = m.autoGain; // voix montée automatiquement, sans saturer
  await recStore.put(r);
  toast(`${r.name} enregistrée`);
  ui?.update();
  ui?.refresh();
  return r;
}

// --- Réécoute calée sur la prod
function stopTake() {
  if (!take.audio) return;
  clearInterval(take.sync);
  take.audio.pause();
  URL.revokeObjectURL(take.url);
  Object.assign(take, { id: null, audio: null, url: '', sync: 0, beatId: null, duration: 0 });
  if (isPlaying()) { ytSend('pauseVideo'); player.state = 2; }
  ytSend('setVolume', [100]);
  renderMini();
  $$('.take-play').forEach((b) => { b.classList.remove('on'); b.replaceChildren(icon('play')); b.setAttribute('aria-label', 'Réécouter sur la prod'); });
}
function updateTakeUi(id) {
  const r0 = $(`.take-row[data-take="${id}"]`);
  if (!r0) return;
  const dur = Number(r0.dataset.dur) || 0;
  const t = Math.min(dur, takePos.get(id) || 0);
  $$(`.take-row[data-take="${id}"]`).forEach((row) => {
    const pctPos = dur ? (t / dur) * 100 : 0;
    row.querySelector('.take-fill').style.width = `${pctPos}%`;
    row.querySelector('.take-knob').style.left = `${pctPos}%`;
    row.querySelector('.take-time').textContent = `${fmtDur(t)} / ${fmtDur(dur)}`;
    row.querySelector('.take-bar').setAttribute('aria-valuenow', String(Math.round(t)));
  });
}
// Aller à un moment de la prise (et de la prod, au même endroit)
function seekTake(r, t, btn) {
  const dur = r.duration || 0;
  t = Math.max(0, Math.min(Math.max(0, dur - 0.05), t));
  takePos.set(r.id, t);
  updateTakeUi(r.id);
  if (take.id === r.id && take.audio) {
    seekBeat(r.offset + t - recLatency());
    take.audio.currentTime = t;
  } else if (btn) {
    playTake(r, btn, t);
  }
}
async function playTake(r, btn, startAt = null) {
  if (take.id === r.id && startAt == null) { stopTake(); return; } // pause : la position est gardée
  stopTake();
  if (rec.state !== 'idle') return;
  let from = startAt ?? takePos.get(r.id) ?? 0;
  if (from >= (r.duration || 0) - 0.3) from = 0;
  const beat = { id: r.beatId, url: r.beatUrl, title: r.beatTitle };
  $$(`.take-row[data-take="${r.id}"] .take-play`).forEach((b) => { b.classList.add('on'); b.replaceChildren(icon('pause')); b.setAttribute('aria-label', 'Pause'); });
  take.id = r.id;
  take.duration = r.duration || 0;
  if (!(await loadBeat(beat))) { stopTake(); toast('La prod ne se lance pas : réécoute impossible'); return; }
  if (take.id !== r.id) return;
  ytSend('pauseVideo');
  seekBeat(r.offset + from - recLatency());
  // La prise avec son volume, calculée comme le .wav téléchargé (sans perte)
  let blob = r.blob;
  try { blob = await renderTake(r); } catch { /* fichier d'origine, volume normal */ }
  if (take.id !== r.id) return;
  take.url = URL.createObjectURL(blob);
  take.audio = new Audio(take.url);
  ytSend('setVolume', [beatVol()]);
  take.offset = r.offset;
  take.beatId = r.beatId;
  take.audio.addEventListener('ended', () => { if (take.id === r.id) { takePos.set(r.id, 0); stopTake(); updateTakeUi(r.id); } });
  ytSend('playVideo');
  await waitFor(() => isPlaying(), 8000);
  if (take.id !== r.id || !take.audio) return;
  take.audio.currentTime = Math.max(0, playerNow() - r.offset + recLatency());
  try { await take.audio.play(); } catch { stopTake(); toast('Lecture impossible'); return; }
  // Garde la voix calée sur la prod (pause, reprise, petits décalages).
  take.sync = setInterval(() => {
    const a = take.audio;
    if (!a) return;
    if (player.vid !== take.beatId) { stopTake(); return; }
    if (!isPlaying()) { if (!a.paused) a.pause(); return; }
    const target = playerNow() - take.offset + recLatency();
    if (target < 0) return;
    if (a.paused && !a.ended) a.play().catch(() => {});
    if (Math.abs(a.currentTime - target) > 0.12) a.currentTime = target;
    takePos.set(take.id, a.currentTime);
    updateTakeUi(take.id);
    if (take.duration && a.currentTime >= take.duration - 0.05) { takePos.set(take.id, 0); const id = take.id; stopTake(); updateTakeUi(id); }
  }, 250);
}

// La prise avec son volume (gain + limiteur de crêtes), en .wav 24 bits
async function renderTake(r) {
  const d = await decodeTake(r);
  const chans = d.chans.map((c) => c.slice());
  return encodeWav(limitInPlace(chans, d.rate, r.gain ?? 1), d.rate);
}
// Volume changé pendant la réécoute : la prise est recalculée et reprend au même endroit
let regainT = 0;
function regainTake(r) {
  clearTimeout(regainT);
  regainT = setTimeout(async () => {
    if (take.id !== r.id || !take.audio) return;
    let blob;
    try { blob = await renderTake(r); } catch { return; }
    if (take.id !== r.id || !take.audio) return;
    const a = take.audio;
    const t = a.currentTime;
    const was = !a.paused;
    const old = take.url;
    take.url = URL.createObjectURL(blob);
    a.src = take.url;
    URL.revokeObjectURL(old);
    a.addEventListener('loadedmetadata', () => { a.currentTime = t; if (was) a.play().catch(() => {}); }, { once: true });
  }, 180);
}
async function downloadTake(r) {
  let blob = r.blob;
  let ext = recExt(r.mime);
  try { blob = await renderTake(r); ext = 'wav'; } catch { toast('Export WAV impossible ici : fichier d’origine téléchargé'); }
  const url = URL.createObjectURL(blob);
  const a = h('a', { href: url, download: `${displayTitle(r.beatTitle || 'Prod').slice(0, 60)} - ${r.name}.${ext}` });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 30e3);
}

function takeRow(r, refresh, { showBeat = false } = {}) {
  const playing = take.id === r.id;
  const play = h('button', { type: 'button', class: `icon-btn take-play${playing ? ' on' : ''}`, 'aria-label': playing ? 'Pause' : 'Réécouter sur la prod' }, icon(playing ? 'pause' : 'play'));
  play.addEventListener('click', () => playTake(r, play));
  // Barre de progression (cliquable / glissable) + début / fin
  const dur = r.duration || 0;
  const bar = h('div', { class: 'take-bar', role: 'slider', tabindex: '0', 'aria-label': `Position dans ${r.name}`, 'aria-valuemin': '0', 'aria-valuemax': String(Math.round(dur)), 'aria-valuenow': '0' },
    h('i', { class: 'take-fill' }), h('b', { class: 'take-knob' }));
  const posAt = (x) => { const b = bar.getBoundingClientRect(); return Math.max(0, Math.min(1, (x - b.left) / b.width)) * dur; };
  bar.addEventListener('pointerdown', (e) => {
    e.preventDefault();
    bar.setPointerCapture?.(e.pointerId);
    takePos.set(r.id, posAt(e.clientX));
    updateTakeUi(r.id);
    const move = (ev) => { takePos.set(r.id, posAt(ev.clientX)); updateTakeUi(r.id); };
    const up = (ev) => { bar.removeEventListener('pointermove', move); bar.removeEventListener('pointerup', up); bar.removeEventListener('pointercancel', up); seekTake(r, posAt(ev.clientX), play); };
    bar.addEventListener('pointermove', move);
    bar.addEventListener('pointerup', up);
    bar.addEventListener('pointercancel', up);
  });
  bar.addEventListener('keydown', (e) => {
    const step = e.key === 'ArrowRight' ? 5 : e.key === 'ArrowLeft' ? -5 : 0;
    if (!step) return;
    e.preventDefault();
    seekTake(r, (takePos.get(r.id) || 0) + step, take.id === r.id ? play : null);
  });
  const toStart = h('button', { type: 'button', class: 'icon-btn take-jump', 'aria-label': 'Aller au début', title: 'Début', onclick: () => seekTake(r, 0, take.id === r.id ? play : null) }, '⏮');
  const toEnd = h('button', { type: 'button', class: 'icon-btn take-jump', 'aria-label': 'Aller à la fin (dernières secondes)', title: 'Fin', onclick: () => seekTake(r, Math.max(0, dur - Math.min(5, dur * 0.2)), play) }, '⏭');
  let armed = null;
  const del = h('button', { type: 'button', class: 'icon-btn', 'aria-label': 'Supprimer la prise' }, icon('trash'));
  del.addEventListener('click', async () => {
    if (!armed) { del.classList.add('armed'); del.title = 'Clique encore pour supprimer'; armed = setTimeout(() => { del.classList.remove('armed'); armed = null; }, 3000); return; }
    clearTimeout(armed);
    if (take.id === r.id) stopTake();
    await recStore.del(r.id);
    toast(`${r.name} supprimée`);
    refresh();
  });
  // Volume de la voix (échelle 0–300 %, 150 % = gain ×3,1)
  const pct = (g) => `${gainToPct(g)} %`;
  const vol = h('input', { type: 'range', min: '0', max: String(MAX_PCT), step: '5', 'aria-label': `Volume de la voix (${r.name})` });
  vol.value = String(gainToPct(r.gain ?? 1));
  const volTxt = h('span', { class: 'take-vol-val mono' }, pct(r.gain ?? 1));
  let saveT = null;
  const setGain = (g) => {
    r.gain = Math.max(0, Math.min(MAX_GAIN, g));
    vol.value = String(gainToPct(r.gain));
    volTxt.textContent = pct(r.gain);
    if (take.id === r.id) regainTake(r);
    clearTimeout(saveT);
    saveT = setTimeout(() => recStore.put(r), 400);
  };
  vol.addEventListener('input', () => setGain(Number(vol.value) * GAIN_PER_PCT));
  const auto = h('button', { type: 'button', class: 'ghost take-auto', title: 'Voix le plus fort possible sans saturer' }, 'Auto');
  auto.addEventListener('click', async () => {
    if (r.autoGain == null) { const m = await measureTake(r); r.peak = m.peak; r.autoGain = m.autoGain; }
    setGain(r.autoGain);
    toast(`Voix réglée à ${pct(r.autoGain)}`);
  });
  const row = h('div', { class: 'take-row', 'data-take': r.id, 'data-dur': String(dur) },
    h('div', { class: 'take-top' }, play,
      h('div', { class: 'take-main' },
        h('b', {}, r.name, showBeat ? h('span', { class: 'take-beat' }, ` · ${displayTitle(r.beatTitle || '')}`) : null),
        h('span', {}, `${fmtDur(r.duration)} · ${new Date(r.at).toLocaleString('fr-FR', { dateStyle: 'short', timeStyle: 'short' })}`)),
      h('button', { type: 'button', class: 'icon-btn', 'aria-label': 'Télécharger la prise (.wav, avec le volume réglé)', title: 'Télécharger en .wav (avec le volume réglé)', onclick: () => downloadTake(r) }, icon('down')),
      del),
    h('div', { class: 'take-seek' }, toStart, bar, h('span', { class: 'take-time mono' }, ''), toEnd),
    h('div', { class: 'take-vol' }, h('span', {}, icon('mic'), 'Voix'), vol, volTxt, auto));
  requestAnimationFrame(() => updateTakeUi(r.id));
  return row;
}

// --- Panneau Rec
function openStudio(item) {
  if (!WEB) return;
  const vid = ytIdOf(item);
  if (!vid) { toast('Pas de vidéo YouTube pour cette prod'); return; }
  let r0 = null;
  try { r0 = analyzed(item, session?.plan || null); } catch { /* sans analyse */ }
  const opts = local.get('recOpts', { fromStart: true, countdown: true, echo: false });
  const fromStart = h('input', { type: 'checkbox', id: 'recFromStart' });
  fromStart.checked = opts.fromStart !== false;
  const countdown = h('input', { type: 'checkbox', id: 'recCountdown' });
  countdown.checked = opts.countdown !== false;
  const echo = h('input', { type: 'checkbox', id: 'recEcho' });
  echo.checked = opts.echo === true;
  const saveOpts = () => local.set('recOpts', { fromStart: fromStart.checked, countdown: countdown.checked, echo: echo.checked });
  fromStart.addEventListener('change', saveOpts);
  countdown.addEventListener('change', saveOpts);
  echo.addEventListener('change', saveOpts);

  const big = h('button', { type: 'button', class: 'rec-big', 'aria-label': 'Enregistrer' }, h('span', { class: 'rec-dot' }));
  const timer = h('div', { class: 'rec-time' }, '0:00');
  const status = h('p', { class: 'rec-status' }, 'Touche le bouton rouge pour rapper sur la prod.');
  const meter = h('div', { class: 'rec-meter' }, h('i'));
  const counter = h('div', { class: 'rec-count', hidden: true });
  const list = h('div', { class: 'take-list' });
  const lat = h('input', { type: 'range', id: 'recLatency', min: '-0.5', max: '0.5', step: '0.01' });
  lat.value = String(recLatency());
  const latVal = h('span', { class: 'mono' }, `${Math.round(recLatency() * 1000)} ms`);
  lat.addEventListener('input', () => { local.set('recLatency', Number(lat.value)); latVal.textContent = `${Math.round(Number(lat.value) * 1000)} ms`; });

  const ui = {
    update() {
      const st = rec.state;
      big.classList.toggle('live', st === 'rec');
      big.classList.toggle('busy', st === 'arming' || st === 'count' || st === 'saving');
      big.setAttribute('aria-label', st === 'rec' ? 'Arrêter et garder la prise' : 'Enregistrer');
      big.replaceChildren(st === 'rec' ? icon('stop') : h('span', { class: 'rec-dot' }));
      if (st === 'idle') { status.textContent = 'Touche le bouton rouge pour rapper sur la prod.'; timer.textContent = '0:00'; meter.firstChild.style.width = '0%'; counter.hidden = true; }
      if (st === 'rec') status.textContent = 'Ça enregistre… Touche ■ pour arrêter et garder la prise.';
      if (st === 'saving') status.textContent = 'J’enregistre la prise…';
      fromStart.disabled = countdown.disabled = echo.disabled = st !== 'idle';
    },
    say(t) { status.textContent = t; },
    level(p) { meter.firstChild.style.width = `${Math.min(100, Math.round(p * 140))}%`; meter.classList.toggle('hot', p > 0.95); },
    count(n) { counter.hidden = !n; counter.textContent = n ? String(n) : ''; if (n) status.textContent = 'Prépare-toi…'; },
    time(s) { timer.textContent = fmtDur(s); },
    async refresh() {
      const rows = (await recStore.all()).filter((r) => r.beatId === vid);
      list.replaceChildren(...(rows.length ? rows.map((r) => takeRow(r, ui.refresh)) : [h('p', { class: 'muted' }, 'Pas encore de prise sur cette prod.')]));
    },
  };
  big.addEventListener('click', () => {
    if (rec.state === 'idle') startRec(item, { fromStart: fromStart.checked, countdown: countdown.checked, echo: echo.checked }, ui);
    else stopRec(ui);
  });

  openDrawer('Rec sur la prod', [
    h('div', { class: 'rec-beat' }, h('b', {}, displayTitle(item.title || '')), h('span', {}, [r0?.bpm ? `${r0.bpm} BPM` : null, r0?.key].filter(Boolean).join(' · ') || 'Prod YouTube')),
    h('div', { class: 'rec-stage' }, counter, big, timer, meter, status),
    (() => {
      const bv = h('input', { type: 'range', id: 'recBeatVol', min: '0', max: '100', step: '1', 'aria-label': 'Volume de la prod' });
      bv.value = String(beatVol());
      const bvTxt = h('span', { class: 'mono' }, `${beatVol()} %`);
      bv.addEventListener('input', () => { local.set('recBeatVol', Number(bv.value)); bvTxt.textContent = `${bv.value} %`; if (take.id || rec.state === 'rec') ytSend('setVolume', [Number(bv.value)]); });
      return h('div', { class: 'take-vol beat-vol' }, h('span', {}, icon('play'), 'Prod'), bv, bvTxt);
    })(),
    h('div', { class: 'rec-opts' },
      h('label', { for: 'recFromStart' }, fromStart, 'Repartir du début de la prod'),
      h('label', { for: 'recCountdown' }, countdown, 'Décompte 3 s'),
      h('label', { for: 'recEcho', title: 'Seulement sans écouteurs : retire la prod du micro, mais abîme la voix' }, echo, 'Anti-écho (sans écouteurs)')),
    h('p', { class: 'hint' }, 'Mets des écouteurs : la voix est enregistrée brute, sans perte (WAV 24 bits), sans réduction de bruit. Sans écouteurs, le micro capte aussi la prod (l’option anti-écho l’enlève, mais abîme la voix). À la réécoute, ta voix repart calée sur la prod.'),
    h('div', { class: 'd-sec' }, h('h4', {}, 'Tes prises sur cette prod'), list),
    h('details', { class: 'rec-adv' }, h('summary', {}, 'Voix en avance ou en retard sur la prod ?'),
      h('div', { class: 'rec-lat' }, h('span', {}, 'Calage'), lat, latVal),
      h('p', { class: 'hint' }, 'Si ta voix tombe à côté du temps, décale-la ici (s’applique à la réécoute de toutes tes prises).')),
    h('button', { type: 'button', class: 'link', onclick: () => { closeDrawer(); showView('recs'); } }, 'Toutes mes recs →'),
  ]);
  drawerOnClose = () => { if (rec.state === 'rec') stopRec(null).then(() => renderRecs()); else if (rec.state !== 'idle') cancelRec(); };
  ui.update();
  ui.refresh();
}

async function renderRecs() {
  const box = $('#recsList');
  if (!box) return;
  const rows = await recStore.all();
  if (!rows.length) {
    box.replaceChildren(h('div', { class: 'empty' }, h('div', { class: 'empty-ico' }, icon('mic')), h('h3', {}, 'Aucune rec pour l’instant'),
      h('p', {}, 'Lance une prod, touche « Rec » dans la barre du bas, et rappe dessus.'),
      h('button', { type: 'button', class: 'primary', onclick: () => showView('search') }, 'Trouver une prod')));
    return;
  }
  const groups = new Map();
  for (const r of rows) { if (!groups.has(r.beatId)) groups.set(r.beatId, []); groups.get(r.beatId).push(r); }
  box.replaceChildren(...[...groups.values()].map((g) => h('div', { class: 'rec-group' },
    h('div', { class: 'rec-group-head' }, h('b', {}, displayTitle(g[0].beatTitle || 'Prod')),
      h('button', { type: 'button', class: 'ghost', onclick: () => openStudio({ id: g[0].beatId, url: g[0].beatUrl, title: g[0].beatTitle }) }, icon('mic'), 'Nouvelle prise')),
    ...g.map((r) => takeRow(r, renderRecs)))));
}

let drawerOnClose = null; // nettoyage du panneau ouvert (ex. arrêter un enregistrement)
function runDrawerCleanup() { const f = drawerOnClose; drawerOnClose = null; try { f?.(); } catch (e) { console.error(e); } }
function openDrawer(title, nodes) {
  runDrawerCleanup();
  delete $('#drawer').dataset.item;
  lastFocus = document.activeElement;
  $('#drawerTitle').textContent = title;
  $('#drawerBody').replaceChildren(...nodes.filter(Boolean));
  $('#drawerBody').scrollTop = 0;
  $('#drawer').classList.add('open');
  $('#drawer').setAttribute('aria-hidden', 'false');
  $('#scrim').classList.add('open');
  setTimeout(() => $('#drawerClose').focus(), 60);
}
function closeDrawer() {
  runDrawerCleanup();
  $('#drawer').classList.remove('open');
  $('#drawer').setAttribute('aria-hidden', 'true');
  $('#scrim').classList.remove('open');
  lastFocus?.focus?.();
}
$('#drawerClose').addEventListener('click', closeDrawer);
$('#scrim').addEventListener('click', closeDrawer);
document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && $('#drawer').classList.contains('open')) closeDrawer(); });

function verdictBox(L, unread) {
  const v = verdictCopy(L, unread);
  return h('div', { class: `verdict cat-${L.category}` }, h('span', { class: 'verdict-ico', 'aria-hidden': 'true' }, CAT_ICON[L.category]), h('div', {}, h('b', {}, v.t), h('span', {}, v.s)));
}
function beatDetails(item, r, terms = []) {
  const L = r.license;
  const facts = [
    r.bpm ? h('span', { class: `fact mono${r.bpmTb ? ' tb' : ''}`, title: r.bpmTb ? 'Trouvé avec Tunebat' : null }, `${r.bpm} BPM`, r.bpmTb ? h('small', {}, ' · Tunebat') : null) : null,
    r.key ? h('span', { class: `fact mono${r.keyTb ? ' tb' : ''}`, title: r.keyTb ? 'Trouvé avec Tunebat' : null }, r.key, r.keyTb ? h('small', {}, ' · Tunebat') : null) : null,
    item.duration > 0 ? h('span', { class: 'fact mono' }, fmtTime(item.duration)) : null,
    L.creditRequired ? h('span', { class: 'fact' }, 'Crédit obligatoire') : null,
    ...(r.styles || []).map((s) => h('span', { class: 'fact' }, s.label)),
  ].filter(Boolean);
  return [
    facts.length ? h('div', { class: 'd-sec' }, h('h4', {}, 'La prod'), h('div', { class: 'facts' }, facts)) : null,
    h('div', { class: `d-sec cat-${L.category}` }, h('h4', {}, 'Pourquoi ce verdict'),
      h('ul', { class: 'reasons' }, L.reasons.map((x) => h('li', {}, x.text, x.quote ? h('q', {}, highlight(x.quote, terms)) : null)))),
    item.description ? h('div', { class: `d-sec cat-${L.category}` }, h('h4', {}, 'Description de la vidéo'), h('pre', { class: 'desc' }, highlight(item.description, terms))) : null,
  ];
}
function openBeat(item, plan) {
  const r = analyzed(item, plan);
  if (!r.bpm || !r.key) tbLookup(item);
  const saveBtn = h('button', { type: 'button', class: `ghost${isSaved(item.id) ? ' on' : ''}` }, icon('heart'), isSaved(item.id) ? 'Dans tes favoris' : 'Ajouter aux favoris');
  saveBtn.addEventListener('click', () => {
    const on = toggleSaved(item);
    saveBtn.classList.toggle('on', on);
    saveBtn.replaceChildren(icon('heart'), on ? 'Dans tes favoris' : 'Ajouter aux favoris');
  });
  const claude = sampleFn && item.description ? h('div', { class: 'claude-ask' }, 'Une tournure bizarre ? ', h('button', { type: 'button', class: 'link', onclick: (e) => askClaude(item, e.currentTarget.parentElement) }, 'Demander l’avis de Claude')) : null;
  openDrawer('Détails de la prod', [
    verdictBox(r.license, item.status === 'unread'),
    partialNote(item),
    h('div', {}, h('h3', { class: 'd-title' }, item.title), h('p', { class: 'd-meta' }, [item.views ? `${item.views} vues` : null, item.likeCount != null ? `${fmtViews(item.likeCount)} likes` : null, ratioOf(item) != null ? `ratio ${fmtPct(ratioOf(item))}` : null, item.age].filter(Boolean).join(' · ') || 'YouTube')),
    h('div', { class: 'd-actions' },
      WEB && ytIdOf(item) ? h('button', { type: 'button', class: 'primary', onclick: () => playItem(item) }, icon('play'), 'Écouter') : null,
      !WEB ? h('a', { class: 'primary', href: ytWatchUrl(item), target: '_blank', rel: 'noopener' }, icon('play'), 'Écouter sur YouTube') : null,
      saveBtn,
      WEB && ytIdOf(item) ? h('button', { type: 'button', class: 'ghost', onclick: () => openStudio(item) }, icon('mic'), 'Rec dessus') : null,
      WEB && ytIdOf(item) ? h('button', { type: 'button', class: 'ghost', onclick: () => sendToPc(item) }, icon('down'), 'Sur mon PC') : null,
      item.url ? h('button', { type: 'button', class: 'ghost', onclick: () => copyText(item.url) }, 'Copier le lien') : null),
    WEB ? h('a', { class: 'link d-yt', href: ytWatchUrl(item), target: '_blank', rel: 'noopener' }, 'Ouvrir sur YouTube', icon('ext')) : null,
    ...beatDetails(item, r, findTerms()),
    claude,
  ]);
  $('#drawer').dataset.item = item.id; // pour l'actualiser quand Tunebat répond
}

// ---------------------------------------------------------------------------
// Parallel Search (connecteur) : page de résultats YouTube + pages vidéo

const SERVER = 'Parallel Search';
const SID = local.get('sid', null) || (() => { const s = `melofinds-${Array.from(crypto.getRandomValues(new Uint8Array(16)), (b) => b.toString(16).padStart(2, '0')).join('')}`; local.set('sid', s); return s; })();
let mcpPromise = null;
const getMcp = () => (mcpPromise ||= (window.claude?.use ? window.claude.use('mcp').catch(() => null) : Promise.resolve(null)));

async function pcall(tool, input) {
  const mcp = await getMcp();
  if (!mcp) throw { code: 'not_granted' };
  const res = await mcp.callTool(SERVER, tool, { ...input, session_id: SID }, { cache: { staleTime: 6 * 3600e3, gcTime: 24 * 3600e3 } });
  const p = res?.payload;
  if (p && typeof p === 'object') return p;
  try { return JSON.parse((res?.content || []).find((b) => b.type === 'text')?.text || '{}'); } catch { return {}; }
}
const resultText = (r) => [...(r.excerpts || []), r.full_content || ''].join('\n');
const cleanTitle = cleanYtTitle;

// Page de résultats YouTube → vidéos (parseResultsPage : moteur)
async function listVideos(query) {
  const url = `https://www.youtube.com/results?search_query=${encodeURIComponent(query)}&sp=EgIQAQ%253D%253D`;
  const p = await pcall('web_fetch', { urls: [url], objective: 'Lister toutes les vidéos de la page de résultats : titre exact et lien de chacune.' });
  return parseResultsPage((p.results || []).map(resultText).join('\n'));
}
// Recherche web : vidéos YouTube avec un extrait de description
async function searchSnippets(queries, objective) {
  const p = await pcall('web_search', { objective, search_queries: queries.slice(0, 5) });
  return (p.results || []).map((r) => ({ id: youtubeId(r.url), title: cleanTitle(r.title), text: (r.excerpts || []).join('\n') })).filter((x) => x.id);
}

// Pages vidéo → description (cleanDescription / usefulDescription : moteur)
const useful = usefulDescription;

async function readPages(ids, host) {
  const urls = ids.map((id) => `https://${host}/watch?v=${id}`);
  const p = await pcall('web_fetch', { urls, objective: 'Texte complet de la description de la vidéo écrit par le producteur : licence, free for profit, limite de streams, Spotify, achat, crédit, BPM, tonalité.' });
  const out = new Map();
  for (const r of p.results || []) {
    const id = youtubeId(r.url);
    if (id) { const text = resultText(r); out.set(id, { title: cleanTitle(r.title), text, stats: parseWatchStats(text) }); }
  }
  return out;
}

async function pool(items, limit, fn) {
  let i = 0;
  const workers = Array.from({ length: Math.min(limit, items.length) }, async () => {
    while (i < items.length) { const k = i++; await fn(items[k], k); }
  });
  await Promise.all(workers);
}
const chunk = (arr, n) => Array.from({ length: Math.ceil(arr.length / n) }, (_, i) => arr.slice(i * n, i * n + n));

function errorKind(e) {
  switch (e?.code) {
    case 'server_not_connected': case 'server_not_found': case 'selection_required': return 'connect';
    case 'not_in_manifest': case 'approval_required': case 'consent_required': case 'blocked_by_policy': return 'denied';
    case 'needs_reauth': return 'reauth';
    case 'yt_nokey': return 'ytkey';
    case 'piped_down': return 'piped';
    case 'yt_key': return 'ytkey-bad';
    case 'yt_quota': return 'quota';
    case 'yt_disabled': return 'ytdisabled';
    case 'yt_referer': return 'ytreferer';
    case 'not_granted': case 'capability_disabled': case 'capability_removed': return 'unavailable';
    default: return null;
  }
}

// ---------------------------------------------------------------------------
// Version web : YouTube Data API v3 (clé gratuite de l'utilisateur, gardée dans
// ce navigateur). search.list → 50 vidéos par recherche, videos.list → la
// description COMPLÈTE de chaque vidéo (rien d'illisible).

const ytKey = () => String(local.get('ytKey', '') || '');
async function ytApi(path, params) {
  const url = new URL(`https://www.googleapis.com/youtube/v3/${path}`);
  for (const [k, v] of Object.entries({ ...params, key: ytKey() })) url.searchParams.set(k, v);
  let res;
  try { res = await fetch(url); } catch { throw { code: 'yt_network', message: 'Pas de connexion à YouTube.' }; }
  const body = await res.json().catch(() => ({}));
  if (res.ok) return body;
  const err = body?.error || {};
  const reason = `${err.errors?.[0]?.reason || ''} ${err.status || ''} ${(err.details || []).map((d) => d.reason || '').join(' ')}`;
  const msg = String(err.message || res.statusText || '');
  let code = 'yt_error';
  if (/quotaExceeded|dailyLimitExceeded|rateLimitExceeded/i.test(reason)) code = 'yt_quota';
  else if (/REFERER|referer/i.test(`${reason} ${msg}`)) code = 'yt_referer';
  else if (/accessNotConfigured|SERVICE_DISABLED|has not been used|is disabled/i.test(`${reason} ${msg}`)) code = 'yt_disabled';
  else if (/keyInvalid|API_KEY_INVALID|API key not valid|badRequest/i.test(`${reason} ${msg}`)) code = 'yt_key';
  throw { code, message: msg };
}
function decodeHtml(s) { const t = document.createElement('textarea'); t.innerHTML = s; return t.value; }
function fmtViews(n) {
  n = Number(n);
  if (!Number.isFinite(n)) return null;
  if (n < 1000) return String(n);
  if (n < 1e6) return `${(n / 1e3).toFixed(n < 1e4 ? 1 : 0).replace(/\.0$/, '').replace('.', ',')} k`;
  return `${(n / 1e6).toFixed(n < 1e7 ? 1 : 0).replace(/\.0$/, '').replace('.', ',')} M`;
}
function applyStats(item, st) {
  if (!st) return;
  if (st.likes != null && st.likes >= 0) item.likeCount = st.likes;
  if (st.views != null && st.views > 0) { item.viewCount = st.views; item.views = fmtViews(st.views); }
}
const ratioOf = (item) => likeRatio(item?.likeCount, item?.viewCount ?? parseCount(item?.views));
const fmtPct = (x) => `${x >= 10 ? Math.round(x) : x.toFixed(1).replace('.', ',')} %`;
function ageFrom(iso) {
  const t = Date.parse(iso || '');
  if (!t) return null;
  const d = Math.max(0, Math.floor((Date.now() - t) / 864e5));
  if (d < 1) return 'aujourd’hui';
  if (d < 7) return `il y a ${d} j`;
  if (d < 31) return `il y a ${Math.floor(d / 7)} sem.`;
  if (d < 365) return `il y a ${Math.floor(d / 30.4)} mois`;
  const y = Math.floor(d / 365);
  return `il y a ${y} an${y > 1 ? 's' : ''}`;
}

// « PT2M20S » → 140 (secondes)
function isoDuration(s) {
  const m = String(s || '').match(/^P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?$/);
  return m ? (+m[1] || 0) * 86400 + (+m[2] || 0) * 3600 + (+m[3] || 0) * 60 + (+m[4] || 0) : 0;
}
// « 2:20 », « 2m20 », « 140 » (secondes si > 10, sinon minutes) → secondes
function parseMinDur(text) {
  const t = String(text || '').trim().toLowerCase().replace(',', '.');
  let m = t.match(/^(\d{1,2})\s*[:mh']\s*(\d{1,2})?\s*s?$/);
  if (m) return Math.min(3600, +m[1] * 60 + (+m[2] || 0));
  m = t.match(/^(\d+(?:\.\d+)?)$/);
  if (m) { const v = +m[1]; return Math.round(v > 10 ? v : v * 60); }
  return null;
}

async function webSearch(queries, add, before) {
  // Sans clé : Piped. Avec une clé YouTube : l'API officielle (description complète + likes).
  if (!ytKey()) return pipedSearch(queries, add, before);
  let doneQ = 0;
  let failures = 0;
  let firstErr = null;
  await pool(queries, 4, async (q) => {
    try {
      const b = await ytApi('search', { part: 'snippet', type: 'video', videoEmbeddable: 'true', maxResults: '50', q });
      for (const it of b.items || []) if (it.id?.videoId) add({ id: it.id.videoId, title: decodeHtml(it.snippet?.title || '') }, q);
    } catch (e) { if (errorKind(e)) throw e; failures++; firstErr ||= e; }
    doneQ++;
    setStatus(`Je cherche sur YouTube… ${session.items.size - before} vidéos trouvées`, 0.08 + 0.3 * (doneQ / queries.length));
  });
  const pending = [...session.items.values()].filter((i) => i.status === 'pending').slice(0, LIMITS().read);
  if (!pending.length) {
    if (failures === queries.length && firstErr) throw firstErr;
    setStatus('Aucune nouvelle vidéo pour ces recherches. Essaie d’autres mots.', 1, true);
    return false;
  }
  let read = 0;
  const total = pending.length;
  const progress = () => setStatus(`${total} vidéos trouvées · je lis les descriptions (${read}/${total})`, 0.4 + 0.6 * (read / total));
  progress();
  await pool(chunk(pending, 50), 4, async (batch) => {
    let found = new Map();
    try {
      const b = await ytApi('videos', { part: 'snippet,statistics,contentDetails', id: batch.map((i) => i.id).join(','), maxResults: '50' });
      found = new Map((b.items || []).map((v) => [v.id, v]));
    } catch (e) { if (errorKind(e)) throw e; }
    for (const item of batch) {
      const v = found.get(item.id);
      if (v) {
        item.title = v.snippet?.title || item.title;
        item.description = String(v.snippet?.description || '').slice(0, DESC_MAX);
        applyStats(item, { views: parseCount(v.statistics?.viewCount), likes: parseCount(v.statistics?.likeCount) });
        item.age = ageFrom(v.snippet?.publishedAt);
        const dur = isoDuration(v.contentDetails?.duration);
        if (dur > 0) item.duration = dur;
        if (v.snippet?.channelTitle) item.channel = String(v.snippet.channelTitle).slice(0, 80);
        item.status = 'done';
      } else item.status = 'unread';
      read++;
    }
    progress();
    renderResults();
  });
  return true;
}

// ---------------------------------------------------------------------------
// Sans clé : Piped (https://docs.piped.video), un miroir libre de YouTube qui
// autorise les sites web à l'interroger. Plusieurs serveurs publics : on garde
// le dernier qui a marché, et on passe au suivant si l'un tombe.
// En octobre 2026, la recherche marche (titre, vues, date, début de description) ;
// la description complète (/streams) est souvent bloquée par YouTube : on la
// tente quand même et on s'arrête vite si elle ne passe pas.

const PIPED_DEFAULT = [
  'https://api.piped.private.coffee',
  'https://pipedapi.ducks.party',
  'https://pipedapi.kavin.rocks',
  'https://pipedapi.adminforge.de',
  'https://pipedapi.leptons.xyz',
  'https://pipedapi.nosebs.ru',
  'https://api.piped.yt',
  'https://pipedapi.drgns.space',
  'https://pipedapi.owo.si',
  'https://piped-api.codespace.cz',
  'https://pipedapi.darkness.services',
  'https://pipedapi.orangenet.cc',
  'https://piped-api.privacy.com.de',
  'https://pipedapi-libre.kavin.rocks',
];
const PIPED_LIST_URL = 'https://raw.githubusercontent.com/TeamPiped/documentation/main/content/docs/public-instances/index.md';

async function fetchJson(url, ms = 7000) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), ms);
  try {
    const res = await fetch(url, { signal: ctrl.signal, headers: { Accept: 'application/json' } });
    if (!res.ok) throw { code: 'http', status: res.status };
    const body = await res.json();
    if (body && typeof body === 'object' && body.error) throw { code: 'piped_error', message: String(body.message || body.error) };
    return body;
  } finally { clearTimeout(timer); }
}

// Liste des serveurs : la liste officielle (mise à jour 1 fois par jour) + nos valeurs par défaut.
let pipedListPromise = null;
async function pipedInstances() {
  const list = await (pipedListPromise ||= (async () => {
    const cached = local.get('pipedList', null);
    let list = PIPED_DEFAULT.slice();
    if (cached?.at && Date.now() - cached.at < 864e5 && Array.isArray(cached.list)) list = [...cached.list, ...list];
    else {
      try {
        const ctrl = new AbortController();
        const timer = setTimeout(() => ctrl.abort(), 5000);
        const md = await fetch(PIPED_LIST_URL, { signal: ctrl.signal }).then((r) => (r.ok ? r.text() : ''));
        clearTimeout(timer);
        const found = [...md.matchAll(/\|\s*(https:\/\/[a-z0-9.-]+)\s*\|/gi)].map((m) => m[1].replace(/\/$/, ''));
        if (found.length) { local.set('pipedList', { at: Date.now(), list: found }); list = [...found, ...list]; }
      } catch { /* liste par défaut */ }
    }
    return [...new Set(list)];
  })());
  // Ordre recalculé à chaque appel : le dernier serveur qui a marché d'abord,
  // ceux tombés en panne il y a moins de 30 min en dernier.
  const good = local.get('pipedGood', null);
  const bad = local.get('pipedBad', {}) || {};
  const down = (a) => ((bad[a] || 0) > Date.now() - 18e5 ? 1 : 0);
  return [...new Set([good, ...list].filter(Boolean))].sort((a, b) => (a === good ? -1 : b === good ? 1 : 0) || down(a) - down(b));
}
function markPiped(api, ok) {
  if (ok) { local.set('pipedGood', api); return; }
  const bad = local.get('pipedBad', {});
  bad[api] = Date.now();
  local.set('pipedBad', bad);
  if (local.get('pipedGood', null) === api) local.set('pipedGood', null);
}

// Appelle le premier serveur qui répond (en commençant par celui qui a marché).
async function pipedGet(path, { stick = true, only = null } = {}) {
  const list = only ? [only] : await pipedInstances();
  let lastErr = null;
  for (const api of list.slice(0, 8)) {
    try {
      const body = await fetchJson(`${api}${path}`);
      if (stick) markPiped(api, true);
      return { body, api };
    } catch (e) { lastErr = e; if (stick) markPiped(api, false); }
  }
  throw { code: 'piped_down', message: String(lastErr?.message || lastErr?.status || 'aucun serveur ne répond') };
}

function enAgeToFr(s) {
  const m = String(s || '').match(/(\d+)\s*(second|minute|hour|day|week|month|year)s?\s+ago/i);
  if (!m) return null;
  const n = Number(m[1]);
  const u = { second: 's', minute: 'min', hour: 'h', day: 'j', week: 'sem.', month: 'mois', year: n > 1 ? 'ans' : 'an' }[m[2].toLowerCase()];
  return `il y a ${n} ${u}`;
}
const pipedId = (it) => (String(it?.url || '').match(/[?&]v=([\w-]{11})/) || [])[1] || null;
const htmlToText = (html) => {
  const d = document.createElement('div');
  d.innerHTML = String(html || '').replace(/<br\s*\/?>/gi, '\n');
  return d.textContent || '';
};

async function pipedSearch(queries, add, before) {
  let doneQ = 0;
  let failures = 0;
  let firstErr = null;
  const pages = device === 'mobile' ? 1 : 2;
  await pool(queries, 3, async (q) => {
    try {
      let { body, api } = await pipedGet(`/search?q=${encodeURIComponent(q)}&filter=videos`);
      for (let p = 0; p < pages && body; p++) {
        for (const it of body.items || []) {
          const id = pipedId(it);
          if (!id || it.type !== 'stream' || it.isShort) continue;
          add({ id, title: it.title || '', views: it.views }, q, it.shortDescription || '');
          const cur = session.items.get(id);
          if (cur && it.duration > 0) cur.duration = it.duration;
          if (cur && it.uploaderName) cur.channel = String(it.uploaderName).slice(0, 80);
          if (cur && cur.status === 'pending') {
            if (it.views >= 0) { cur.viewCount = it.views; cur.views = fmtViews(it.views); }
            if (it.uploaded > 0) cur.age = ageFrom(new Date(it.uploaded).toISOString());
            else if (it.uploadedDate) cur.age = enAgeToFr(it.uploadedDate);
          }
        }
        if (p + 1 < pages && body.nextpage) {
          try { body = (await fetchJson(`${api}/nextpage/search?nextpage=${encodeURIComponent(body.nextpage)}&q=${encodeURIComponent(q)}&filter=videos`)); } catch { body = null; }
        } else body = null;
      }
    } catch (e) { failures++; firstErr ||= e; }
    doneQ++;
    setStatus(`Je cherche sur YouTube… ${session.items.size - before} vidéos trouvées`, 0.08 + 0.3 * (doneQ / queries.length));
  });
  const pending = [...session.items.values()].filter((i) => i.status === 'pending').slice(0, LIMITS().read);
  if (!pending.length) {
    if (failures === queries.length && firstErr) throw firstErr;
    setStatus('Aucune nouvelle vidéo pour ces recherches. Essaie d’autres mots.', 1, true);
    return false;
  }

  // Description complète + likes : on essaie, et on abandonne vite si YouTube bloque.
  let read = 0;
  const total = pending.length;
  const progress = () => setStatus(`${total} vidéos trouvées · je lis les descriptions (${read}/${total})`, 0.4 + 0.6 * (read / total));
  progress();
  const useShort = (item) => {
    const short = String(item.snippet || '').replace(/\s*\.\.\.\s*$/, '');
    item.description = short;
    item.partial = true;
    item.status = 'done';
  };
  const streamsOk = local.get('pipedStreamsOk', null);
  let streamsWork = streamsOk && Date.now() - streamsOk.at < 36e5 ? streamsOk.ok : null;
  let fails = 0;
  await pool(pending, 4, async (item) => {
    if (streamsWork !== false) {
      try {
        const { body } = await pipedGet(`/streams/${item.id}`, { stick: false, only: local.get('pipedGood', null) || undefined });
        streamsWork = true;
        item.description = htmlToText(body.description).slice(0, DESC_MAX);
        item.partial = false;
        item.status = 'done';
        if (body.title) item.title = body.title;
        applyStats(item, { views: body.views, likes: body.likes >= 0 ? body.likes : null });
      } catch {
        fails++;
        if (fails >= 3 && streamsWork !== true) streamsWork = false;
        useShort(item);
      }
    } else useShort(item);
    read++;
    if (read % 6 === 0 || read === total) { progress(); renderResults(); }
  });
  if (streamsWork != null) local.set('pipedStreamsOk', { at: Date.now(), ok: streamsWork });
  session.partialMode = streamsWork === false;
  return true;
}

function keyNotice(title, text) {
  const input = h('input', { id: 'ytKeyInput', type: 'text', placeholder: 'AIza…', autocomplete: 'off', spellcheck: 'false', 'aria-label': 'Clé YouTube' });
  input.value = ytKey();
  const save = () => {
    const v = input.value.trim();
    if (!v && ytKey()) { local.set('ytKey', ''); showNotice(null); toast('Clé retirée : mode sans clé'); $('#keyBtn').textContent = 'Descriptions complètes (clé YouTube, facultatif)'; return; }
    if (!/^AIza[\w-]{20,}$/.test(v)) { toast('Une clé YouTube commence par « AIza »'); input.focus(); return; }
    local.set('ytKey', v);
    showNotice(null);
    if ($('#keyBtn')) $('#keyBtn').textContent = 'Clé YouTube';
    toast('Clé enregistrée');
    if (promptEl.value.trim()) startSearch(); else promptEl.focus();
  };
  input.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); save(); } });
  return h('div', { class: 'notice' },
    h('h3', {}, title),
    h('p', {}, text),
    h('ol', {},
      h('li', {}, 'Ouvre Google Cloud (bouton ci-dessous) et connecte-toi avec ton compte Google. Crée un projet si on te le demande : c’est gratuit, sans carte bancaire.'),
      h('li', {}, 'Sur la page « YouTube Data API v3 », clique sur Activer.'),
      h('li', {}, 'Va dans Identifiants → Créer des identifiants → Clé API, puis copie la clé et colle-la ici.')),
    h('div', { class: 'key-row' }, input, h('button', { type: 'button', class: 'primary', onclick: save }, 'Enregistrer')),
    h('p', { class: 'hint' }, 'La clé reste dans ce navigateur. Pour la protéger : dans Google Cloud, ouvre la clé → Restrictions d’application → Sites web → ajoute kimany91.github.io/*'),
    h('div', { class: 'actions' }, h('a', { class: 'ghost', href: 'https://console.cloud.google.com/apis/library/youtube.googleapis.com', target: '_blank', rel: 'noopener' }, 'Ouvrir Google Cloud', icon('ext'))));
}
function openKeySettings() {
  showView('search');
  const n = keyNotice(ytKey() ? 'Ta clé YouTube' : 'Facultatif : descriptions complètes et likes',
    ytKey() ? 'Colle une nouvelle clé pour la remplacer, ou vide le champ et enregistre pour repasser en mode sans clé.' : 'Sans clé, Melofinds lit seulement le début des descriptions (YouTube bloque le reste). Avec une clé gratuite, il lit tout et affiche les likes.');
  $('#notice').replaceChildren(n);
  $('#notice').scrollIntoView({ behavior: 'smooth', block: 'center' });
}

// ---------------------------------------------------------------------------
// Recherche

const SUGGESTIONS = ['rapide', 'énergique', 'mélodique', 'sombre', 'triste', 'chill', 'drill', 'rage', 'pluggnb', 'jerk', 'piano', 'Luther', 'Damso', 'La Fève', 'Ninho', 'Lil Uzi', 'Travis Scott'];
const promptEl = $('#prompt');
for (const w of SUGGESTIONS) $('#suggestions').append(h('button', { type: 'button', class: 'chip', 'data-word': w, onclick: () => toggleWord(w) }, w));
function toggleWord(w) {
  const parts = promptEl.value.split(',').map((p) => p.trim()).filter(Boolean);
  const i = parts.findIndex((p) => p.toLowerCase() === w.toLowerCase());
  if (i >= 0) parts.splice(i, 1); else parts.push(w);
  promptEl.value = parts.join(', ');
  syncChips();
}
function syncChips() {
  const txt = ` ${strip(promptEl.value.toLowerCase())} `;
  $$('#suggestions .chip').forEach((c) => {
    const w = strip(c.dataset.word.toLowerCase()).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    c.classList.toggle('on', new RegExp(`[^a-z]${w}[^a-z]`).test(txt));
  });
}
promptEl.addEventListener('input', () => { syncChips(); onPromptInput(); });

// ---------------------------------------------------------------------------
// Rappeurs reconnus (en direct) + autocomplétion

const artistStyles = (m) => (m.type === 'fr' ? m.entry.fr.styles : [m.entry.genre]).map((id) => GENRE_BY_ID[id]?.label).filter(Boolean);
function renderRecognized() {
  const found = findArtists(promptEl.value);
  const box = $('#recognized');
  box.hidden = !found.length;
  box.replaceChildren(...found.map((m) => h('span', { class: 'rec', title: m.type === 'fr' ? m.entry.fr.note : '' },
    icon('mic'),
    h('b', {}, m.name),
    h('em', { class: `flag${m.type === 'us' ? ' us' : ''}` }, m.type === 'fr' ? 'FR' : 'US'),
    h('span', {}, artistStyles(m).slice(0, 2).join(' · ')),
    m.type === 'fr' ? h('span', { class: 'rec-us' }, `→ ${m.entry.fr.us.slice(0, 3).join(', ')}`) : null)));
}
let acItems = [];
let acIndex = -1;
function fragmentAtCaret() {
  const v = promptEl.value;
  const caret = promptEl.selectionStart ?? v.length;
  const before = v.slice(0, caret);
  const seg = before.split(/[,;]/).pop();
  const words = seg.trim().split(/\s+/).filter(Boolean);
  for (const n of [3, 2, 1]) {
    if (words.length < n) continue;
    const frag = words.slice(-n).join(' ');
    const list = suggestArtists(frag, 6);
    if (list.length && frag.length >= 2) return { frag, start: before.length - (before.length - before.lastIndexOf(words[words.length - n])), list };
  }
  return null;
}
function hideAc() { $('#ac').hidden = true; acItems = []; acIndex = -1; promptEl.setAttribute('aria-expanded', 'false'); }
function onPromptInput() {
  clearTimeout(onPromptInput._t);
  onPromptInput._t = setTimeout(() => {
    renderRecognized();
    const f = fragmentAtCaret();
    const exactAlready = f && findArtists(f.frag).some((m) => m.exact && f.list[0] && m.name === f.list[0].name && artistKey(f.frag) === artistKey(m.name));
    if (!f || exactAlready) { hideAc(); return; }
    acItems = f.list;
    acIndex = -1;
    const ac = $('#ac');
    ac.replaceChildren(...f.list.map((it, i) => {
      const styles = (it.type === 'fr' ? it.entry.fr.styles : [it.entry.genre]).map((id) => GENRE_BY_ID[id]?.label).filter(Boolean).slice(0, 2).join(' · ');
      const b = h('button', { type: 'button', class: 'ac-item', role: 'option', 'data-i': i },
        h('em', { class: `flag${it.type === 'us' ? ' us' : ''}` }, it.type === 'fr' ? 'FR' : 'US'), h('b', {}, it.name), h('span', {}, styles));
      b.addEventListener('mousedown', (e) => { e.preventDefault(); pickAc(i, f); });
      return b;
    }));
    ac.hidden = false;
    promptEl.setAttribute('aria-expanded', 'true');
  }, 90);
}
function pickAc(i, f = fragmentAtCaret()) {
  const it = acItems[i];
  if (!it || !f) return;
  const v = promptEl.value;
  const caret = promptEl.selectionStart ?? v.length;
  const start = f.start;
  promptEl.value = `${v.slice(0, start)}${it.name}${v.slice(caret)}`;
  const pos = start + it.name.length;
  promptEl.setSelectionRange(pos, pos);
  hideAc();
  syncChips();
  renderRecognized();
  promptEl.focus();
}
promptEl.addEventListener('keydown', (e) => {
  if ($('#ac').hidden || !acItems.length) return;
  if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
    e.preventDefault();
    acIndex = (acIndex + (e.key === 'ArrowDown' ? 1 : -1) + acItems.length) % acItems.length;
    $$('.ac-item').forEach((b, i) => b.classList.toggle('on', i === acIndex));
  } else if ((e.key === 'Enter' || e.key === 'Tab') && acIndex >= 0) {
    e.preventDefault();
    pickAc(acIndex);
  } else if (e.key === 'Escape') hideAc();
});
promptEl.addEventListener('blur', () => setTimeout(hideAc, 120));

// Liste complète des rappeurs et courants reconnus
$('#browseBtn').addEventListener('click', openBrowse);
function openBrowse() {
  const filter = h('input', { class: 'a-filter', id: 'aFilter', type: 'search', placeholder: 'Cherche un rappeur ou un courant…', 'aria-label': 'Filtrer la liste' });
  const count = h('p', { class: 'a-count' });
  const list = h('div', { class: 'alist' });
  const frSorted = [...FR_ARTISTS].sort((a, b) => a.name.localeCompare(b.name, 'fr'));
  const run = (q) => { closeDrawer(); promptEl.value = q; syncChips(); renderRecognized(); showView('search'); startSearch(); };
  const draw = () => {
    const k = artistKey(filter.value);
    const frRows = frSorted.filter((a) => !k || artistKey(a.name).includes(k) || a.aliases.some((al) => artistKey(al).includes(k)) || a.styles.some((id) => artistKey(GENRE_BY_ID[id]?.label || '').includes(k)) || a.us.some((u) => artistKey(u).includes(k)));
    const gRows = GENRES.filter((g) => !k || artistKey(g.label).includes(k) || g.artists.some((u) => artistKey(u).includes(k)));
    count.textContent = `${frRows.length} rappeurs FR · ${gRows.length} courants${k ? ' (filtrés)' : ''}`;
    list.replaceChildren(
      ...frRows.map((a) => h('div', { class: 'arow' },
        h('b', {}, a.name, ' ', h('em', { class: 'flag' }, 'FR')),
        h('div', { class: 'a-styles' }, a.styles.map((id) => GENRE_BY_ID[id]?.label).join(' · '), a.note ? ` — ${a.note}` : ''),
        h('div', { class: 'a-us' }, 'Même son que : ', h('strong', {}, a.us.join(', '))),
        h('button', { type: 'button', class: 'ghost', onclick: () => run(`une prod à la ${a.name}`) }, 'Chercher'))),
      ...gRows.map((g) => h('div', { class: 'arow' },
        h('b', {}, g.label, ' ', h('em', { class: 'flag us' }, 'COURANT')),
        h('div', { class: 'a-styles' }, `${g.bpm[0]}–${g.bpm[1]} BPM`),
        h('div', { class: 'a-us' }, 'Type beats : ', h('strong', {}, g.artists.join(', '))),
        h('button', { type: 'button', class: 'ghost', onclick: () => run(g.aliases[0]) }, 'Chercher'))),
    );
  };
  filter.addEventListener('input', () => { clearTimeout(draw._t); draw._t = setTimeout(draw, 80); });
  draw();
  openDrawer('Rappeurs & courants reconnus', [
    h('p', { class: 'muted', style: 'margin:0' }, 'Écris un de ces noms dans la recherche (même mal orthographié) : je cherche ses type beats et ceux des artistes US au même son.'),
    filter, count, list,
  ]);
  setTimeout(() => filter.focus(), 100);
}

// Filtres de licence (servent aussi à choisir « free for profit » dans les recherches)
const searchPrefs = Object.assign({ licenses: ['ffp', 'upto'], sort: 'licence', bpm: null }, local.get('searchPrefs', null) || {});
if (!Array.isArray(searchPrefs.licenses)) searchPrefs.licenses = ['ffp', 'upto'];
let session = null; // { prompt, plan, done: [], items: Map, at }
let searching = false;
let rendered = new Set();

function setStatus(text, progress, done = false) {
  const box = $('#status');
  if (text == null) { box.hidden = true; return; }
  box.hidden = false;
  box.classList.toggle('done', done);
  $('#statusText').textContent = text;
  $('#statusFill').style.width = `${Math.round(Math.max(0.04, progress) * 100)}%`;
}
function techDetail(e) {
  const where = String(e?.stack || '').split('\n').slice(0, 3).join(' | ');
  return `${String(e?.message || e?.code || e).slice(0, 160)}${where ? ` — ${where.slice(0, 260)}` : ''}`;
}
function showNotice(kind, extra, detail) {
  const box = $('#notice');
  if (!kind) { box.replaceChildren(); return; }
  const retry = h('button', { type: 'button', class: 'primary', onclick: () => { showNotice(null); startSearch(); } }, 'Réessayer');
  let n;
  if (kind === 'piped') {
    n = h('div', { class: 'notice error' }, h('h3', {}, 'Les serveurs de recherche ne répondent pas'),
      h('p', {}, 'Melofinds cherche sans clé via des serveurs gratuits (Piped). Ils sont tous injoignables en ce moment. Réessaie dans quelques minutes, ou ajoute une clé YouTube gratuite pour ne plus dépendre d’eux.'),
      h('div', { class: 'actions' }, retry, h('button', { type: 'button', class: 'ghost', onclick: openKeySettings }, 'Ajouter une clé YouTube')));
  } else if (kind === 'ytkey') {
    n = keyNotice('Dernière étape : ta clé YouTube gratuite', 'Melofinds cherche directement dans YouTube et lit la description complète de chaque prod. YouTube demande une clé gratuite (5 minutes, une seule fois).');
  } else if (kind === 'ytkey-bad') {
    n = keyNotice('Cette clé YouTube ne marche pas', 'YouTube refuse la clé. Vérifie que tu l’as copiée en entier, ou crée-en une nouvelle.');
  } else if (kind === 'ytdisabled') {
    n = keyNotice('Active « YouTube Data API v3 »', 'La clé existe, mais l’API YouTube n’est pas activée dans ton projet Google Cloud. Ouvre Google Cloud, clique sur Activer, attends une minute et réessaie.');
    n.querySelector('.actions').prepend(retry);
  } else if (kind === 'ytreferer') {
    n = keyNotice('La clé est bloquée pour ce site', 'Dans Google Cloud, ouvre ta clé → Restrictions d’application → Sites web, et ajoute kimany91.github.io/* (ou retire la restriction).');
    n.querySelector('.actions').prepend(retry);
  } else if (kind === 'quota') {
    n = h('div', { class: 'notice' }, h('h3', {}, 'Quota YouTube du jour épuisé'),
      h('p', {}, 'YouTube donne 10 000 unités par jour et par clé, soit environ 25 recherches. Le compteur repart à zéro à 9 h (heure de Paris). Tes favoris et l’historique restent dispo.'),
      h('div', { class: 'actions' }, h('button', { type: 'button', class: 'ghost', onclick: openKeySettings }, 'Utiliser une autre clé')));
  } else if (kind === 'connect') {
    n = h('div', { class: 'notice' }, h('h3', {}, 'Branche Parallel Search pour lancer la recherche'),
      h('p', {}, 'C’est le connecteur gratuit qui permet à Melofinds de lire YouTube. Sans compte ni clé, à faire une seule fois :'),
      h('ol', {}, h('li', {}, 'claude.ai → Paramètres → Connecteurs'), h('li', {}, 'Parcourir les connecteurs → Parallel Search → Connecter'), h('li', {}, 'Reviens ici et clique sur Réessayer')),
      h('div', { class: 'actions' }, retry, h('a', { class: 'ghost', href: 'https://claude.ai/settings/connectors', target: '_blank', rel: 'noopener' }, 'Ouvrir les connecteurs', icon('ext'))));
  } else if (kind === 'denied') {
    n = h('div', { class: 'notice' }, h('h3', {}, 'Autorise Parallel Search pour cette page'),
      h('p', {}, 'L’accès a été refusé. Autorise-le dans le menu Permissions de la page, puis réessaie.'),
      h('div', { class: 'actions' }, retry, h('button', { type: 'button', class: 'ghost', onclick: async () => { try { const p = await window.claude?.use?.('permissions'); await p?.manage?.(); } catch { toast('Ouvre le menu Permissions de la page.'); } } }, 'Permissions')));
  } else if (kind === 'reauth') {
    n = h('div', { class: 'notice' }, h('h3', {}, 'Reconnecte Parallel Search'), h('p', {}, 'claude.ai → Paramètres → Connecteurs → Parallel Search → Reconnecter, puis réessaie.'), h('div', { class: 'actions' }, retry));
  } else if (kind === 'unavailable') {
    n = h('div', { class: 'notice' }, h('h3', {}, 'Recherche indisponible dans cette vue'), h('p', {}, 'Ouvre Melofinds sur claude.ai pour lancer la recherche automatique.'));
  } else {
    n = h('div', { class: 'notice error' }, h('h3', {}, 'La recherche a coupé'), h('p', {}, extra || 'Parallel Search n’a pas répondu.'),
      detail ? h('details', { class: 'tech' }, h('summary', {}, 'Détail technique (à me copier si ça revient)'), h('code', {}, detail)) : null,
      h('div', { class: 'actions' }, retry));
  }
  box.replaceChildren(n);
}

function nextQueries(first) {
  const lim = LIMITS();
  const done = new Set(session.done);
  if (first) return session.plan.queries.map((q) => q.q).slice(0, lim.firstQueries);
  const deep = buildPlan(session.prompt, { licenses: searchPrefs.licenses, device, depth: 'approfondie' }).queries.map((q) => q.q);
  const sfx = licenseSuffix(searchPrefs.licenses) ? ` ${licenseSuffix(searchPrefs.licenses)}` : '';
  const variants = [];
  for (const a of session.plan.artists) variants.push(`${a.name} type beat 2026${sfx}`, `${a.name} type beat hard${sfx}`, `${a.name} type beat melodic${sfx}`);
  for (const g of session.plan.genres) variants.push(`${GENRE_BY_ID[g.id]?.query || g.label.toLowerCase()} type beat 2026${sfx}`);
  return [...deep, ...variants].filter((q) => !done.has(q)).slice(0, lim.moreQueries);
}

$('#searchForm').addEventListener('submit', (e) => { e.preventDefault(); startSearch(); });
function startSearch() {
  hideAc();
  const prompt = promptEl.value.trim();
  if (!prompt) { promptEl.focus(); toast('Décris la prod que tu cherches'); return; }
  if (searching) return;
  promptEl.blur();
  const plan = buildPlan(prompt, { licenses: searchPrefs.licenses, device, depth: device === 'mobile' ? 'rapide' : 'normal' });
  session = { prompt, plan, done: [], items: new Map(), at: new Date().toISOString() };
  rendered = new Set();
  $('#grid').replaceChildren();
  runSearch(true);
}
$('#moreBtn').addEventListener('click', () => { if (session) runSearch(false); });

async function runSearch(first) {
  if (searching || !session) return;
  const queries = nextQueries(first);
  if (!queries.length) { toast('J’ai fait le tour de cette recherche. Essaie d’autres mots.'); return; }
  searching = true;
  showNotice(null);
  $('#hero').classList.add('compact');
  $('#results').hidden = false;
  $('#goBtn').disabled = true;
  $('#moreBtn').disabled = true;
  session.done.push(...queries);
  if (first) saveHistory();
  const before = session.items.size;
  let searchTask = null;
  try {
    // 1) Trouver les vidéos : page de résultats YouTube de chaque recherche (+ recherche web)
    setStatus(`Je cherche sur YouTube (${queries.length} recherche${queries.length > 1 ? 's' : ''})…`, 0.08);
    if (first) showSkeletons(device === 'mobile' ? 4 : 8);
    let failures = 0;
    let firstErr = null;
    const add = (v, q, snippet = '') => {
      const cur = session.items.get(v.id);
      if (cur) {
        if (!Array.isArray(cur.foundBy)) cur.foundBy = [];
        if (!cur.foundBy.includes(q)) cur.foundBy.push(q);
        if (!cur.snippet && snippet) cur.snippet = snippet;
        return;
      }
      const viewCount = parseCount(v.views);
      session.items.set(v.id, { id: v.id, url: `https://www.youtube.com/watch?v=${v.id}`, title: v.title || 'Vidéo YouTube', views: viewCount != null ? fmtViews(viewCount) : null, viewCount, likeCount: null, age: v.age || null, foundBy: [q], status: 'pending', description: '', snippet });
    };
    if (WEB) {
      if (!(await webSearch(queries, add, before))) return;
    } else {
    const objective = `Vidéos YouTube de type beats (instrumentales rap) pour : ${session.prompt}. Avec les conditions de licence écrites dans la description.`;
    searchTask = searchSnippets(queries, objective)
      .then((list) => { list.forEach((v) => add(v, queries[0], v.text)); return null; })
      .catch((e) => (errorKind(e) ? e : null));
    let doneQ = 0;
    await pool(queries, 3, async (q) => {
      try { (await listVideos(q)).forEach((v) => add(v, q)); } catch (e) { if (errorKind(e)) throw e; failures++; firstErr ||= e; }
      doneQ++;
      setStatus(`Je cherche sur YouTube… ${session.items.size - before} vidéos trouvées`, 0.08 + 0.22 * (doneQ / queries.length));
    });
    const searchErr = await searchTask;
    if (searchErr) throw searchErr;
    const pending = [...session.items.values()].filter((i) => i.status === 'pending').slice(0, LIMITS().read);
    if (!pending.length) {
      if (failures === queries.length) { showNotice('error', `Parallel Search a renvoyé une erreur : ${String(firstErr?.message || firstErr?.code || '').slice(0, 160)}`); setStatus(null); }
      else setStatus('Aucune nouvelle vidéo pour ces recherches. Essaie d’autres mots.', 1, true);
      return;
    }

    // 2) Lire la description de chaque vidéo (page normale, puis version mobile, puis extrait de recherche)
    let read = 0;
    const total = pending.length;
    const progress = () => setStatus(`${total} vidéos trouvées · je lis les descriptions (${read}/${total})`, 0.3 + 0.7 * (read / total));
    progress();
    const retry = [];
    await pool(chunk(pending, 10), 3, async (batch) => {
      let pages = new Map();
      try { pages = await readPages(batch.map((i) => i.id), 'www.youtube.com'); } catch (e) { if (errorKind(e)) throw e; }
      for (const item of batch) {
        const page = pages.get(item.id);
        if (page?.title && item.title === 'Vidéo YouTube') item.title = page.title;
        applyStats(item, page?.stats);
        const desc = cleanDescription(page?.text, item.title, DESC_MAX);
        if (useful(desc)) { item.description = desc; item.status = 'done'; read++; } else retry.push(item);
      }
      progress();
      renderResults();
    });
    await pool(chunk(retry, 10), 3, async (batch) => {
      let pages = new Map();
      try { pages = await readPages(batch.map((i) => i.id), 'm.youtube.com'); } catch (e) { if (errorKind(e)) throw e; }
      for (const item of batch) {
        applyStats(item, pages.get(item.id)?.stats);
        const desc = cleanDescription(pages.get(item.id)?.text, item.title);
        const snip = cleanDescription(item.snippet, item.title);
        if (useful(desc)) { item.description = desc; item.status = 'done'; }
        else if (useful(snip)) { item.description = snip; item.status = 'done'; item.partial = true; }
        else item.status = 'unread';
        read++;
      }
      progress();
      renderResults();
    });
    }
    const all = [...session.items.values()].filter((i) => i.status !== 'pending');
    const unread = all.filter((i) => i.status === 'unread').length;
    const partialN = all.filter((i) => i.partial).length;
    setStatus(partialN
      ? `${all.length} prods · ${partialN} avec seulement le début de la description (YouTube bloque la suite)`
      : `${all.length} prods · ${all.length - unread} descriptions lues et vérifiées${unread ? ` · ${unread} illisibles` : ''}`, 1, true);
    saveSession();
    updateHistory();
  } catch (e) {
    await searchTask?.catch?.(() => {});
    const kind = errorKind(e);
    console.error('Melofinds : recherche interrompue', e);
    const got = [...session.items.values()].filter((i) => i.status !== 'pending');
    [...session.items.values()].forEach((i) => { if (i.status === 'pending') i.status = 'unread'; });
    if (kind) { setStatus(null); showNotice(kind); }
    else if (got.length) {
      setStatus(`${got.length} prods trouvées · la recherche s’est arrêtée en route`, 1, true);
      toast('Recherche interrompue : je garde ce que j’ai trouvé', { label: 'Réessayer', run: () => runSearch(false) });
      saveSession();
    } else {
      setStatus(null);
      showNotice('error', 'Un problème est survenu pendant la recherche. Relance-la.', techDetail(e));
    }
  } finally {
    searching = false;
    $('#goBtn').disabled = false;
    $('#moreBtn').disabled = false;
    clearSkeletons();
    renderResults();
    prewarmPlayer();
  }
}

function showSkeletons(n) {
  clearSkeletons();
  const grid = $('#grid');
  for (let i = 0; i < n; i++) grid.append(h('div', { class: 'skel', 'aria-hidden': 'true' }));
}
function clearSkeletons() { $$('#grid .skel').forEach((s) => s.remove()); }

// Filtres de la grille
const LIC_ORDER = ['ffp', 'upto', 'fnp', 'paid', 'unknown'];
function renderPills(box, counts, active, onToggle) {
  const prev = Object.fromEntries($$('.pill', box).map((p) => [p.dataset.cat, p.querySelector('b')?.textContent]));
  box.replaceChildren(...LIC_ORDER.map((c) => {
    const b = h('b', {}, counts[c] || 0);
    if (prev[c] != null && prev[c] !== String(counts[c] || 0)) b.classList.add('bump');
    return h('button', { type: 'button', class: `pill cat-${c}${active.includes(c) ? ' on' : ''}`, 'data-cat': c, 'aria-pressed': String(active.includes(c)), onclick: () => onToggle(c) }, SHORT[c], b);
  }));
}
function findTerms() { const t = $('#findInput').value.trim(); return t ? parseTextQuery(t).include : []; }
function sortRows(rows, how) {
  const rank = { ffp: 0, upto: 1, fnp: 2, paid: 3, unknown: 4 };
  const unreadPenalty = (r) => (r._item.status === 'unread' ? 1 : 0);
  if (how === 'ratio') {
    // Les vidéos à moins de 300 vues passent après : leur ratio ne veut pas dire grand-chose.
    const key = (r) => { const x = ratioOf(r._item); const v = r._item.viewCount ?? parseCount(r._item.views) ?? 0; return x == null ? -2 : v < 300 ? -1 + x / 1000 : x; };
    return [...rows].sort((a, b) => key(b) - key(a) || b.score - a.score);
  }
  if (how === 'duree-desc' || how === 'duree-asc') {
    const d = (r) => (r._item.duration > 0 ? r._item.duration : null);
    return [...rows].sort((a, b) => (d(a) == null) - (d(b) == null) || (how === 'duree-desc' ? d(b) - d(a) : d(a) - d(b)) || b.score - a.score);
  }
  if (how === 'vues') {
    const v = (r) => r._item.viewCount ?? parseCount(r._item.views) ?? -1;
    return [...rows].sort((a, b) => v(b) - v(a) || b.score - a.score);
  }
  if (how === 'licence') {
    return [...rows].sort((a, b) => unreadPenalty(a) - unreadPenalty(b) || rank[a.license.category] - rank[b.license.category]
      || (a.license.category === 'upto' ? (b.license.limit || 0) - (a.license.limit || 0) : 0) || b.score - a.score);
  }
  return sortResults(rows, how);
}

function renderResults() {
  if (!session) return;
  const plan = session.plan;
  const items = [...session.items.values()].filter((i) => i.status === 'done' || i.status === 'unread');
  const rows = items.map((item) => safeRow(item, plan)).filter((r) => r && (r.isBeat || r._item.status === 'unread'));
  $('#results').hidden = !rows.length && !searching;
  const counts = Object.fromEntries(LIC_ORDER.map((c) => [c, 0]));
  rows.forEach((r) => counts[r.license.category]++);
  renderPills($('#licPills'), counts, searchPrefs.licenses, (c) => {
    const set = new Set(searchPrefs.licenses);
    if (set.has(c)) set.delete(c); else set.add(c);
    searchPrefs.licenses = LIC_ORDER.filter((x) => set.has(x));
    local.set('searchPrefs', searchPrefs);
    renderResults();
  });
  const text = $('#findInput').value.trim();
  const bpm = searchPrefs.bpm;
  const filtered = filterResults(rows.map((r) => ({ ...r, isBeat: true })), {
    licenses: searchPrefs.licenses.length ? searchPrefs.licenses : LIC_ORDER,
    text,
    bpm: bpm ? { enabled: true, min: bpm.min, max: bpm.max, requireBpm: false } : undefined,
  });
  const minDur = Number(searchPrefs.minDur) || 0;
  const byDur = minDur ? filtered.filter((r) => !(r._item.duration > 0) || r._item.duration >= minDur) : filtered;
  const shown = searchPrefs.verifiedOnly ? byDur.filter((r) => r._item.status !== 'unread') : byDur;
  const sorted = sortRows(shown, $('#sort').value);
  const pendingN = [...session.items.values()].filter((i) => i.status === 'pending').length;
  const hiddenN = rows.length - sorted.length;
  $('#count').textContent = rows.length
    ? `${sorted.length} prod${sorted.length > 1 ? 's' : ''} affichée${sorted.length > 1 ? 's' : ''}${hiddenN ? ` · ${hiddenN} masquée${hiddenN > 1 ? 's' : ''} par les filtres` : ''}${searching && pendingN ? ` · ${pendingN} en cours de lecture` : ''}`
    : '';
  const grid = $('#grid');
  const skels = $$('.skel', grid);
  let newIndex = 0;
  const cards = sorted.map((r) => {
    const isNew = !rendered.has(r._item.id);
    const card = renderCard(r._item, r, { isNew, index: isNew ? Math.min(newIndex++, 12) : 0, plan });
    rendered.add(r._item.id);
    return card;
  });
  if (!cards.length && !skels.length && rows.length) {
    grid.replaceChildren(h('div', { class: 'empty', style: 'grid-column: 1 / -1' }, h('h3', {}, 'Rien avec ces filtres'), h('p', {}, 'Active d’autres licences au-dessus, ou retire le filtre texte / BPM.')));
    return;
  }
  grid.replaceChildren(...cards, ...skels);
}

function syncVerifiedPill() {
  $('#verifiedPill').classList.toggle('on', !!searchPrefs.verifiedOnly);
  $('#verifiedPill').setAttribute('aria-pressed', String(!!searchPrefs.verifiedOnly));
}
$('#verifiedPill').addEventListener('click', () => {
  searchPrefs.verifiedOnly = !searchPrefs.verifiedOnly;
  local.set('searchPrefs', searchPrefs); syncVerifiedPill(); renderResults();
});
$('#findInput').addEventListener('input', () => { clearTimeout(renderResults._t); renderResults._t = setTimeout(renderResults, 120); });
$('#sort').value = searchPrefs.sort || 'licence';
$('#sort').addEventListener('change', () => { searchPrefs.sort = $('#sort').value; local.set('searchPrefs', searchPrefs); renderResults(); });
function syncBpmPill() {
  const on = !!searchPrefs.bpm;
  $('#bpmPill').classList.toggle('on', on);
  $('#bpmPill').textContent = on ? `${searchPrefs.bpm.min || '…'}–${searchPrefs.bpm.max || '…'} BPM` : 'BPM';
}
$('#bpmPill').addEventListener('click', () => {
  const pop = $('#bpmPop');
  pop.hidden = !pop.hidden;
  $('#bpmPill').setAttribute('aria-expanded', String(!pop.hidden));
  if (!pop.hidden) {
    const range = searchPrefs.bpm || session?.plan?.bpmRange || { min: 130, max: 160 };
    $('#bpmMin').value = range.min || '';
    $('#bpmMax').value = range.max || '';
    searchPrefs.bpm = { min: Number($('#bpmMin').value) || null, max: Number($('#bpmMax').value) || null };
    if (['licence', 'pertinence'].includes($('#sort').value)) $('#sort').value = 'bpm-asc';
    searchPrefs.sort = $('#sort').value;
    local.set('searchPrefs', searchPrefs); syncBpmPill(); renderResults();
    $('#bpmMin').focus();
  }
});
['#bpmMin', '#bpmMax'].forEach((s) => $(s).addEventListener('input', () => {
  searchPrefs.bpm = { min: Number($('#bpmMin').value) || null, max: Number($('#bpmMax').value) || null };
  local.set('searchPrefs', searchPrefs); syncBpmPill(); renderResults();
}));
// Durée minimum : 1:00+, 2:00+, 3:00+ ou une durée libre (« 2:20 »)
function syncDurPill() {
  const v = Number(searchPrefs.minDur) || 0;
  $('#durPill').classList.toggle('on', !!v);
  $('#durPill').textContent = v ? `${fmtTime(v)}+` : 'Durée';
  $$('#durPop [data-dur]').forEach((b) => b.classList.toggle('on', Number(b.dataset.dur) === v));
}
function setMinDur(v) {
  searchPrefs.minDur = v > 0 ? v : null;
  local.set('searchPrefs', searchPrefs);
  syncDurPill();
  renderResults();
}
$('#durPill').addEventListener('click', () => {
  const pop = $('#durPop');
  pop.hidden = !pop.hidden;
  $('#durPill').setAttribute('aria-expanded', String(!pop.hidden));
  if (!pop.hidden) $('#durMin').value = searchPrefs.minDur ? fmtTime(searchPrefs.minDur) : '';
});
$$('#durPop [data-dur]').forEach((b) => b.addEventListener('click', () => { $('#durMin').value = fmtTime(Number(b.dataset.dur)); setMinDur(Number(b.dataset.dur)); }));
$('#durMin').addEventListener('input', () => {
  const v = parseMinDur($('#durMin').value);
  $('#durMin').classList.toggle('bad', !!$('#durMin').value.trim() && v == null);
  if (v != null || !$('#durMin').value.trim()) setMinDur(v || 0);
});
$('#durClear').addEventListener('click', () => {
  $('#durPop').hidden = true;
  $('#durPill').setAttribute('aria-expanded', 'false');
  setMinDur(0);
});
syncDurPill();

$('#bpmClear').addEventListener('click', () => {
  searchPrefs.bpm = null;
  $('#bpmPop').hidden = true;
  $('#bpmPill').setAttribute('aria-expanded', 'false');
  if ($('#sort').value.startsWith('bpm')) $('#sort').value = 'licence';
  searchPrefs.sort = $('#sort').value;
  local.set('searchPrefs', searchPrefs); syncBpmPill(); renderResults();
});

// « Comment j'ai cherché »
$('#howBtn').addEventListener('click', () => {
  if (!session) return;
  const p = session.plan;
  const counts = (q) => [...session.items.values()].filter((i) => (i.foundBy || []).includes(q)).length;
  openDrawer('Comment j’ai cherché', [
    h('p', { class: 'muted', style: 'margin:0' }, `Pour « ${session.prompt} », voici ce que l’algo a compris et les recherches lancées sur YouTube.`),
    p.recognized?.length ? h('div', { class: 'd-sec' }, h('h4', {}, 'Rappeurs reconnus'), h('div', { class: 'alist' }, p.recognized.map((r) => h('div', { class: 'arow' },
      h('b', {}, r.name, ' ', h('em', { class: `flag${r.type === 'us' ? ' us' : ''}` }, r.type === 'fr' ? 'FR' : 'US')),
      h('div', { class: 'a-styles' }, r.styles.join(' · '), r.note ? ` — ${r.note}` : ''),
      r.us.length ? h('div', { class: 'a-us' }, 'Même son que : ', h('strong', {}, r.us.join(', '))) : null)))) : null,
    h('div', { class: 'plan-grid' },
      h('div', { class: 'plan-card' }, h('h4', {}, 'Ambiances'), h('div', { class: 'tags' }, p.moods.length ? p.moods.map((m) => h('span', { class: 'tag' }, m.label)) : h('span', { class: 'muted' }, 'aucune reconnue'))),
      h('div', { class: 'plan-card' }, h('h4', {}, 'Courants de rap'), h('div', { class: 'tags' }, p.genres.map((g) => h('span', { class: 'tag' }, g.label)))),
      h('div', { class: 'plan-card' }, h('h4', {}, 'Artistes US'), h('div', { class: 'tags' }, p.artists.map((a) => h('span', { class: 'tag' }, a.name)))),
      h('div', { class: 'plan-card' }, h('h4', {}, 'BPM conseillé'), h('div', { class: 'bpm-big' }, `${p.bpmRange.min}–${p.bpmRange.max}`, h('small', {}, 'BPM')))),
    h('div', { class: 'd-sec' }, h('h4', {}, `Recherches YouTube (${session.done.length})`),
      h('ul', { class: 'qlist' }, session.done.map((q) => h('li', {}, h('span', {}, q), h('em', {}, `${counts(q)} vidéos`),
        h('a', { href: ytSearchUrl(q), target: '_blank', rel: 'noopener', 'aria-label': 'Ouvrir sur YouTube' }, icon('ext')))))),
  ]);
});

function saveSession() {
  if (!session) return;
  const items = [...session.items.values()].filter((i) => i.status !== 'pending')
    .map(({ id, url, title, views, viewCount, likeCount, age, foundBy, status, description, partial }) => ({ id, url, title, views, viewCount, likeCount, age, foundBy, status, description, partial }));
  local.set('session', { prompt: session.prompt, done: session.done, at: session.at, items });
}
function restoreSession() {
  const s = local.get('session', null);
  if (!s || typeof s.prompt !== 'string' || !Array.isArray(s.items)) return;
  s.items = s.items.filter((i) => i && typeof i.id === 'string')
    .map((i) => ({ ...i, title: String(i.title || 'Vidéo YouTube'), foundBy: Array.isArray(i.foundBy) ? i.foundBy : [], status: i.status === 'pending' ? 'unread' : (i.status || 'done') }));
  if (!s.items.length) return;
  if (!Array.isArray(s.done)) s.done = [];
  promptEl.value = s.prompt;
  syncChips();
  renderRecognized();
  session = { prompt: s.prompt, plan: buildPlan(s.prompt, { licenses: searchPrefs.licenses, device, depth: device === 'mobile' ? 'rapide' : 'normal' }), done: s.done || [], items: new Map(s.items.map((i) => [i.id, i])), at: s.at };
  rendered = new Set(s.items.map((i) => i.id));
  $('#hero').classList.add('compact');
  $('#results').hidden = false;
  const unread = s.items.filter((i) => i.status === 'unread').length;
  setStatus(`${s.items.length} prods · ${s.items.length - unread} descriptions lues et vérifiées`, 1, true);
  renderResults();
  prewarmPlayer();
}

// ---------------------------------------------------------------------------
// Historique & recherches favorites

function saveHistory() {
  const key = session.prompt.toLowerCase();
  const old = state.history.find((e) => e.prompt?.toLowerCase() === key);
  const entry = {
    id: old?.id || `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`,
    prompt: session.prompt, date: session.at, device,
    queries: session.done.slice(), favorite: old?.favorite || false, name: old?.name,
    genres: session.plan.genres.map((g) => g.label), artists: session.plan.artists.map((a) => a.name),
    counts: old?.counts || null, runs: (old?.runs || 0) + 1,
  };
  state.history = [entry, ...state.history.filter((e) => e.id !== entry.id)];
  persist.save('history');
  renderHistory();
}
function updateHistory() {
  const e = state.history.find((x) => x.prompt?.toLowerCase() === session.prompt.toLowerCase());
  if (!e) return;
  const counts = Object.fromEntries(LIC_ORDER.map((c) => [c, 0]));
  for (const item of session.items.values()) if (item.status !== 'pending') counts[analyzed(item, session.plan).license.category]++;
  updateEntry(e.id, { counts, queries: session.done.slice() });
}
function updateEntry(id, patch) {
  state.history = state.history.map((e) => (e.id === id ? { ...e, ...patch } : e));
  persist.save('history');
  renderHistory(); renderSavedSearches(); updateDots();
}
function relaunch(e) { promptEl.value = e.prompt; syncChips(); renderRecognized(); showView('search'); startSearch(); }

function historyRow(e, i) {
  if (!e.prompt) return null;
  const total = e.counts ? Object.values(e.counts).reduce((a, b) => a + b, 0) : null;
  const star = h('button', { type: 'button', class: `icon-btn star${e.favorite ? ' on' : ''}`, 'aria-label': e.favorite ? 'Retirer des favoris' : 'Mettre en favori', 'aria-pressed': String(!!e.favorite),
    onclick: () => { updateEntry(e.id, { favorite: !e.favorite }); toast(e.favorite ? 'Retirée des favoris' : 'Recherche ajoutée aux favoris'); } }, icon('star'));
  const del = h('button', { type: 'button', class: 'icon-btn', 'aria-label': 'Supprimer', onclick: () => {
    const before = state.history;
    state.history = state.history.filter((x) => x.id !== e.id);
    persist.save('history'); renderHistory(); renderSavedSearches(); updateDots();
    toast('Recherche supprimée', { label: 'Annuler', run: () => { state.history = before; persist.save('history'); renderHistory(); renderSavedSearches(); updateDots(); } });
  } }, icon('trash'));
  return h('div', { class: 'row-item', style: `--i:${Math.min(i, 12)}` },
    h('div', { class: 'ri-main' },
      h('div', { class: 'ri-title' }, e.name || e.prompt),
      h('div', { class: 'ri-sub' },
        h('span', {}, new Date(e.date).toLocaleString('fr-FR', { dateStyle: 'medium', timeStyle: 'short' })),
        total != null ? h('span', {}, `${total} prods`) : null,
        ...(e.counts ? ['ffp', 'upto'].filter((c) => e.counts[c]).map((c) => h('span', { class: `n cat-${c}` }, `${e.counts[c]} ${SHORT[c]}`)) : [])),
      h('div', { class: 'ri-q', title: (e.queries || []).join(' · ') }, `Recherches : ${(e.queries || []).join(' · ')}`)),
    h('div', { class: 'ri-actions' }, star, h('button', { type: 'button', class: 'primary', onclick: () => relaunch(e) }, 'Relancer'), del));
}
function renderHistory() {
  const list = state.history.filter((e) => e.prompt);
  $('#clearHistory').hidden = !list.length;
  $('#historyList').replaceChildren(...(list.length ? list.map(historyRow)
    : [h('div', { class: 'empty' }, h('div', { class: 'empty-ico' }, icon('clock')), h('h3', {}, 'Aucune recherche pour l’instant'), h('p', {}, 'Tes recherches apparaîtront ici, avec les requêtes utilisées sur YouTube.'), h('button', { type: 'button', class: 'primary', onclick: () => showView('search') }, 'Lancer une recherche'))]));
}
let clearArmed = null;
$('#clearHistory').addEventListener('click', () => {
  const btn = $('#clearHistory');
  if (!clearArmed) { btn.textContent = 'Confirmer (favoris gardés)'; clearArmed = setTimeout(() => { btn.textContent = 'Tout effacer'; clearArmed = null; }, 4000); return; }
  clearTimeout(clearArmed); clearArmed = null; btn.textContent = 'Tout effacer';
  state.history = state.history.filter((e) => e.favorite);
  persist.save('history'); renderHistory(); renderSavedSearches(); updateDots();
  toast('Historique effacé');
});

// ---------------------------------------------------------------------------
// Favoris : prods + recherches

function setSeg(s) {
  $$('.seg-btn').forEach((b) => b.classList.toggle('active', b.dataset.seg === s));
  $('#savedProds').hidden = s !== 'prods';
  $('#savedSearches').hidden = s !== 'searches';
}
$$('.seg-btn').forEach((b) => b.addEventListener('click', () => setSeg(b.dataset.seg)));
const savedPrefs = Object.assign({ licenses: LIC_ORDER.slice() }, local.get('savedPrefs', null) || {});
if (!Array.isArray(savedPrefs.licenses)) savedPrefs.licenses = LIC_ORDER.slice();
function renderSavedProds() {
  const rows = state.beats.map((b) => safeRow(b, null)).filter(Boolean);
  const counts = Object.fromEntries(LIC_ORDER.map((c) => [c, 0]));
  rows.forEach((r) => counts[r.license.category]++);
  $('#savedPills').hidden = !rows.length;
  renderPills($('#savedPills'), counts, savedPrefs.licenses, (c) => {
    const set = new Set(savedPrefs.licenses);
    if (set.has(c)) set.delete(c); else set.add(c);
    savedPrefs.licenses = LIC_ORDER.filter((x) => set.has(x));
    local.set('savedPrefs', savedPrefs);
    renderSavedProds();
  });
  const shown = rows.filter((r) => savedPrefs.licenses.includes(r.license.category));
  $('#savedGrid').replaceChildren(...(rows.length
    ? shown.map((r, i) => renderCard(r._item, r, { isNew: true, index: Math.min(i, 10) }))
    : [h('div', { class: 'empty', style: 'grid-column: 1 / -1' }, h('div', { class: 'empty-ico' }, icon('heart')), h('h3', {}, 'Aucune prod en favori'), h('p', {}, 'Clique sur le cœur d’une prod pour la retrouver ici.'), h('button', { type: 'button', class: 'primary', onclick: () => showView('search') }, 'Chercher des prods'))]));
}
function renderSavedSearches() {
  const favs = state.history.filter((e) => e.favorite && e.prompt);
  $('#savedSearches').replaceChildren(...(favs.length ? favs.map(historyRow)
    : [h('div', { class: 'empty' }, h('div', { class: 'empty-ico' }, icon('star')), h('h3', {}, 'Aucune recherche favorite'), h('p', {}, 'Dans l’historique, clique sur l’étoile d’une recherche pour la relancer en un clic.'))]));
}
function updateDots() {
  const favSearches = state.history.filter((e) => e.favorite && e.prompt).length;
  const n = state.beats.length + favSearches;
  $('#savedDot').hidden = !n;
  $('#savedDot').textContent = n;
  $('#nProds').textContent = state.beats.length;
  $('#nSearches').textContent = favSearches;
}

// ---------------------------------------------------------------------------
// Vérifier une prod (lien YouTube, ou titre + description collés)

const EXAMPLES = [['Titre trompeur', 'demo-baby1'], ['Up to 5K', 'demo-uzi2'], ['Vraiment free', 'demo-uzi3']];
$('#openVerify').addEventListener('click', openVerify);
function openVerify() {
  const url = h('input', { id: 'vUrl', type: 'url', placeholder: 'https://www.youtube.com/watch?v=…', inputmode: 'url' });
  const title = h('input', { id: 'vTitle', type: 'text', placeholder: 'Titre de la vidéo' });
  const desc = h('textarea', { id: 'vDesc', placeholder: 'Colle ici la description complète' });
  const result = h('div', { style: 'display:grid; gap:14px' });
  const readBtn = h('button', { type: 'button', class: 'ghost', hidden: true }, 'Lire la description depuis YouTube');
  const keep = h('button', { type: 'button', class: 'primary', disabled: true }, icon('heart'), 'Ajouter aux favoris');
  const draft = () => {
    const id = youtubeId(url.value);
    return { id: id || `m-${strip(title.value).toLowerCase().replace(/[^a-z0-9]+/g, '-').slice(0, 40)}`, url: id ? `https://www.youtube.com/watch?v=${id}` : '', title: title.value.trim(), description: desc.value.trim().slice(0, DESC_MAX), status: 'done' };
  };
  const update = () => {
    const b = draft();
    readBtn.hidden = !youtubeId(url.value);
    const has = !!(b.title || b.description);
    keep.disabled = !has || isSaved(b.id);
    if (!has) { result.replaceChildren(); return; }
    const r = analyzed(b, null);
    result.replaceChildren(verdictBox(r.license, false), ...beatDetails(b, r).filter(Boolean));
  };
  const readFromLink = async () => {
    const id = youtubeId(url.value);
    if (!id) return;
    readBtn.disabled = true;
    readBtn.replaceChildren(h('span', { class: 'spinner' }), 'Lecture…');
    try {
      let pages = await readPages([id], 'www.youtube.com');
      let page = pages.get(id);
      let d = cleanDescription(page?.text, page?.title);
      if (!useful(d)) { pages = await readPages([id], 'm.youtube.com'); page = pages.get(id) || page; d = cleanDescription(page?.text, page?.title); }
      if (page?.title) title.value = page.title;
      if (useful(d)) desc.value = d; else toast('Description illisible : colle-la à la main.');
      update();
    } catch (e) {
      toast(errorKind(e) === 'connect' ? 'Branche Parallel Search pour lire les liens (claude.ai → Connecteurs).' : 'Lecture impossible : colle la description à la main.');
    } finally {
      readBtn.disabled = false;
      readBtn.replaceChildren('Lire la description depuis YouTube');
    }
  };
  readBtn.addEventListener('click', readFromLink);
  url.addEventListener('paste', () => setTimeout(() => { update(); if (youtubeId(url.value)) readFromLink(); }, 0));
  [url, title, desc].forEach((el) => el.addEventListener('input', () => { clearTimeout(update._t); update._t = setTimeout(update, 120); }));
  keep.addEventListener('click', () => { const b = draft(); if (!isSaved(b.id)) toggleSaved(b); update(); });
  openDrawer('Vérifier une prod', [
    h('p', { class: 'muted', style: 'margin:0' }, 'Colle le lien d’une vidéo : je lis sa description et je te dis si tu peux vraiment sortir ton son sur Spotify.'),
    h('label', { class: 'field', for: 'vUrl' }, 'Lien YouTube', url),
    readBtn,
    h('label', { class: 'field', for: 'vTitle' }, 'Titre', title),
    h('label', { class: 'field', for: 'vDesc' }, 'Description', desc),
    h('div', { class: 'chips', style: 'justify-content:flex-start; margin:0' }, h('span', { class: 'hint', style: 'align-self:center' }, 'Exemples :'),
      EXAMPLES.map(([label, vid]) => h('button', { type: 'button', class: 'chip', onclick: () => { const v = DEMO_VIDEOS.find((x) => x.id === vid); url.value = ''; title.value = v.title; desc.value = v.description; update(); } }, label))),
    result,
    keep,
  ]);
  setTimeout(() => url.focus(), 80);
}

// ---------------------------------------------------------------------------
// Avis de Claude (facultatif, capacité « sample »)

let sampleFn = null;
async function askClaude(item, slot) {
  slot.replaceChildren(h('span', { class: 'spinner' }), 'Claude lit la description…');
  const prompt = [
    'Tu aides un rappeur à savoir s’il peut sortir un son sur Spotify avec une prod (beat) trouvée sur YouTube.',
    'Lis le titre et la description. La description fait foi sur le titre.',
    'Catégories : "ffp" = free for profit sans limite ; "upto" = free for profit jusqu’à une limite de streams ; "fnp" = gratuit seulement non commercial, payer pour Spotify ; "paid" = payant ou vendue ; "unknown" = rien de clair.',
    'Réponds UNIQUEMENT avec ce JSON : {"categorie": "ffp|upto|fnp|paid|unknown", "limite_streams": nombre ou null, "explication": "2 phrases max en français simple", "citation": "phrase exacte qui décide, ou vide"}',
    '', `TITRE : ${item.title}`, 'DESCRIPTION :', String(item.description || '').slice(0, 6000),
  ].join('\n');
  try {
    const a = await sampleFn.json(prompt);
    const cat = CATEGORIES[a?.categorie] ? a.categorie : 'unknown';
    const algo = analyzed(item, null).license.category;
    slot.replaceChildren(h('div', { class: `claude-box cat-${cat}` },
      h('b', {}, `Claude : ${cat === 'upto' && a.limite_streams ? `Up to ${formatCount(Number(a.limite_streams))} streams` : CATEGORIES[cat].label}`),
      h('div', {}, String(a.explication || '')), a.citation ? h('q', {}, String(a.citation)) : null,
      h('div', { class: 'hint', style: 'margin-top:6px' }, cat === algo ? 'Même verdict que l’algo.' : `L’algo dit « ${CATEGORIES[algo].label} » : relis la description pour trancher.`)));
  } catch (e) {
    slot.replaceChildren(e?.code === 'not_granted' ? 'Tu n’as pas autorisé Claude pour cette page.' : e?.code === 'rate_limited' ? 'Trop de demandes : réessaie dans un moment.' : 'Claude n’a pas pu répondre.');
    if (['not_granted', 'sampling_disabled', 'not_declared', 'capability_disabled', 'capability_removed'].includes(e?.code)) sampleFn = null;
  }
}

// ---------------------------------------------------------------------------
// Démarrage

// ---------------------------------------------------------------------------
// Télécharger sur mon PC (version web) : l'app envoie la prod via ntfy.sh
// (messages gratuits, sans compte) ; le programme MelofindsPC.exe, sur le PC,
// la récupère et la télécharge avec yt-dlp. Marche en 5G comme en Wi-Fi.
// Le PC répond sur le sujet <code>-ok : en ligne, prod téléchargée, erreur.

const NTFY = 'https://ntfy.sh';
function pcCode() {
  let c = String(local.get('pcCode', '') || '');
  if (!/^melofinds-[a-f0-9]{32}$/.test(c)) {
    c = `melofinds-${Array.from(crypto.getRandomValues(new Uint8Array(16)), (b) => b.toString(16).padStart(2, '0')).join('')}`;
    local.set('pcCode', c);
  }
  return c;
}
const randHex = (n) => Array.from(crypto.getRandomValues(new Uint8Array(n)), (b) => b.toString(16).padStart(2, '0')).join('');
// Clé secrète : elle ne passe JAMAIS par ntfy. Elle signe chaque envoi (HMAC-SHA256) ;
// le programme du PC ignore tout envoi sans la bonne signature.
function pcKey() {
  let k = String(local.get('pcKey', '') || '');
  if (!/^[a-f0-9]{64}$/.test(k)) { k = randHex(32); local.set('pcKey', k); }
  return k;
}
// Nom court de cet appareil, affiché dans « Appareils » sur le PC (ex. « iPhone · Safari »)
function deviceLabel() {
  const ua = navigator.userAgent || '';
  const dev = /iPhone/.test(ua) ? 'iPhone' : /iPad/.test(ua) ? 'iPad' : /Android/.test(ua) ? 'Android' : /Windows/.test(ua) ? 'Windows' : /Mac OS X|Macintosh/.test(ua) ? 'Mac' : /Linux/.test(ua) ? 'Linux' : 'Appareil';
  const br = /EdgA?\//.test(ua) ? 'Edge' : /SamsungBrowser/.test(ua) ? 'Samsung' : /OPR\//.test(ua) ? 'Opera' : /Firefox|FxiOS/.test(ua) ? 'Firefox' : /Chrome|CriOS/.test(ua) ? 'Chrome' : /Safari/.test(ua) ? 'Safari' : '';
  return br ? `${dev} · ${br}` : dev;
}
async function signed(obj) {
  const p = JSON.stringify({ mf: 2, ts: Date.now(), n: randHex(16), dev: deviceLabel(), ...obj });
  const raw = new Uint8Array(pcKey().match(/../g).map((x) => parseInt(x, 16)));
  const key = await crypto.subtle.importKey('raw', raw, { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
  const sig = new Uint8Array(await crypto.subtle.sign('HMAC', key, new TextEncoder().encode(p)));
  return JSON.stringify({ p, s: Array.from(sig, (b) => b.toString(16).padStart(2, '0')).join('') });
}
const pc = { queue: local.get('pcQueue', {}) || {}, info: local.get('pcInfo', null), es: null, onPong: null, cur: null };
function savePc() {
  const ids = Object.keys(pc.queue).sort((a, b) => (pc.queue[b].at || 0) - (pc.queue[a].at || 0)).slice(0, 150);
  pc.queue = Object.fromEntries(ids.map((id) => [id, pc.queue[id]]));
  local.set('pcQueue', pc.queue);
}
async function ntfyPublish(payload) {
  // Corps en texte brut, sans en-tête spécial : pas de requête préalable CORS.
  const res = await fetch(`${NTFY}/${pcCode()}`, { method: 'POST', body: await signed(payload) });
  if (!res.ok) throw new Error(`ntfy ${res.status}`);
}

function listenPc() {
  if (!WEB || pc.es || typeof EventSource === 'undefined') return;
  const since = Math.floor((Date.now() - 12 * 3600e3) / 1000);
  const es = new EventSource(`${NTFY}/${pcCode()}-ok/sse?since=${since}`);
  pc.es = es;
  es.onmessage = (e) => {
    let d;
    try { d = JSON.parse(e.data); } catch { return; }
    if (d?.event && d.event !== 'message') return;
    let m;
    try { m = JSON.parse(d.message || '{}'); } catch { return; }
    if (!m || typeof m !== 'object') return;
    const fresh = (d.time || 0) * 1000 > Date.now() - 90e3;
    if (onPcViewMessage(d, m, fresh)) return;
    if (m.update) {
      if (fresh) {
        if (m.update === 'none') toast(`Ton PC est déjà à jour (version ${String(m.version || '')})`);
        else if (m.update === 'start') toast(`Ton PC installe la version ${String(m.version || '')}…`);
        else toast(`Mise à jour impossible : ${String(m.err || '').slice(0, 80)}`);
      }
      return;
    }
    if (m.pc === 'online' || m.pc === 'alive' || m.pc === 'offline' || m.pong) {
      const at = (d.time || 0) * 1000;
      if (at >= (pc.info?.at || 0)) {
        pc.info = { ...(pc.info || {}), at, offline: m.pc === 'offline', why: m.pc === 'offline' ? String(m.why || '').slice(0, 20) : '', version: String(m.version || pc.info?.version || ''), dossier: String(m.dossier || pc.info?.dossier || ''), name: String(m.name || pc.info?.name || '') };
        local.set('pcInfo', pc.info);
      }
      if (m.pong && pc.onPong) pc.onPong(m);
      // Le PC vient de se rallumer : on renvoie ce qui a pu expirer pendant qu'il était éteint.
      if (m.pc === 'online' && fresh) { setTimeout(resendPending, 15e3); setTimeout(() => pcSync(true), 20e3); }
      syncPcUi();
      return;
    }
    const id = String(m.v || '');
    if (!/^[\w-]{11}$/.test(id)) return;
    const cur = pc.queue[id] || { t: id, at: (d.time || 0) * 1000 };
    // Réponse à un envoi plus ancien (relue au rechargement de la page) : on l'ignore,
    // sinon une vieille réponse « téléchargée » validerait un nouvel envoi pas encore fait.
    if (cur.lastSent && (d.time || 0) * 1000 < cur.lastSent - 5000) return;
    if (cur.state === 'done' && !m.ok) return;
    const was = cur.state;
    // Ce que le PC a trouvé sur Tunebat (affiché en bleu dans l'app)
    if (m.ok && m.tb && typeof m.tb === 'object') {
      const bpm = Number(m.tb.bpm) >= 50 && Number(m.tb.bpm) <= 220 ? Math.round(Number(m.tb.bpm)) : null;
      const key = /^[A-G][#b]? (min|maj)$/.test(String(m.tb.key || '')) ? String(m.tb.key) : null;
      if (bpm || key) {
        tbStore(id, { ...(tbFor(id) || {}), ...(bpm ? { bpm } : {}), ...(key ? { key } : {}), at: Date.now() });
        const it = session?.items?.get(id);
        if (it) refreshItem(it);
      }
    }
    pc.queue[id] = { ...cur, state: m.ok ? 'done' : 'error', file: m.file ? String(m.file) : cur.file, err: m.err ? String(m.err) : null };
    if (pc.cur?.v === id) pc.cur = null;
    pc.info = { ...(pc.info || {}), at: Math.max(pc.info?.at || 0, (d.time || 0) * 1000) };
    local.set('pcInfo', pc.info);
    savePc();
    syncPcUi();
    if (fresh && was !== pc.queue[id].state) {
      toast(m.ok ? (m.deja ? `Déjà sur ton PC : ${String(m.file || displayTitle(cur.t)).slice(0, 80)}` : `Sur ton PC : ${displayTitle(cur.t)}`)
        : `Le PC n’a pas pu télécharger : ${String(m.err || '').slice(0, 80)}`);
    }
  };
  es.onerror = () => { /* EventSource se reconnecte tout seul */ };
}

async function sendToPc(item) {
  if (!WEB) return;
  const id = ytIdOf(item);
  if (!id) { toast('Pas de vidéo YouTube pour cette prod'); return; }
  if (!pc.info) { openPcSetup(item); return; }
  let r = null;
  try { r = analyzed(item, session?.plan || null); } catch { /* sans analyse */ }
  // Le PC nomme le fichier « Titre [Clé, BPM].wav » (sans « free ») ; il relit aussi la description.
  // Licence → étiquette du fichier sur le PC : [FFP], [F] ou [FFP, UPTO 5000]
  const msg = { v: id, t: String(item.title || '').slice(0, 200), bpm: r?.bpm || null, key: r?.key || null, tbBpm: r?.bpmTb || undefined, tbKey: r?.keyTb || undefined,
    lic: r?.license?.category || null, limit: r?.license?.limit || null, force: pc.queue[id]?.state === 'error' || undefined };
  pc.queue[id] = { t: item.title || id, at: Date.now(), lastSent: Date.now(), state: 'sending', msg };
  syncPcUi();
  try {
    await ntfyPublish(msg);
    pc.queue[id].state = 'sent';
    pc.queue[id].lastSent = Date.now();
    toast(pcOn() ? 'Envoyée à ton PC' : 'Ton PC est éteint : la prod est en file d’attente, elle arrivera dès qu’il se rallume');
  } catch {
    pc.queue[id].state = 'unsent';
    toast('Pas de réseau : la prod partira toute seule dès que tu en auras');
  }
  savePc();
  syncPcUi();
  listenPc();
}

// File d'attente : ntfy garde les envois ~12 h. Une prod pas encore reçue est
// renvoyée avant d'expirer (et dès que le réseau revient) : elle arrive dès que
// le PC se rallume, même des jours plus tard. Le PC ignore les doublons.
// Le PC se signale toutes les 50 min (limite de 250 envois par jour sur ntfy.sh)
const pcOn = () => !!pc.info && !pc.info.offline && Date.now() - (pc.info.at || 0) < 110 * 60e3;
let resending = false;
async function resendPending() {
  if (!WEB || !pc.info || resending || !navigator.onLine) return;
  resending = true;
  try {
    const todo = Object.entries(pc.queue).filter(([, q]) => q.state === 'unsent' || (q.state === 'sent' && Date.now() - (q.lastSent || q.at || 0) > 10 * 3600e3)).slice(0, 25);
    for (const [id, q] of todo) {
      try {
        await ntfyPublish({ ...(q.msg || { v: id, t: String(q.t || '').slice(0, 200) }), force: undefined });
        pc.queue[id] = { ...q, state: 'sent', lastSent: Date.now() };
      } catch { break; }
    }
    if (todo.length) { savePc(); syncPcUi(); }
    await resendPcCmds();
  } finally { resending = false; }
}

const PC_LABEL = { sending: 'Envoi…', sent: 'En file d’attente pour ton PC', unsent: 'Partira dès que tu as du réseau', done: 'Sur ton PC', error: 'Erreur' };
function pcButton(item) {
  const id = ytIdOf(item);
  const st = pc.queue[id]?.state || '';
  return h('button', { type: 'button', class: `pc-btn${st ? ` ${st}` : ''}`, 'data-pc': id, 'aria-label': st ? PC_LABEL[st] : 'Télécharger sur mon PC', title: st ? PC_LABEL[st] : 'Télécharger sur mon PC',
    onclick: (e) => { e.stopPropagation(); sendToPc(item); } }, icon(st === 'done' ? 'check' : 'down'));
}
function syncPcUi() {
  $$('.pc-btn[data-pc]').forEach((b) => {
    const st = pc.queue[b.dataset.pc]?.state || '';
    b.className = `pc-btn${st ? ` ${st}` : ''}`;
    const label = st ? PC_LABEL[st] : 'Télécharger sur mon PC';
    b.setAttribute('aria-label', label);
    b.title = label;
    b.replaceChildren(icon(st === 'done' ? 'check' : 'down'));
  });
  const dot = $('#pcDot');
  if (dot) {
    const waiting = Object.values(pc.queue).filter((q) => q.state === 'sent' || q.state === 'unsent' || q.state === 'sending').length;
    dot.hidden = !pc.info && !waiting;
    dot.textContent = waiting ? String(waiting) : '✓';
    dot.classList.toggle('wait', waiting > 0);
  }
  if ($('#pcStatus')) renderPcStatus();
  renderPcView();
}

function pcStatusText(short) {
  if (!pc.info) return { ok: false, t: 'PC pas encore connecté', s: 'Fais les 3 étapes ci-dessous.' };
  const ago = Date.now() - (pc.info.at || 0);
  const when = ago < 90e3 ? 'à l’instant' : ago < 3600e3 ? `il y a ${Math.round(ago / 60e3)} min` : ago < 864e5 ? `il y a ${Math.round(ago / 3600e3)} h` : `il y a ${Math.round(ago / 864e5)} j`;
  const waiting = Object.values(pc.queue).filter((q) => q.state === 'sent' || q.state === 'unsent').length;
  if (!pcOn()) return { ok: false, off: true, t: pc.info.offline ? (pc.info.why === 'shutdown' ? 'PC éteint' : 'PC hors ligne') : 'PC éteint ou hors ligne', s: `Dernier signe ${when}. ${waiting ? `${waiting} prod${waiting > 1 ? 's' : ''} en file d’attente : elle${waiting > 1 ? 's' : ''} arrivera${waiting > 1 ? 'nt' : ''} dès qu’il se rallume.` : 'Tes envois l’attendront et arriveront dès qu’il se rallume.'}` };
  if (short) return { ok: true, t: `PC en ligne${pc.info.version ? ` · ${pc.info.version}` : ''}`, s: `Dernier signe ${when}` };
  return { ok: true, t: `PC en ligne${pc.info.version ? ` · version ${pc.info.version}` : ''}`, s: `${pc.info.name ? `Ce téléphone s’appelle « ${pc.info.name} » sur le PC · ` : ''}Dernier signe ${when}${pc.info.dossier ? ` · dossier ${pc.info.dossier}` : ''}` };
}
function renderPcStatus() {
  const st = pcStatusText();
  $('#pcStatus').replaceChildren(h('div', { class: `pc-status${st.ok ? ' ok' : ''}${st.off ? ' off' : ''}` }, h('span', { class: 'pc-led', 'aria-hidden': 'true' }), h('div', {}, h('b', {}, st.t), h('span', {}, st.s))));
  const list = Object.entries(pc.queue).sort((a, b) => (b[1].at || 0) - (a[1].at || 0)).slice(0, 30);
  const box = $('#pcList');
  if (!box) return;
  box.replaceChildren(...(list.length ? list.map(([id, q]) => h('div', { class: `pc-row ${q.state}` },
    h('span', { class: 'pc-ico' }, icon(q.state === 'done' ? 'check' : q.state === 'error' ? 'x' : 'clock')),
    h('div', { class: 'pc-row-main' }, h('b', {}, displayTitle(q.t || id)), h('span', {}, q.state === 'done' ? (q.file || 'Téléchargée') : q.state === 'error' ? (q.err || 'Erreur') : q.state === 'unsent' ? 'Partira dès que tu as du réseau' : pcOn() ? 'Le PC s’en occupe…' : 'En file d’attente : arrivera dès que le PC se rallume')),
    q.state !== 'done' ? h('button', { type: 'button', class: 'ghost', onclick: () => sendToPc({ id, url: `https://www.youtube.com/watch?v=${id}`, title: q.t }) }, 'Renvoyer') : null))
    : [h('p', { class: 'muted' }, 'Aucune prod envoyée pour l’instant. Touche ', icon('down'), ' sur une prod.')]));
}

// ---------------------------------------------------------------------------
// Onglet « File d'attente » : la prod qui arrive sur le PC, celles qui attendent, puis
// tous les projets du PC (renommer, icône, couleur, favori, écouter l'instru et chaque
// version). La liste et les sons écoutés sont gardés sur ce téléphone : tout reste
// visible et écoutable quand le PC est éteint. Les changements faits PC éteint partent
// dès qu'il se rallume (ntfy les garde 12 h, l'app les renvoie ensuite).

const pcLib = { data: null, parts: {}, waiting: null, askedAt: 0, q: '', filter: local.get('pcLibFilter', 'all'), open: new Set(), cmds: local.get('pcCmds', []) || [], cached: new Map() };
const PC_COLOR = /^#[0-9a-f]{6}$/i;
const pcPlayer = { audio: null, fid: null, url: '', el: null, unlocked: false };
// Un seul lecteur, « débloqué » au moment où tu touches ▶ : le son peut démarrer tout seul
// quand il arrive du PC quelques secondes plus tard (iPhone compris).
const SILENT_WAV = 'data:audio/wav;base64,UklGRjQAAABXQVZFZm10IBAAAAABAAEAQB8AAIA+AAACABAAZGF0YRAAAAAAAAAAAAAAAAAAAAAAAAAA';
function pcAudioEl() {
  if (!pcPlayer.el) pcPlayer.el = new Audio();
  return pcPlayer.el;
}
function unlockPcAudio() {
  if (pcPlayer.unlocked || pcPlayer.audio) return;
  const el = pcAudioEl();
  try {
    el.src = SILENT_WAV;
    const r = el.play();
    pcPlayer.unlocked = true;
    if (r && r.catch) r.catch(() => { pcPlayer.unlocked = false; });
  } catch { /* lecteur indisponible */ }
}

function sanitizeLib(raw) {
  if (!raw || typeof raw !== 'object' || !Array.isArray(raw.projects)) return null;
  const str = (v, n) => String(v ?? '').slice(0, n);
  const palette = (Array.isArray(raw.palette) ? raw.palette : []).filter((c) => PC_COLOR.test(String(c))).slice(0, 24);
  const icons = (Array.isArray(raw.icons) ? raw.icons : []).map((i) => str(i, 2)).filter(Boolean).slice(0, 40);
  const projects = raw.projects.slice(0, 300).filter((p) => p && typeof p === 'object' && typeof p.p === 'string').map((p) => ({
    p: str(p.p, 260), n: str(p.n, 200), t: str(p.t || p.n, 160), k: /^[A-G][#b]?( (min|maj))?$/.test(String(p.k || '')) ? String(p.k) : '',
    b: Number(p.b) >= 50 && Number(p.b) <= 220 ? Math.round(Number(p.b)) : 0, tb: Array.isArray(p.tb) ? p.tb.filter((x) => x === 'key' || x === 'bpm') : [],
    lic: str(p.lic, 30), fav: p.fav ? 1 : 0, c: PC_COLOR.test(String(p.c)) ? String(p.c) : '#8b5cf6', ic: str(p.ic, 2) || '♪', d: Number(p.d) || 0, fl: p.fl ? 1 : 0,
    files: (Array.isArray(p.files) ? p.files : []).slice(0, 60).filter((f) => f && /^[a-f0-9]{12}$/.test(String(f.f))).map((f) => ({
      f: String(f.f), n: str(f.n, 140), e: str(f.e, 6), v: /^v[\d.]{1,15}$/.test(String(f.v || '')) ? String(f.v) : '', s: Number(f.s) || 0, m: Number(f.m) || 0, i: f.i ? 1 : 0, l: f.l ? 1 : 0 })),
  }));
  return { at: Number(raw.at) || 0, projects, palette: palette.length ? palette : ['#8b5cf6'], icons: icons.length ? icons : ['♪'] };
}
pcLib.data = sanitizeLib(local.get('pcLib', null));
function savePcLib() {
  pcLib.cmds = pcLib.cmds.filter((c) => Date.now() - c.at < 7 * 864e5).slice(-60);
  local.set('pcCmds', pcLib.cmds);
  if (pcLib.data) local.set('pcLib', pcLib.data);
}

// Sons gardés dans ce navigateur (IndexedDB) : la dernière version de chaque projet
// arrive toute seule (synchronisation), plus ceux que tu écoutes ; 200 au plus.
const PC_KEEP = 200;
const pcAudioStore = {
  db: null,
  open() {
    if (this.db !== null) return this.db;
    this.db = new Promise((resolve) => {
      try {
        const req = indexedDB.open('melofinds-pc', 1);
        req.onupgradeneeded = () => req.result.createObjectStore('audio', { keyPath: 'id' });
        req.onsuccess = () => resolve(req.result);
        req.onerror = () => resolve(null);
      } catch { resolve(null); }
    });
    return this.db;
  },
  async req(mode, fn) {
    const db = await this.open();
    if (!db) return null;
    return new Promise((resolve) => {
      try {
        const t = db.transaction('audio', mode);
        const r = fn(t.objectStore('audio'));
        t.oncomplete = () => resolve(r?.result ?? null);
        t.onerror = () => resolve(null);
      } catch { resolve(null); }
    });
  },
  get(id) { return this.req('readonly', (st) => st.get(id)); },
  put(row) { pcLib.cached.set(row.id, row.m); return this.req('readwrite', (st) => st.put(row)); },
  del(id) { pcLib.cached.delete(id); return this.req('readwrite', (st) => st.delete(id)); },
  async load() {
    const rows = (await this.req('readonly', (st) => st.getAll())) || [];
    rows.forEach((r) => pcLib.cached.set(r.id, r.m));
    if (rows.length > PC_KEEP) {
      // on garde d'abord la dernière version de chaque projet, puis les plus récents
      const keep = new Set(pcTargets().map((f) => f.f));
      rows.sort((a, b) => (keep.has(a.id) - keep.has(b.id)) || (a.at - b.at)).slice(0, rows.length - PC_KEEP).forEach((r) => this.del(r.id));
    }
  },
};

const pcAttachment = (d) => {
  const u = String(d?.attachment?.url || '');
  return u.startsWith(`${NTFY}/file/`) ? u : null;
};
function pcSeen(d) {
  if (!pc.info) return;
  pc.info = { ...pc.info, at: Math.max(pc.info.at || 0, (d.time || 0) * 1000), offline: false };
  local.set('pcInfo', pc.info);
}

// Messages du PC propres à cet onglet. Renvoie true si le message est traité.
function onPcViewMessage(d, m, fresh) {
  if (m.lib) { pcSeen(d); onPcLib(d, m); return true; }
  if (m.aud) { pcSeen(d); onPcAudio(d, m, fresh); return true; }
  if (m.q && typeof m.q === 'object') {
    pcSeen(d);
    const v = String(m.q.v || '');
    if (/^[\w-]{11}$/.test(v) && (d.time || 0) * 1000 > (pc.cur?.at || 0) && pc.queue[v]?.state !== 'done') {
      pc.cur = { v, t: String(m.q.t || pc.queue[v]?.t || v).slice(0, 160), left: Math.max(0, Number(m.q.left) || 0), at: (d.time || 0) * 1000 };
      renderPcView();
    }
    return true;
  }
  if (m.sync && typeof m.sync === 'object') {
    pcSeen(d);
    pcLib.syncInfo = { left: Math.max(0, Number(m.sync.left) || 0), wait: Math.max(0, Number(m.sync.wait) || 0), at: (d.time || 0) * 1000 };
    renderPcView();
    return true;
  }
  if (m.cmd) {
    pcSeen(d);
    const p = String(m.p || '');
    if (!m.ok) pcLib.cmds = pcLib.cmds.filter((c) => !(c.msg.p === p && c.msg.cmd === m.cmd && c.at < (d.time || 0) * 1000));
    savePcLib();
    if (fresh) {
      const what = { ren: 'Projet renommé sur ton PC', style: 'Icône et couleur changées sur ton PC', fav: 'Favori mis à jour sur ton PC' }[m.cmd] || 'Fait sur ton PC';
      toast(m.ok ? (m.new ? `${what} : ${String(m.new).slice(0, 80)}` : what) : `Le PC n’a pas pu le faire : ${String(m.err || '').slice(0, 90)}`);
    }
    renderPcView();
    return true;
  }
  return false;
}

async function onPcLib(d, m) {
  const url = pcAttachment(d);
  const at = Number(m.at) || 0;
  if (!url || (pcLib.data && pcLib.data.at >= at)) return;
  try {
    const res = await fetch(url);
    if (!res.ok) return;
    const lib = sanitizeLib(await res.json());
    if (!lib || (pcLib.data && pcLib.data.at >= lib.at)) return;
    pcLib.data = lib;
    // les changements que le PC a reçus avant cette liste y sont déjà
    pcLib.cmds = pcLib.cmds.filter((c) => c.at > lib.at * 1000 + 2000);
    savePcLib();
    renderPcView();
    pcSync();
  } catch { /* pièce jointe expirée (3 h) : on garde la liste qu'on a */ }
}

async function onPcAudio(d, m, fresh) {
  const fid = String(m.aud || '');
  if (!/^[a-f0-9]{12}$/.test(fid)) return;
  if (m.err) {
    if (pcLib.waiting === fid) { pcLib.waiting = null; renderPcView(); if (fresh) toast(String(m.err).slice(0, 100)); }
    return;
  }
  const url = pcAttachment(d);
  const i = Number(m.i);
  const of = Number(m.of);
  const mt = Number(m.m) || 0;
  if (!url || !(of >= 1 && of <= 8 && i >= 0 && i < of)) return;
  if ((pcLib.cached.get(fid) || -1) >= mt) return;
  const key = `${fid}:${mt}`;
  const e = pcLib.parts[key] || (pcLib.parts[key] = { urls: Array(of).fill(null) });
  e.urls[i] = url;
  if (e.urls.some((x) => !x)) return;
  delete pcLib.parts[key];
  try {
    const blobs = await Promise.all(e.urls.map(async (u) => { const r = await fetch(u); if (!r.ok) throw new Error(String(r.status)); return r.blob(); }));
    const blob = new Blob(blobs, { type: 'audio/mp4' });
    if (!blob.size || blob.size > 16e6) return;
    await pcAudioStore.put({ id: fid, m: mt, blob, n: String(m.n || '').slice(0, 140), v: String(m.v || '').slice(0, 20), p: String(m.p || '').slice(0, 260), at: Date.now() });
    if (pcLib.cached.size > PC_KEEP) pcAudioStore.load();
    if (pcLib.waiting === fid) { pcLib.waiting = null; playPcBlob(fid, blob); }
    renderPcView();
  } catch {
    if (pcLib.waiting === fid) { pcLib.waiting = null; renderPcView(); toast('Son pas récupéré : réessaie'); }
  }
}

// --- Synchronisation : la dernière version de chaque projet (sinon l'instru) est
// gardée sur ce téléphone, pour l'écouter même PC éteint. Le téléphone dit au PC ce qui
// lui manque ; le PC l'envoie petit à petit (limites de ntfy.sh : ~10 sons par 3 h).
const pcTarget = (p) => p.files.find((f) => f.l) || p.files.find((f) => f.i) || null;
const pcTargets = () => pcProjects().map(pcTarget).filter(Boolean);
const pcHas = (f) => (pcLib.cached.has(f.f) ? pcLib.cached.get(f.f) : -1) >= f.m;
const pcSyncState = { at: 0, sig: '' };
function pcSync(force) {
  if (!WEB || !pc.info || !pcLib.data || !pcOn() || versionLt(pc.info.version, '3.11.0')) return;
  const miss = pcTargets().filter((f) => !pcHas(f)).map((f) => f.f);
  if (!miss.length) { pcLib.syncInfo = null; return; }
  const sig = miss.join(',');
  if (!force && sig === pcSyncState.sig && Date.now() - pcSyncState.at < 10 * 60e3) return;
  Object.assign(pcSyncState, { sig, at: Date.now() });
  ntfyPublish({ cmd: 'sync', f: miss.slice(0, 300) }).catch(() => { pcSyncState.at = 0; });
}

function askPcLib(force) {
  if (!WEB || !pc.info) return;
  if (!force && (Date.now() - pcLib.askedAt < 90e3 || (pcLib.data && Date.now() - pcLib.data.at * 1000 < 5 * 60e3))) return;
  pcLib.askedAt = Date.now();
  ntfyPublish({ cmd: 'lib' }).then(() => { if (force) toast(pcOn() ? 'Le PC envoie sa liste…' : 'PC éteint : la liste arrivera quand il se rallume'); }).catch(() => { if (force) toast('Pas de réseau'); });
}

async function pcCommand(msg, label) {
  const c = { id: randHex(6), msg, at: Date.now(), lastSent: 0 };
  pcLib.cmds.push(c);
  savePcLib();
  renderPcView();
  try {
    await ntfyPublish(msg);
    c.lastSent = Date.now();
    toast(pcOn() ? `${label}…` : `${label} : ton PC est éteint, ce sera fait dès qu’il se rallume`);
  } catch {
    toast(`${label} : pas de réseau, ça partira dès que tu en as`);
  }
  savePcLib();
}
// Changements pas encore confirmés par le PC : renvoyés s'il était éteint trop longtemps
async function resendPcCmds() {
  for (const c of pcLib.cmds) {
    if (c.lastSent && Date.now() - c.lastSent < 10 * 3600e3) continue;
    try { await ntfyPublish(c.msg); c.lastSent = Date.now(); } catch { break; }
  }
  savePcLib();
}

function pcProjects() {
  const ps = (pcLib.data?.projects || []).map((p) => ({ ...p }));
  for (const c of pcLib.cmds) {
    const p = ps.find((x) => x.p === c.msg.p);
    if (!p) continue;
    p.pending = true;
    if (c.msg.cmd === 'fav') p.fav = c.msg.on ? 1 : 0;
    if (c.msg.cmd === 'style') { p.c = c.msg.c || p.c; p.ic = c.msg.i || p.ic; }
    if (c.msg.cmd === 'ren') { p.t = c.msg.t; p.renaming = true; }
  }
  return ps;
}

// --- Lecture
function pcFindFile(fid) {
  for (const p of pcProjects()) {
    const f = p.files.find((x) => x.f === fid);
    if (f) return { p, f };
  }
  return null;
}
// « Haze [C# min, 150 BPM] [FFP] » → « Haze » (la clé / le BPM sont déjà sur la carte)
const pcName = (n) => String(n || '').replace(/(\s*\[[^[\]]*\])+\s*$/, '').trim() || String(n || '');
function pcStop(silent) {
  const a = pcPlayer.audio;
  if (a) { a.pause(); a.onended = null; a.ontimeupdate = null; a.onplay = null; a.onpause = null; URL.revokeObjectURL(pcPlayer.url); }
  Object.assign(pcPlayer, { audio: null, fid: null, url: '' });
  renderPcMini();
  if (!silent) renderPcView();
}
function pcSeek(e) {
  e.stopPropagation();
  const a = pcPlayer.audio;
  if (!a?.duration) return;
  const r = e.currentTarget.getBoundingClientRect();
  a.currentTime = Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)) * a.duration;
  pcProgress();
}
function pcProgress() {
  const a = pcPlayer.audio;
  if (!a) return;
  const pct = a.duration ? (a.currentTime / a.duration) * 100 : 0;
  $$(`.pcf[data-f="${pcPlayer.fid}"] .pcf-prog i, #pcMini .pcm-bar i`).forEach((i) => { i.style.width = `${pct}%`; });
  const t = `${fmtTime(a.currentTime)} / ${fmtTime(a.duration || 0)}`;
  $$(`.pcf[data-f="${pcPlayer.fid}"] .pcf-time, #pcMini .pcm-time`).forEach((el) => { el.textContent = t; });
}
function playPcBlob(fid, blob) {
  pcStop(true);
  if (player.item) stopPlayer();
  stopTake();
  const url = URL.createObjectURL(blob);
  const a = pcAudioEl();
  a.src = url;
  a.onended = () => pcStop();
  a.ontimeupdate = pcProgress;
  a.onplay = () => { renderPcMini(); renderPcView(); };
  a.onpause = () => { renderPcMini(); renderPcView(); };
  Object.assign(pcPlayer, { audio: a, fid, url });
  a.play().catch(() => {
    // le son est arrivé longtemps après le toucher : le navigateur demande un nouveau toucher
    if (pcPlayer.audio === a) pcStop();
    toast('Son prêt : touche ▶ pour l’écouter');
  });
  renderPcMini();
  renderPcView();
}
// Barre de lecture en bas de l'écran : reste visible quand on fait défiler
function renderPcMini() {
  let bar = $('#pcMini');
  const a = pcPlayer.audio;
  if (!a) {
    if (bar) bar.hidden = true;
    document.body.classList.remove('pc-playing');
    return;
  }
  if (!bar) { bar = h('div', { class: 'pc-mini', id: 'pcMini', role: 'region', 'aria-label': 'Lecture d’un son du PC' }); document.body.append(bar); }
  const hit = pcFindFile(pcPlayer.fid);
  bar.style.setProperty('--pc', hit?.p.c || '#8b5cf6');
  bar.replaceChildren(
    h('span', { class: 'pc-tile sm' }, hit?.p.ic || '♪'),
    h('div', { class: 'pcm-main' },
      h('b', {}, hit ? (hit.f.i ? pcName(hit.p.t) : pcName(hit.f.n)) : 'Son du PC'),
      h('span', {}, hit ? `${hit.f.i ? 'Instru' : hit.f.v || hit.f.e.toUpperCase()} · ${pcName(hit.p.t)}` : ''),
      h('div', { class: 'pcm-bar', onclick: pcSeek }, h('i'))),
    h('span', { class: 'pcm-time' }, '0:00'),
    h('button', { type: 'button', class: 'pcm-btn', 'aria-label': a.paused ? 'Lecture' : 'Pause', onclick: () => (a.paused ? a.play().catch(() => {}) : a.pause()) }, icon(a.paused ? 'play' : 'pause')),
    h('button', { type: 'button', class: 'icon-btn', 'aria-label': 'Arrêter', onclick: () => pcStop() }, icon('x')));
  bar.hidden = false;
  document.body.classList.add('pc-playing');
  pcProgress();
}
async function playPcFile(f) {
  if (pcPlayer.fid === f.f && pcPlayer.audio) {
    const a = pcPlayer.audio;
    if (a.paused) a.play().catch(() => {}); else a.pause();
    return;
  }
  unlockPcAudio();
  const have = await pcAudioStore.get(f.f);
  if (have && (have.m >= f.m || !pcOn())) {
    if (have.m < f.m) toast('Version gardée sur ce téléphone (le son a changé depuis sur le PC)');
    playPcBlob(f.f, have.blob);
    return;
  }
  if (!pcOn()) { toast('PC éteint : ce son n’a pas encore été gardé sur ce téléphone'); return; }
  pcLib.waiting = f.f;
  renderPcView();
  try {
    await ntfyPublish({ cmd: 'play', f: f.f });
    toast('Le PC prépare le son… (quelques secondes)');
  } catch { pcLib.waiting = null; renderPcView(); toast('Pas de réseau'); return; }
  setTimeout(() => { if (pcLib.waiting === f.f) { pcLib.waiting = null; renderPcView(); toast('Pas de réponse du PC pour ce son'); } }, 120e3);
}

// --- Gestion (renommer, icône et couleur, favori)
function pcRename(p) {
  const inp = h('input', { type: 'text', class: 'pc-input', value: p.t, maxlength: 110, 'aria-label': 'Nouveau nom' });
  const err = h('p', { class: 'hint', style: 'color:var(--paid);min-height:1.2em;margin:6px 0 0' });
  const go = h('button', { type: 'button', class: 'primary' }, 'Renommer');
  const submit = () => {
    const t = inp.value.replace(/\s+/g, ' ').trim();
    if (!t) { err.textContent = 'Choisis un nom.'; return; }
    if (/[\\/:*?"<>|]/.test(t)) { err.textContent = 'Pas de \\ / : * ? " < > | dans un nom de fichier Windows.'; return; }
    if (t === p.t) { closeDrawer(); return; }
    closeDrawer();
    pcCommand({ cmd: 'ren', p: p.p, t }, 'Renommage envoyé au PC');
  };
  go.addEventListener('click', submit);
  inp.addEventListener('keydown', (e) => { if (e.key === 'Enter') submit(); });
  openDrawer('Renommer le projet', [
    h('p', { class: 'muted', style: 'margin:0' }, 'Sur ton PC, le dossier du projet, la prod, le projet FL et tous les fichiers à son nom prennent le nouveau nom (tout ou rien). La clé, le BPM et la licence restent.'),
    inp, err, h('div', { class: 'actions' }, go),
  ]);
  setTimeout(() => { inp.focus(); inp.select(); }, 80);
}
function pcStyle(p) {
  const lib = pcLib.data || { palette: ['#8b5cf6'], icons: ['♪'] };
  const st = { c: p.c, i: p.ic };
  const prev = h('span', { class: 'pc-tile big' });
  const sw = h('div', { class: 'pc-swatches' });
  const ig = h('div', { class: 'pc-icons' });
  const paint = () => {
    prev.style.setProperty('--pc', st.c);
    prev.textContent = st.i;
    $$('button', sw).forEach((b) => b.classList.toggle('on', b.dataset.c === st.c));
    $$('button', ig).forEach((b) => { b.classList.toggle('on', b.textContent === st.i); b.style.setProperty('--pc', st.c); });
  };
  lib.palette.forEach((c) => sw.append(h('button', { type: 'button', 'data-c': c, style: `--sw:${c}`, 'aria-label': `Couleur ${c}`, onclick: () => { st.c = c; paint(); } })));
  lib.icons.forEach((i) => ig.append(h('button', { type: 'button', onclick: () => { st.i = i; paint(); } }, i)));
  const save = h('button', { type: 'button', class: 'primary', onclick: () => { closeDrawer(); pcCommand({ cmd: 'style', p: p.p, c: st.c, i: st.i }, 'Icône et couleur envoyées au PC'); } }, 'Enregistrer');
  const reset = h('button', { type: 'button', class: 'ghost', onclick: () => { closeDrawer(); pcCommand({ cmd: 'style', p: p.p, c: null, i: null }, 'Style par défaut envoyé au PC'); } }, 'Par défaut');
  openDrawer('Icône et couleur', [
    h('div', { class: 'pc-style-head' }, prev, h('b', {}, p.t)),
    h('div', { class: 'd-sec' }, h('h4', {}, 'Couleur'), sw),
    h('div', { class: 'd-sec' }, h('h4', {}, 'Icône'), ig),
    h('div', { class: 'actions' }, save, reset),
  ]);
  paint();
}

// --- Affichage
function pcFileRow(p, f) {
  const cur = pcPlayer.fid === f.f && !!pcPlayer.audio;
  const playing = cur && !pcPlayer.audio.paused;
  const loading = pcLib.waiting === f.f;
  const kept = pcLib.cached.has(f.f);
  const target = pcTarget(p)?.f === f.f;
  const state = loading ? 'Le PC envoie ce son…' : kept ? (pcHas(f) ? 'Sur ce téléphone · écoutable hors ligne' : 'Sur ce téléphone (ancienne copie)')
    : target ? (pcOn() ? 'Arrive sur ce téléphone…' : 'Arrivera quand le PC sera allumé') : pcOn() ? 'Sur le PC · touche pour l’écouter' : 'Sur le PC (éteint)';
  const sub = cur ? null : `${state}${f.e && f.e !== 'wav' ? ` · ${f.e.toUpperCase()}` : ''}`;
  return h('div', { class: `pcf${cur ? ' on' : ''}${f.i ? ' instru' : f.v ? ' ver' : ''}`, 'data-f': f.f },
    h('button', { type: 'button', class: `pcf-play${loading ? ' loading' : ''}`, 'aria-label': playing ? 'Pause' : `Écouter ${f.n}`, onclick: () => playPcFile(f) }, icon(playing ? 'pause' : 'play')),
    h('div', { class: 'pcf-main', onclick: () => playPcFile(f) },
      h('div', { class: 'pcf-line' }, f.v ? h('span', { class: 'pcf-tag' }, f.v) : null, h('b', { title: f.n }, f.i ? 'Instru' : pcName(f.n)), f.l ? h('span', { class: 'pcf-last' }, 'dernière') : null),
      cur ? h('div', { class: 'pcf-prog', onclick: pcSeek }, h('i')) : null,
      h('span', { class: 'pcf-sub' }, cur ? h('span', { class: 'pcf-time' }, '0:00') : sub)),
    kept ? h('span', { class: 'pcf-kept', title: 'Écoutable même PC éteint' }) : null);
}
function pcCard(p) {
  const files = p.files || [];
  const instru = files.filter((f) => f.i);
  const vers = files.filter((f) => !f.i && f.v);
  const other = files.filter((f) => !f.i && !f.v);
  const open = pcLib.open.has(p.p);
  const chip = (txt, cls) => (txt ? h('span', { class: `pcp-chip ${cls || ''}` }, txt) : null);
  const sec = (title, list) => (list.length ? h('div', { class: 'pcp-sec' }, h('h5', {}, title), ...list.map((f) => pcFileRow(p, f))) : null);
  return h('article', { class: `pcp${p.fav ? ' fav' : ''}${p.pending ? ' pending' : ''}`, style: `--pc:${p.c}` },
    h('div', { class: 'pcp-top' },
      h('span', { class: 'pc-tile' }, p.ic),
      h('div', { class: 'pcp-tt' }, h('b', { title: p.t }, pcName(p.t)),
        h('span', {}, p.renaming ? 'Renommage en attente du PC…' : [p.fl ? 'Projet FL' : 'Prod', p.d ? fmtAgo(p.d * 1000) : '', vers.length ? `${vers.length} version${vers.length > 1 ? 's' : ''}` : ''].filter(Boolean).join(' · ')),
        pcTarget(p) ? h('em', { class: `pcp-off${pcHas(pcTarget(p)) ? ' ok' : ''}` }, pcHas(pcTarget(p)) ? '✓ Écoutable hors ligne' : '↓ Arrive sur ce téléphone') : null),
      h('button', { type: 'button', class: `pcp-star${p.fav ? ' on' : ''}`, 'aria-label': p.fav ? 'Retirer des favoris' : 'Mettre en favori',
        onclick: () => pcCommand({ cmd: 'fav', p: p.p, on: !p.fav }, p.fav ? 'Retiré des favoris' : 'Mis en favori') }, icon('star'))),
    p.k || p.b || p.lic ? h('div', { class: 'pcp-chips' }, chip(p.k, p.tb.includes('key') ? 'tb' : ''), chip(p.b ? `${p.b} BPM` : '', p.tb.includes('bpm') ? 'tb' : ''), chip(p.lic, 'lic')) : null,
    files.length ? null : h('p', { class: 'hint', style: 'margin:0' }, 'Aucun son dans ce projet.'),
    sec('Instru', instru),
    sec(`Versions · ${vers.length}`, vers),
    other.length ? h('div', { class: 'pcp-sec' },
      h('button', { type: 'button', class: 'pcp-more', 'aria-expanded': open ? 'true' : 'false', onclick: () => { if (open) pcLib.open.delete(p.p); else pcLib.open.add(p.p); renderPcView(); } },
        `${open ? '▾' : '▸'} Autres sons · ${other.length}`),
      ...(open ? other.map((f) => pcFileRow(p, f)) : [])) : null,
    h('div', { class: 'pcp-acts' },
      h('button', { type: 'button', class: 'ghost', disabled: p.renaming, onclick: () => pcRename(p) }, 'Renommer'),
      h('button', { type: 'button', class: 'ghost', onclick: () => pcStyle(p) }, 'Icône et couleur')));
}
function fmtAgo(ms) {
  const s = (Date.now() - ms) / 1000;
  return s < 90 ? 'à l’instant' : s < 3600 ? `il y a ${Math.round(s / 60)} min` : s < 86400 ? `il y a ${Math.round(s / 3600)} h` : s < 86400 * 30 ? `il y a ${Math.round(s / 86400)} j` : new Date(ms).toLocaleDateString('fr-FR');
}
const versionLt = (a, b) => {
  const x = String(a || '0').split('.').map(Number);
  const y = String(b).split('.').map(Number);
  for (let i = 0; i < 3; i++) if ((x[i] || 0) !== (y[i] || 0)) return (x[i] || 0) < (y[i] || 0);
  return false;
};
function syncPcNav() {
  const dot = $('#pcNavDot');
  if (!dot) return;
  const n = Object.values(pc.queue).filter((q) => q.state === 'sent' || q.state === 'unsent' || q.state === 'sending').length;
  dot.hidden = !n;
  dot.textContent = String(n);
}
function pcUpdateBtn() {
  const b = h('button', { type: 'button', class: 'primary' }, 'Mettre à jour le PC');
  b.addEventListener('click', async () => {
    b.disabled = true;
    try { await ntfyPublish({ update: 1 }); toast(pcOn() ? 'Le PC se met à jour… il revient tout seul' : 'PC éteint : il se mettra à jour en se rallumant'); } catch { toast('Pas de réseau'); }
    setTimeout(() => { b.disabled = false; }, 5000);
  });
  return b;
}
function renderPcView() {
  syncPcNav();
  const view = $('#view-pc');
  if (!WEB || !view?.classList.contains('active')) return;
  // --- état + file d'attente
  const st = pcStatusText(true);
  if (pc.cur && (Date.now() - pc.cur.at > 30 * 60e3 || pc.queue[pc.cur.v]?.state === 'done' || pc.queue[pc.cur.v]?.state === 'error')) pc.cur = null;
  const waiting = Object.entries(pc.queue).filter(([id, q]) => (q.state === 'sent' || q.state === 'unsent' || q.state === 'sending') && id !== pc.cur?.v)
    .sort((a, b) => (a[1].at || 0) - (b[1].at || 0));
  const recent = Object.entries(pc.queue).filter(([, q]) => q.state === 'done' || q.state === 'error').sort((a, b) => (b[1].at || 0) - (a[1].at || 0)).slice(0, 3);
  const row = ([id, q], n) => h('div', { class: `pc-row ${q.state}` },
    n != null ? h('span', { class: 'pcq-n' }, String(n + 1)) : h('span', { class: 'pc-ico' }, icon(q.state === 'done' ? 'check' : 'x')),
    h('div', { class: 'pc-row-main' }, h('b', {}, displayTitle(q.t || id)),
      h('span', {}, q.state === 'done' ? pcName(String(q.file || 'Sur ton PC').replace(/\.wav$/i, '')) : q.state === 'error' ? (q.err || 'Erreur') : q.state === 'unsent' ? 'Partira dès que tu as du réseau' : pcOn() ? 'En file d’attente sur le PC' : 'Arrivera dès que le PC se rallume')),
    q.state !== 'done' ? h('button', { type: 'button', class: 'ghost sm', onclick: () => sendToPc({ id, url: `https://www.youtube.com/watch?v=${id}`, title: q.t }) }, 'Renvoyer') : null);
  const old = pc.info?.version && versionLt(pc.info.version, '3.11.0');
  $('#pcLive').replaceChildren(...[
    h('div', { class: `pc-status${st.ok ? ' ok' : ''}${st.off ? ' off' : ''}` }, h('span', { class: 'pc-led', 'aria-hidden': 'true' }), h('div', {}, h('b', {}, st.t), h('span', {}, st.s))),
    !pc.info ? h('div', { class: 'actions' }, h('button', { type: 'button', class: 'primary', onclick: () => openPcSetup() }, 'Connecter mon PC')) : null,
    old ? h('div', { class: 'pc-old' }, h('div', {}, h('b', {}, `Ton PC a la version ${pc.info.version}`),
      h('span', {}, 'Mets-le à jour : tes projets et la dernière version de chacun arrivent alors tout seuls sur ce téléphone, écoutables même PC éteint.')), pcUpdateBtn()) : null,
    pc.cur ? h('div', { class: 'pcq-cur' }, h('span', { class: 'pcq-k' }, 'En cours'), h('b', {}, displayTitle(pc.cur.t)),
      h('span', {}, `Téléchargement et conversion en WAV sur ton PC${pc.cur.left ? ` · +${pc.cur.left} derrière` : ''}`), h('div', { class: 'pcq-bar' }, h('i'))) : null,
    waiting.length ? h('div', { class: 'pcq-sec' }, h('h4', {}, `En attente · ${waiting.length}`), h('div', { class: 'pc-list' }, waiting.map((e, n) => row(e, n)))) : null,
    !pc.cur && !waiting.length && pc.info ? h('p', { class: 'hint pcq-empty' }, 'Rien en cours ni en attente. Touche ', icon('down'), ' sur une prod pour l’envoyer sur ton PC.') : null,
    recent.length ? h('div', { class: 'pcq-sec' }, h('h4', {}, 'Dernières arrivées'), h('div', { class: 'pc-list' }, recent.map((e) => row(e)))) : null,
  ].filter(Boolean));
  // --- projets du PC
  const all = pcProjects();
  const q = strip(pcLib.q).toLowerCase();
  const list = all.filter((p) => (pcLib.filter !== 'fav' || p.fav) && (!q || strip(`${p.t} ${p.k} ${p.files.map((f) => `${f.n} ${f.v}`).join(' ')}`).toLowerCase().includes(q)));
  const tg = all.map(pcTarget).filter(Boolean);
  const have = tg.filter(pcHas).length;
  const si = pcLib.syncInfo && Date.now() - pcLib.syncInfo.at < 6 * 3600e3 ? pcLib.syncInfo : null;
  const waitTxt = si?.left && si.wait > 120 ? ` · ${si.left} en route, reprise dans ~${si.wait >= 3600 ? `${Math.floor(si.wait / 3600)} h ${String(Math.round((si.wait % 3600) / 60)).padStart(2, '0')}` : `${Math.round(si.wait / 60)} min`} (limite du relais gratuit)` : '';
  $('#pcLibMeta').textContent = pcLib.data ? `${list.length} projet${list.length > 1 ? 's' : ''}${list.length !== all.length ? ` sur ${all.length}` : ''} · liste du PC ${fmtAgo(pcLib.data.at * 1000)}` : '';
  const sync = $('#pcSync');
  if (sync) {
    sync.hidden = !pcLib.data || !tg.length;
    sync.replaceChildren(h('div', { class: 'pcs-top' }, h('b', {}, `${have} / ${tg.length} sons sur ce téléphone`),
      h('span', {}, have === tg.length ? 'Tout s’écoute même PC éteint' : pcOn() ? `Le PC envoie les autres${waitTxt}` : 'Les autres arriveront quand le PC sera allumé')),
      h('div', { class: 'pcs-bar' }, h('i', { style: `width:${tg.length ? (have / tg.length) * 100 : 0}%` })));
  }
  $$('#pcLibSeg .seg-btn').forEach((b) => b.classList.toggle('active', b.dataset.f === pcLib.filter));
  const grid = $('#pcLibGrid');
  if (!pcLib.data) {
    grid.replaceChildren(h('p', { class: 'muted' }, !pc.info ? 'Connecte ton PC pour voir tes projets ici.' : old ? 'La liste de tes projets arrivera après la mise à jour du PC.' : pcOn() ? 'Le PC envoie la liste de tes projets…' : 'La liste de tes projets arrivera dès que le PC sera allumé.'));
    return;
  }
  grid.replaceChildren(...(list.length ? list.slice(0, 120).map(pcCard) : [h('p', { class: 'muted' }, all.length ? 'Aucun projet ne correspond.' : 'Aucun projet dans le dossier des projets du PC.')]));
}

function cmdBlock(text) {
  return h('div', { class: 'cmd' }, h('code', {}, text), h('button', { type: 'button', class: 'ghost', onclick: () => copyText(text) }, 'Copier'));
}
const PC_EXE_URL = 'https://github.com/kimany91/Melofinds/releases/latest/download/MelofindsSetup.exe';
function openPcSetup(pending) {
  listenPc();
  const pairing = `${pcCode()}.${pcKey()}`;
  const resetBtn = (b, label) => { b.disabled = false; b.textContent = label; };
  const test = h('button', { type: 'button', class: 'primary' }, 'Tester la connexion');
  test.addEventListener('click', async () => {
    test.disabled = true;
    test.textContent = 'J’attends ton PC… (jusqu’à 30 s)';
    const timer = setTimeout(() => { pc.onPong = null; resetBtn(test, 'Tester la connexion'); toast('Pas de réponse : MelofindsPC est-il installé et le PC allumé ?'); }, 35e3);
    pc.onPong = () => {
      clearTimeout(timer); pc.onPong = null; resetBtn(test, 'Tester la connexion'); toast('PC connecté !');
      if (pending) { const p = pending; pending = null; sendToPc(p); }
    };
    try { await ntfyPublish({ ping: 1 }); } catch { clearTimeout(timer); pc.onPong = null; resetBtn(test, 'Tester la connexion'); toast('Envoi impossible : vérifie ta connexion'); }
  });
  const upd = h('button', { type: 'button', class: 'ghost' }, 'Mettre à jour le PC');
  upd.addEventListener('click', async () => {
    upd.disabled = true;
    try { await ntfyPublish({ update: 1 }); toast('Demande envoyée : le PC vérifie s’il y a une nouvelle version'); } catch { toast('Envoi impossible : vérifie ta connexion'); }
    setTimeout(() => { upd.disabled = false; }, 4000);
  });
  openDrawer('Télécharger sur mon PC', [
    h('p', { class: 'muted', style: 'margin:0' }, 'Touche ', icon('down'), ' sur une prod : elle arrive en .wav sur ton PC, même si tu es loin (5G ou Wi-Fi). Il faut juste que le PC soit allumé.'),
    h('div', { id: 'pcStatus' }),
    h('div', { class: 'd-sec' }, h('h4', {}, '1. Installer Melofinds PC (sur le PC Windows)'),
      h('a', { class: 'primary dl-exe', href: PC_EXE_URL, target: '_blank', rel: 'noopener' }, icon('down'), 'MelofindsSetup.exe'),
      h('p', { class: 'hint' }, 'Ouvre ce lien sur ton PC (ou envoie-le-toi), lance le fichier : choisis où installer le programme et où arrivent les prods. Il installe tout seul ce qui manque et crée un raccourci « Melofinds PC » sur le bureau.'),
      h('p', { class: 'hint' }, 'Si Windows affiche « Windows a protégé votre ordinateur » : « Informations complémentaires » → « Exécuter quand même » (le programme n’est pas signé par Microsoft, c’est normal).')),
    h('div', { class: 'd-sec' }, h('h4', {}, '2. Ajouter ce téléphone'),
      cmdBlock(pairing),
      h('p', { class: 'hint' }, 'Colle ce code dans l’installateur, ou plus tard : raccourci « Melofinds PC » → onglet « Appareils » → « Ajouter un appareil ». Chaque téléphone a son propre code.'),
      h('p', { class: 'hint' }, 'Dans le panneau Melofinds PC : « Mettre en ligne » / « Mettre hors ligne », démarrage automatique avec l’ordinateur, appareils connectés, dossier des prods.')),
    h('div', { class: 'd-sec' }, h('h4', {}, '3. Vérifier'), h('div', { class: 'actions' }, test, upd)),
    h('div', { class: 'd-sec' }, h('h4', {}, 'Envois récents'), h('div', { id: 'pcList', class: 'pc-list' })),
    h('div', { class: 'd-sec' }, h('h4', {}, 'Sécurité'),
      h('ul', { class: 'reasons' },
        h('li', {}, 'Chaque envoi est signé avec ta clé secrète (dans le code ci-dessus), qui ne passe jamais par Internet. Sans elle, le PC ignore l’envoi.'),
        h('li', {}, 'Un envoi contient seulement l’identifiant de la vidéo : jamais de lien, de fichier ou de commande.'),
        h('li', {}, 'Le PC n’écrit que des .wav vérifiés, dans le seul dossier choisi sur le PC (impossible à changer à distance). Nom : « Titre [Clé, BPM].wav », sans « free ».'),
        h('li', {}, 'Mises à jour : uniquement les versions officielles publiées sur ton GitHub, avec empreinte vérifiée. Il vérifie aussi tout seul une fois par jour.'),
        h('li', {}, 'Limites : vidéos de 15 min max, 40 téléchargements par heure, envois de plus de 48 h refusés.'))),
    h('p', { class: 'hint' }, 'Ne partage pas ce code. ',
      h('button', { type: 'button', class: 'link', onclick: () => { local.set('pcCode', ''); local.set('pcKey', ''); pc.info = null; local.set('pcInfo', null); pc.es?.close(); pc.es = null; openPcSetup(); toast('Nouveau code : sur le PC, ouvre MelofindsPC → « Changer le code / dossier »'); } }, 'Changer de code')),
    h('p', { class: 'hint' }, 'L’audio YouTube contient souvent le tag du beatmaker ; la version sans tag s’obtient via le lien de sa description. Si le PC est éteint plus de 12 h, renvoie la prod.'),
  ]);
  renderPcStatus();
}

// Bouton « remonter aux filtres » quand la barre de filtres est sortie de l'écran
(() => {
  const btn = $('#toTop');
  btn.addEventListener('click', () => $('#results').scrollIntoView({ behavior: 'smooth', block: 'start' }));
  let ticking = false;
  window.addEventListener('scroll', () => {
    if (ticking) return;
    ticking = true;
    requestAnimationFrame(() => {
      ticking = false;
      const bar = $('#rbar');
      const out = !$('#results').hidden && $('#view-search').classList.contains('active') && bar.getBoundingClientRect().bottom < 0;
      btn.classList.toggle('show', out);
    });
  }, { passive: true });
})();

function setupTarget() {
  document.body.classList.add(WEB ? 'web' : 'claude-page');
  if (WEB) {
    $('#navRecs').hidden = false;
    $('#navPc').hidden = false;
    $('#pcLibSearch').addEventListener('input', (e) => { pcLib.q = e.target.value; renderPcView(); });
    $$('#pcLibSeg .seg-btn').forEach((b) => b.addEventListener('click', () => { pcLib.filter = b.dataset.f; local.set('pcLibFilter', pcLib.filter); renderPcView(); }));
    $('#pcLibRefresh').addEventListener('click', () => askPcLib(true));
    $('#pcSetupBtn').addEventListener('click', () => openPcSetup());
    pcAudioStore.load().then(() => { renderPcView(); pcSync(); });
    setInterval(() => pcSync(), 5 * 60e3);
    try { navigator.storage?.persist?.(); } catch { /* le navigateur décide */ }
    const keyBtn = h('button', { type: 'button', class: 'link', id: 'keyBtn', onclick: openKeySettings }, ytKey() ? 'Clé YouTube' : 'Descriptions complètes (clé YouTube, facultatif)');
    $('.results-foot').append(keyBtn);
    if (!ytKey()) pipedInstances();
    const pcBtn = h('button', { type: 'button', class: 'verify-btn pc-head', id: 'pcHead', title: 'Télécharger les prods sur mon PC', onclick: () => openPcSetup() }, icon('down'), h('span', {}, 'Mon PC'), h('em', { class: 'dot', id: 'pcDot', hidden: !pc.info }, '✓'));
    $('#openVerify').before(pcBtn);
    if (pc.info || Object.values(pc.queue).some((q) => q.state === 'sent')) listenPc();
    syncPcUi();
    setTimeout(resendPending, 6000);
    setInterval(resendPending, 20 * 60e3);
    window.addEventListener('online', () => setTimeout(resendPending, 1500));
    $('.hero-sub').textContent = 'Décris la vibe ou cite un rappeur (Luther, Damso, Bu$hi…). Je trouve les type beats sur YouTube, je lis chaque description pour vérifier la licence, et tu écoutes direct ici.';
  } else {
    $('#hero').append(h('p', { class: 'web-tip' }, icon('play'), 'Pour écouter les prods sans quitter l’app, ouvre ',
      h('a', { href: WEB_URL, target: '_blank', rel: 'noopener' }, 'Melofinds Web'), '. La page Claude interdit les lecteurs vidéo.'));
  }
}

applyDevice();
syncBpmPill();
syncVerifiedPill();
restoreSession();
renderHistory();
renderSavedProds();
renderSavedSearches();
updateDots();
setSeg('prods');
showView(location.hash.slice(1) || local.get('view', 'search'));
setupTarget();
persist.init();
window.claude?.use?.('sample').then((s) => { sampleFn = s || null; }).catch(() => {});
})();
