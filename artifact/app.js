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

const VIEWS = ['search', 'saved', 'history'];
function showView(name) {
  if (!VIEWS.includes(name)) name = 'search';
  $$('.nav-item').forEach((t) => { const on = t.dataset.view === name; t.classList.toggle('active', on); t.setAttribute('aria-selected', on); });
  $$('.view').forEach((v) => v.classList.toggle('active', v.id === `view-${name}`));
  local.set('view', name);
  if (name === 'saved') { renderSavedProds(); renderSavedSearches(); }
  if (name === 'history') renderHistory();
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
function analyzed(item, plan) {
  const key = `${(item.description || '').length}|${item.title}|${plan ? 1 : 0}`;
  if (item._r && item._key === key) return item._r;
  const r = analyzeVideo({ id: item.id, title: item.title, description: item.description || '', foundBy: item.foundBy }, plan || null);
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
    h('span', { class: 'cover-meta' }, style, r.key ? h('small', {}, r.key) : null),
    r.bpm ? h('span', { class: 'cover-bpm' }, r.bpm, h('small', {}, 'BPM')) : h('span', { class: 'cover-bpm none' }, 'BPM ?')));
  const heart = h('button', { type: 'button', class: `heart${isSaved(item.id) ? ' on' : ''}`, 'data-id': item.id, 'aria-label': 'Ajouter aux favoris', 'aria-pressed': String(isSaved(item.id)) }, icon('heart'));
  heart.addEventListener('click', (e) => { e.stopPropagation(); toggleSaved(item); });
  card.append(heart);
  const line = cardLine(item, r);
  const ratio = ratioOf(item);
  const tier = ratio == null ? '' : ratio >= 5 ? ' hi' : ratio >= 2.5 ? ' mid' : ' lo';
  const meta = [item.views ? `${item.views} vues` : null, item.age].filter(Boolean).join(' · ');
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
const player = { item: null, vid: null, frame: null, ready: false, loadedVid: null, state: -1, time: 0, dur: 0, status: 'idle', message: '', timers: [], listen: null };
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
  const vid = ytIdOf(item);
  if (!vid) { toast('Pas de vidéo YouTube pour cette prod'); return; }
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
  if (isPlaying()) { ytSend('pauseVideo'); player.state = 2; renderMini(); return; }
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
  ytSend('stopVideo');
  Object.assign(player, { item: null, vid: null, status: 'idle', time: 0, dur: 0 });
  renderMini();
}

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
    if (typeof i.currentTime === 'number') player.time = i.currentTime;
    if (typeof i.duration === 'number' && i.duration > 0) player.dur = i.duration;
    if (!player.ready) onPlayerReady();
  }
  if (d.event === 'onStateChange' && typeof d.info === 'number') player.state = d.info;
  if (d.event === 'onError') { if (player.item) playerBlocked(YT_ERRORS[d.info] || 'Lecture impossible ici. Ouvre la prod sur YouTube.'); return; }
  if (isPlaying() && player.status !== 'blocked') player.status = 'ready';
  if (player.item) renderMini();
});

let miniHideTimer = null;
function renderMini() {
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
    tg.setAttribute('aria-label', playing ? 'Pause' : 'Lecture');
  }
  $$('.card[data-vid]').forEach((c) => {
    const me = on && c.dataset.vid === player.vid && player.status !== 'blocked';
    c.classList.toggle('playing', me);
    c.classList.toggle('paused', me && !isPlaying());
  });
}

$('#miniToggle').addEventListener('click', togglePlay);
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
function openDrawer(title, nodes) {
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
    r.bpm ? h('span', { class: 'fact mono' }, `${r.bpm} BPM`) : null,
    r.key ? h('span', { class: 'fact mono' }, r.key) : null,
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
      WEB && ytIdOf(item) ? h('button', { type: 'button', class: 'ghost', onclick: () => sendToPc(item) }, icon('down'), 'Sur mon PC') : null,
      item.url ? h('button', { type: 'button', class: 'ghost', onclick: () => copyText(item.url) }, 'Copier le lien') : null),
    WEB ? h('a', { class: 'link d-yt', href: ytWatchUrl(item), target: '_blank', rel: 'noopener' }, 'Ouvrir sur YouTube', icon('ext')) : null,
    ...beatDetails(item, r, findTerms()),
    claude,
  ]);
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
      const b = await ytApi('videos', { part: 'snippet,statistics', id: batch.map((i) => i.id).join(','), maxResults: '50' });
      found = new Map((b.items || []).map((v) => [v.id, v]));
    } catch (e) { if (errorKind(e)) throw e; }
    for (const item of batch) {
      const v = found.get(item.id);
      if (v) {
        item.title = v.snippet?.title || item.title;
        item.description = String(v.snippet?.description || '').slice(0, DESC_MAX);
        applyStats(item, { views: parseCount(v.statistics?.viewCount), likes: parseCount(v.statistics?.likeCount) });
        item.age = ageFrom(v.snippet?.publishedAt);
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
  for (const g of session.plan.genres) variants.push(`${g.label.toLowerCase()} type beat 2026${sfx}`);
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
  const shown = searchPrefs.verifiedOnly ? filtered.filter((r) => r._item.status !== 'unread') : filtered;
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
// (messages gratuits, sans compte) ; le programme melofinds-pc.py, sur le PC,
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
async function signed(obj) {
  const p = JSON.stringify({ mf: 2, ts: Date.now(), n: randHex(16), ...obj });
  const raw = new Uint8Array(pcKey().match(/../g).map((x) => parseInt(x, 16)));
  const key = await crypto.subtle.importKey('raw', raw, { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
  const sig = new Uint8Array(await crypto.subtle.sign('HMAC', key, new TextEncoder().encode(p)));
  return JSON.stringify({ p, s: Array.from(sig, (b) => b.toString(16).padStart(2, '0')).join('') });
}
const pc = { queue: local.get('pcQueue', {}) || {}, info: local.get('pcInfo', null), es: null, onPong: null };
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
    if (m.pc === 'online' || m.pong) {
      pc.info = { at: (d.time || 0) * 1000, dossier: String(m.dossier || '') };
      local.set('pcInfo', pc.info);
      if (m.pong && pc.onPong) pc.onPong(m);
      syncPcUi();
      return;
    }
    const id = String(m.v || '');
    if (!/^[\w-]{11}$/.test(id)) return;
    const cur = pc.queue[id] || { t: id, at: (d.time || 0) * 1000 };
    if (cur.state === 'done' && !m.ok) return;
    const was = cur.state;
    pc.queue[id] = { ...cur, state: m.ok ? 'done' : 'error', file: m.file ? String(m.file) : cur.file, err: m.err ? String(m.err) : null };
    pc.info = { ...(pc.info || {}), at: Math.max(pc.info?.at || 0, (d.time || 0) * 1000) };
    local.set('pcInfo', pc.info);
    savePc();
    syncPcUi();
    if (fresh && was !== pc.queue[id].state) {
      toast(m.ok ? `Sur ton PC : ${displayTitle(cur.t)}` : `Le PC n’a pas pu télécharger : ${String(m.err || '').slice(0, 80)}`);
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
  const msg = { v: id, t: String(item.title || '').slice(0, 200), bpm: r?.bpm || null, key: r?.key || null, force: pc.queue[id]?.state === 'error' || undefined };
  pc.queue[id] = { t: item.title || id, at: Date.now(), state: 'sending' };
  syncPcUi();
  try {
    await ntfyPublish(msg);
    pc.queue[id].state = 'sent';
    toast('Envoyée à ton PC');
  } catch {
    pc.queue[id].state = 'error';
    pc.queue[id].err = 'envoi impossible (connexion ?)';
    toast('Envoi impossible : vérifie ta connexion');
  }
  savePc();
  syncPcUi();
  listenPc();
}

const PC_LABEL = { sending: 'Envoi…', sent: 'Envoyée au PC (en attente)', done: 'Sur ton PC', error: 'Erreur' };
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
  if (dot) dot.hidden = !pc.info;
  if ($('#pcStatus')) renderPcStatus();
}

function pcStatusText() {
  if (!pc.info) return { ok: false, t: 'PC pas encore connecté', s: 'Fais les 3 étapes ci-dessous, puis « Tester ».' };
  const ago = Date.now() - (pc.info.at || 0);
  const when = ago < 90e3 ? 'à l’instant' : ago < 3600e3 ? `il y a ${Math.round(ago / 60e3)} min` : ago < 864e5 ? `il y a ${Math.round(ago / 3600e3)} h` : `il y a ${Math.round(ago / 864e5)} j`;
  return { ok: true, t: 'PC connecté', s: `Dernier signe ${when}${pc.info.dossier ? ` · dossier ${pc.info.dossier}` : ''}` };
}
function renderPcStatus() {
  const st = pcStatusText();
  $('#pcStatus').replaceChildren(h('div', { class: `pc-status${st.ok ? ' ok' : ''}` }, h('span', { class: 'pc-led', 'aria-hidden': 'true' }), h('div', {}, h('b', {}, st.t), h('span', {}, st.s))));
  const list = Object.entries(pc.queue).sort((a, b) => (b[1].at || 0) - (a[1].at || 0)).slice(0, 30);
  const box = $('#pcList');
  if (!box) return;
  box.replaceChildren(...(list.length ? list.map(([id, q]) => h('div', { class: `pc-row ${q.state}` },
    h('span', { class: 'pc-ico' }, icon(q.state === 'done' ? 'check' : q.state === 'error' ? 'x' : 'clock')),
    h('div', { class: 'pc-row-main' }, h('b', {}, displayTitle(q.t || id)), h('span', {}, q.state === 'done' ? (q.file || 'Téléchargée') : q.state === 'error' ? (q.err || 'Erreur') : 'En attente du PC')),
    q.state !== 'done' ? h('button', { type: 'button', class: 'ghost', onclick: () => sendToPc({ id, url: `https://www.youtube.com/watch?v=${id}`, title: q.t }) }, 'Renvoyer') : null))
    : [h('p', { class: 'muted' }, 'Aucune prod envoyée pour l’instant. Touche ', icon('down'), ' sur une prod.')]));
}

function cmdBlock(text) {
  return h('div', { class: 'cmd' }, h('code', {}, text), h('button', { type: 'button', class: 'ghost', onclick: () => copyText(text) }, 'Copier'));
}
function openPcSetup(pending) {
  listenPc();
  const code = pcCode();
  const run = `python "$env:USERPROFILE\\Downloads\\melofinds-pc.py" --code ${code} --cle ${pcKey()} --demarrage`;
  const test = h('button', { type: 'button', class: 'primary' }, 'Tester la connexion');
  test.addEventListener('click', async () => {
    test.disabled = true;
    test.textContent = 'J’attends ton PC… (jusqu’à 30 s)';
    const timer = setTimeout(() => { pc.onPong = null; test.disabled = false; test.textContent = 'Tester la connexion'; toast('Pas de réponse : le programme tourne-t-il sur ton PC ?'); }, 35e3);
    pc.onPong = () => {
      clearTimeout(timer); pc.onPong = null; test.disabled = false; test.textContent = 'Tester la connexion'; toast('PC connecté !');
      if (pending) { const p = pending; pending = null; sendToPc(p); }
    };
    try { await ntfyPublish({ ping: 1 }); } catch { clearTimeout(timer); pc.onPong = null; test.disabled = false; test.textContent = 'Tester la connexion'; toast('Envoi impossible : vérifie ta connexion'); }
  });
  openDrawer('Télécharger sur mon PC', [
    h('p', { class: 'muted', style: 'margin:0' }, 'Touche ', icon('down'), ' sur une prod : elle se télécharge toute seule sur ton PC, rangée par licence, même si tu es loin (5G ou Wi-Fi). Il faut juste que le PC soit allumé.'),
    h('div', { id: 'pcStatus' }),
    h('div', { class: 'd-sec' }, h('h4', {}, '1. Installer les outils (une fois, sur le PC Windows)'),
      h('p', { class: 'hint' }, 'Ouvre « Terminal » (clic droit sur le menu Démarrer) et colle :'),
      cmdBlock('winget install --id Python.Python.3.12 -e; winget install --id DenoLand.Deno -e; winget install --id Gyan.FFmpeg -e'),
      h('p', { class: 'hint' }, 'Ferme le Terminal, rouvre-le, puis :'),
      cmdBlock('python -m pip install -U "yt-dlp[default]"')),
    h('div', { class: 'd-sec' }, h('h4', {}, '2. Télécharger le programme'),
      h('a', { class: 'ghost', href: 'melofinds-pc.py', download: 'melofinds-pc.py' }, icon('down'), 'melofinds-pc.py'),
      h('p', { class: 'hint' }, 'Ouvre ce lien sur ton PC (envoie-toi la page). Le fichier arrive dans « Téléchargements ».')),
    h('div', { class: 'd-sec' }, h('h4', {}, '3. Le lancer avec ton code'),
      cmdBlock(run),
      h('p', { class: 'hint' }, '« --demarrage » le relance tout seul à chaque allumage du PC. Les prods arrivent en .wav uniquement, dans un seul dossier : Musique\\Melofinds (pour en choisir un autre, ajoute --dossier "D:\\Prods"). Nom du fichier : « Titre [Clé, BPM].wav », sans « free ».')),
    h('div', { class: 'actions' }, test),
    h('div', { class: 'd-sec' }, h('h4', {}, 'Envois récents'), h('div', { id: 'pcList', class: 'pc-list' })),
    h('div', { class: 'd-sec' }, h('h4', {}, 'Sécurité'),
      h('ul', { class: 'reasons' },
        h('li', {}, 'Chaque envoi est signé avec ta clé secrète, qui ne quitte jamais ce téléphone et ton PC. Sans elle, le PC ignore l’envoi.'),
        h('li', {}, 'Un envoi contient seulement l’identifiant de la vidéo : jamais de lien, de chemin ou de commande.'),
        h('li', {}, 'Le PC n’écrit que des .wav vérifiés, dans le seul dossier choisi sur le PC (impossible à changer à distance).'),
        h('li', {}, 'Limites : vidéos de 15 min max, 40 téléchargements par heure, envois de plus de 48 h refusés.'))),
    h('p', { class: 'hint' }, 'Ne partage pas la commande de l’étape 3 : elle contient ta clé. ',
      h('button', { type: 'button', class: 'link', onclick: () => { local.set('pcCode', ''); local.set('pcKey', ''); pc.info = null; local.set('pcInfo', null); pc.es?.close(); pc.es = null; openPcSetup(); toast('Nouvelle clé : relance le programme avec la nouvelle commande'); } }, 'Changer de code et de clé')),
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
    const keyBtn = h('button', { type: 'button', class: 'link', id: 'keyBtn', onclick: openKeySettings }, ytKey() ? 'Clé YouTube' : 'Descriptions complètes (clé YouTube, facultatif)');
    $('.results-foot').append(keyBtn);
    if (!ytKey()) pipedInstances();
    const pcBtn = h('button', { type: 'button', class: 'verify-btn pc-head', id: 'pcHead', title: 'Télécharger les prods sur mon PC', onclick: () => openPcSetup() }, icon('down'), h('span', {}, 'Mon PC'), h('em', { class: 'dot', id: 'pcDot', hidden: !pc.info }, '✓'));
    $('#openVerify').before(pcBtn);
    if (pc.info || Object.values(pc.queue).some((q) => q.state === 'sent')) listenPc();
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
