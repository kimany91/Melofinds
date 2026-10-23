(() => {
'use strict';
// Melofinds, version page Claude. Le moteur (buildPlan, analyzeVideo, filterResults…)
// est chargé juste avant ce script ; ici, l'interface et la recherche automatique.

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const h = (tag, attrs = {}, ...kids) => {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? '' : v);
  }
  for (const k of kids.flat()) if (k != null && k !== false) el.append(k instanceof Node ? k : String(k));
  return el;
};

// ---------------------------------------------------------------------------
// Petits réglages du navigateur (onglet, formulaire en cours, filtres)

const local = {
  get(k, fallback) {
    try { const v = localStorage.getItem(`mf.${k}`); return v == null ? fallback : JSON.parse(v); } catch { return fallback; }
  },
  set(k, v) { try { localStorage.setItem(`mf.${k}`, JSON.stringify(v)); } catch { /* indisponible */ } },
};

let toastTimer;
function toast(msg, action) {
  const t = $('#toast');
  $('#toastMsg').textContent = msg;
  const btn = $('#toastAction');
  btn.hidden = !action;
  btn.onclick = null;
  if (action) {
    btn.textContent = action.label;
    btn.onclick = () => { t.classList.remove('show'); action.run(); };
  }
  t.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove('show'), action ? 5000 : 2000);
}

// ---------------------------------------------------------------------------
// Données gardées : historique + ma liste (compte Claude si possible, sinon navigateur)

const state = { history: local.get('history', []), beats: local.get('beats', []) };
const MAX = { history: 80, beats: 80 };
const DESC_MAX = 2500;

const persist = {
  mode: 'local',
  refs: {},
  chain: { history: Promise.resolve(), beats: Promise.resolve() },
  timers: {},
  async init() {
    setSync();
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
            if (Array.isArray(items)) {
              state[key] = JSON.parse(JSON.stringify(items));
              local.set(key, state[key]);
              renderFor(key);
            }
          } else if (first && state[key].length) {
            this.save(key);
          }
          first = false;
        }, () => { this.mode = 'local'; setSync(); });
      }
      this.mode = 'db';
      setSync();
    } catch {
      this.mode = 'local';
      setSync();
    }
  },
  save(key) {
    state[key] = state[key].slice(0, MAX[key]);
    local.set(key, state[key]);
    if (this.mode !== 'db' || !this.refs[key]) return;
    clearTimeout(this.timers[key]);
    this.timers[key] = setTimeout(() => {
      const body = { items: state[key], updatedAt: new Date().toISOString() };
      this.chain[key] = this.chain[key].then(() => this.refs[key].set(body)).catch((e) => {
        if (e?.code === 'quota_exceeded') toast('Ta liste est pleine : retire quelques prods.');
        else if (['invalid_argument', 'revoked', 'not_granted'].includes(e?.code)) { this.mode = 'local'; setSync(); }
      });
    }, 500);
  },
};
function setSync() {
  $('#syncBadge').textContent = persist.mode === 'db' ? '☁️ Sauvé dans ton compte' : '💾 Sauvé dans ce navigateur';
}
function renderFor(key) {
  if (key === 'history') { renderHistory(); syncFavButton(); }
  else { listBoard.render(); searchBoard.render(); updateListCount(); }
}

// ---------------------------------------------------------------------------
// Appareil : l'algo s'adapte (mise en page, nombre de recherches, nombre de vidéos)

function detectDevice() {
  const forced = local.get('device', '');
  if (forced === 'mobile' || forced === 'desktop') return forced;
  const ua = /Mobi|Android|iPhone|iPad|iPod/i.test(navigator.userAgent);
  return ua || window.innerWidth < 760 ? 'mobile' : 'desktop';
}
let device = detectDevice();
function applyDevice() {
  document.body.classList.toggle('mobile', device === 'mobile');
  document.body.classList.toggle('desktop', device === 'desktop');
  const forced = local.get('device', '');
  $('#deviceBadge').textContent = `${device === 'mobile' ? '📱 Mobile' : '💻 PC'}${forced ? ' · forcé' : ''}`;
  $('#depth option[value=""]').textContent = `Auto · ${DEPTHS[defaultDepth(device)].label.toLowerCase()} sur ${device === 'mobile' ? 'mobile' : 'PC'}`;
  updatePlan();
}
$('#deviceBadge').addEventListener('click', () => {
  local.set('device', local.get('device', '') ? '' : device === 'mobile' ? 'desktop' : 'mobile');
  device = detectDevice();
  applyDevice();
  toast(device === 'mobile' ? 'Mode mobile : recherche plus légère' : 'Mode PC : recherche plus complète');
});
let resizeTimer;
window.addEventListener('resize', () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => { const d = detectDevice(); if (d !== device) { device = d; applyDevice(); } }, 200);
});

// ---------------------------------------------------------------------------
// Onglets

const VIEWS = ['search', 'verify', 'list', 'history'];
function showView(name, { scroll = true } = {}) {
  if (!VIEWS.includes(name)) name = 'search';
  $$('.tab').forEach((t) => { const on = t.dataset.view === name; t.classList.toggle('active', on); t.setAttribute('aria-selected', on); });
  $$('.view').forEach((v) => v.classList.toggle('active', v.id === `view-${name}`));
  local.set('view', name);
  if (name === 'list') listBoard.render();
  if (name === 'history') renderHistory();
  if (scroll) window.scrollTo({ top: 0 });
}
$$('.tab').forEach((t) => t.addEventListener('click', () => showView(t.dataset.view)));

// ---------------------------------------------------------------------------
// Utilitaires d'affichage

const GROUP_ICON = { ffp: '✅', upto: '⏳', fnp: '🎧', paid: '💸', unknown: '❓' };
const KEYLINE_ICON = { licence: '📜', credit: '✍️', tempo: '🎚️', contact: '✉️' };
const KW_RE = /(free\s*(?:for|4)\s*profit|non[\s-]*profit|spotify|apple\s*music|streaming|youtube\s*only|lease|licen[cs]e|licence|cr[eé]dit|untagged|up\s*to\s*[\d.,\s]+k?\s*(?:streams?|plays?)|[\d.,]+\s*k?\s*(?:streams?|plays?|écoutes)|❌|✅)/gi;
const stripAccents = (s) => s.normalize('NFD').replace(/[̀-ͯ]/g, '');
const ytSearch = (q) => `https://www.youtube.com/results?search_query=${encodeURIComponent(q)}`;
const YT_RE = /https?:\/\/(?:www\.|m\.|music\.)?(?:youtube\.com\/(?:watch\?(?:[^\s)"'<>\]]*?&)?v=|shorts\/|live\/|embed\/)|youtu\.be\/)([\w-]{11})/g;
function youtubeId(url) {
  const m = String(url || '').match(/(?:youtu\.be\/|[?&]v=|\/shorts\/|\/embed\/|\/live\/)([\w-]{11})/);
  return m ? m[1] : null;
}

function highlight(text, terms = []) {
  const frag = document.createDocumentFragment();
  if (!text) return frag;
  const ranges = [];
  const plain = stripAccents(text).toLowerCase();
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

function verdictText(L) {
  switch (L.category) {
    case 'ffp': return '✅ Spotify sans payer';
    case 'upto': return `⏳ Gratuit jusqu’à ${formatCount(L.limit)} ${L.limitUnit || 'streams'}`;
    case 'fnp': return L.misleading ? '⚠️ Payer pour Spotify' : '🎧 Gratuit hors Spotify';
    case 'paid': return L.reasons[0]?.text.includes('SOLD') ? '⛔ Prod déjà vendue' : '💸 Licence payante';
    default: return '❓ Licence à vérifier';
  }
}

async function copyText(text, what = 'Copié') {
  try { await navigator.clipboard.writeText(text); toast(what); } catch { toast('Copie impossible ici : sélectionne le texte à la main.'); }
}

function analyze(beat, plan = null) {
  return analyzeVideo({ id: beat.id, title: beat.title, description: beat.description, channel: beat.channel, views: beat.views, foundBy: beat.foundBy }, plan);
}

// ---------------------------------------------------------------------------
// Carte d'une prod

function renderCard(beat, r, { terms = [], open = false, big = false, example = false, actions = [] } = {}) {
  const L = r.license;
  const card = h('article', { class: `card cat-${L.category}${L.misleading ? ' misleading' : ''}${big ? ' big-card' : ''}` });
  const style = r.styles?.[0]?.label || 'Type beat';
  card.append(h('div', { class: 'cover' },
    h('span', { class: 'ribbon' }, L.label),
    example ? h('span', { class: 'example-tag' }, 'exemple') : null,
    h('div', { class: 'cover-style' }, style, h('small', {}, r.key ? `🎹 ${r.key}` : (r.styles?.[1]?.label || ' '))),
    r.bpm ? h('div', { class: 'cover-bpm' }, r.bpm, h('small', {}, 'BPM')) : h('div', { class: 'cover-bpm none' }, 'BPM ?')));

  const body = h('div', { class: 'card-body' });
  const dots = { haute: 3, moyenne: 2, faible: 1 }[L.confidence] || 1;
  body.append(h('div', { class: 'verdict' }, verdictText(L),
    h('span', { class: 'conf', title: `Confiance de l’algo : ${L.confidence}` }, L.confidence, h('span', { class: 'conf-dots' }, [1, 2, 3].map((i) => h('i', { class: i <= dots ? 'on' : null }))))));
  body.append(h('h3', { class: 'title', title: beat.title },
    beat.url ? h('a', { href: beat.url, target: '_blank', rel: 'noopener' }, beat.title || '(sans titre)') : (beat.title || '(sans titre)')));
  const meta = [beat.channel, beat.addedAt ? `gardée le ${new Date(beat.addedAt).toLocaleDateString('fr-FR')}` : null].filter(Boolean).join(' · ');
  if (meta) body.append(h('div', { class: 'meta' }, meta));
  if (L.misleading) {
    body.append(h('div', { class: 'alert' }, h('span', { 'aria-hidden': 'true' }, '⚠️'),
      h('span', {}, h('b', {}, 'Titre trompeur. '), 'Le titre dit « free for profit », mais la description demande de payer pour sortir le son sur Spotify.')));
  }
  const badges = h('div', { class: 'badges' });
  if (L.creditRequired) badges.append(h('span', { class: 'badge credit' }, '✍️ Crédit obligatoire'));
  badges.append(h('span', { class: 'badge' }, `Spotify : ${L.spotify}`));
  if (beat.partial) badges.append(h('span', { class: 'badge', title: 'La description complète n’a pas pu être lue : verdict sur le titre et un extrait.' }, 'extrait seulement'));
  for (const s of (r.styles || []).slice(1)) badges.append(h('span', { class: 'badge' }, s.label));
  body.append(badges);

  const lines = r.keyLines || [];
  if (lines.length) {
    body.append(h('ul', { class: 'keyinfo' },
      h('li', { class: 'keyinfo-title' }, '📋 Lu dans la description'),
      lines.slice(0, big ? 8 : 4).map((l) => h('li', { class: l.type }, h('i', { 'aria-hidden': 'true' }, KEYLINE_ICON[l.type] || '•'), h('span', {}, highlight(l.text, terms))))));
  } else {
    body.append(h('div', { class: 'small-note' }, beat.description ? 'Aucune ligne sur les droits dans la description.' : 'Pas de description : l’algo n’a que le titre.'));
  }
  card.append(body);

  const details = h('div', { class: 'details', hidden: !open });
  const fill = () => {
    if (details.childNodes.length) return;
    details.append(h('ul', { class: 'reasons' }, L.reasons.map((x) => h('li', {}, x.text, x.quote ? h('q', {}, highlight(x.quote, terms)) : null))));
    if (beat.foundBy?.length) details.append(h('div', { class: 'small-note' }, `Trouvée via : ${beat.foundBy.map((q) => `« ${q} »`).join(', ')}`));
    const pre = h('pre', {});
    pre.append(highlight(beat.description || '(description vide)', terms));
    details.append(h('details', { class: 'desc', open: terms.length ? true : null }, h('summary', {}, 'Description complète'), pre));
  };
  if (open) fill();
  const whyBtn = h('button', { type: 'button', class: `act${open ? ' on' : ''}`, title: 'Pourquoi cette catégorie ?' }, 'ℹ️', h('span', {}, 'Pourquoi'));
  whyBtn.addEventListener('click', () => { fill(); details.hidden = !details.hidden; whyBtn.classList.toggle('on', !details.hidden); });
  card.append(h('div', { class: 'actions' },
    beat.url ? h('a', { class: 'act yt-act', href: beat.url, target: '_blank', rel: 'noopener', title: 'Écouter sur YouTube' }, '▶', h('span', {}, 'YouTube')) : null,
    whyBtn,
    ...actions.map((a) => a()),
    beat.url ? h('button', { type: 'button', class: 'act', title: 'Copier le lien', onclick: () => copyText(beat.url, 'Lien copié') }, '🔗', h('span', {}, 'Lien')) : null));
  card.append(details);
  return card;
}

// ---------------------------------------------------------------------------
// Tableau de prods (utilisé pour les résultats de recherche ET pour « Ma liste ») :
// compteurs par licence cliquables, recherche dans les descriptions, tri, style, BPM.

const QUICK_TERMS = ['spotify', 'crédit', 'untagged', 'wav', 'contact', '-lease'];

function createBoard(root, prefix, cfg) {
  const prefs = local.get(`${prefix}Prefs`, { off: cfg.defaultOff || [], onlyMisleading: false });
  const savePrefs = () => local.set(`${prefix}Prefs`, prefs);
  const id = (n) => `${prefix}-${n}`;
  const head = h('div', { class: 'board-head' });
  const stats = h('div', { class: 'stats' });
  const search = h('input', { id: id('desc'), type: 'search', placeholder: 'Chercher dans les descriptions… (spotify, wav, -lease)', 'aria-label': 'Chercher dans les descriptions' });
  const quick = h('div', { class: 'quick' });
  const sort = h('select', { id: id('sort') },
    h('option', { value: 'pertinence' }, 'Pertinence'), h('option', { value: 'bpm-asc' }, 'BPM ↑'), h('option', { value: 'bpm-desc' }, 'BPM ↓'),
    h('option', { value: 'limite' }, 'Limite de streams'), h('option', { value: 'recent' }, cfg.recentLabel || 'Récentes'));
  const styleSel = h('select', { id: id('style') }, h('option', { value: '' }, 'Tous'));
  const bpmOn = h('input', { type: 'checkbox', id: id('bpm') });
  const bpmMin = h('input', { type: 'number', id: id('bpmMin'), min: 50, max: 220, inputmode: 'numeric', placeholder: 'min', 'aria-label': 'BPM minimum' });
  const bpmMax = h('input', { type: 'number', id: id('bpmMax'), min: 50, max: 220, inputmode: 'numeric', placeholder: 'max', 'aria-label': 'BPM maximum' });
  const bpmReq = h('input', { type: 'checkbox', id: id('bpmReq') });
  const noCredit = h('input', { type: 'checkbox', id: id('noCredit') });
  const bpmBox = h('div', { class: 'bpm-range', hidden: true }, bpmMin, h('span', { class: 'dash' }, '→'), bpmMax,
    h('label', { class: 'row check', for: id('bpmReq') }, bpmReq, h('span', {}, 'Cacher sans BPM')));
  const count = h('p', { class: 'count' });
  const results = h('div', {});
  const controls = h('div', {},
    stats,
    h('div', { class: 'toolbar' },
      h('div', { class: 'search-desc' }, h('span', { class: 'ico', 'aria-hidden': 'true' }, '🔎'), search),
      quick,
      h('div', { class: 'tools' },
        h('label', { for: id('sort') }, h('span', {}, 'Tri'), sort),
        h('label', { for: id('style') }, h('span', {}, 'Style'), styleSel))),
    h('div', { class: 'bpm-bar' },
      h('label', { class: 'switch-row', for: id('bpm') }, h('span', { class: 'switch' }, bpmOn, h('span', { class: 'slider' })), h('span', {}, 'Trier / filtrer par BPM')),
      bpmBox,
      h('label', { class: 'row check', for: id('noCredit') }, noCredit, h('span', {}, 'Cacher si crédit obligatoire'))),
    count);
  root.append(head, controls, results);

  for (const term of QUICK_TERMS) {
    quick.append(h('button', {
      type: 'button', class: 'chip', 'data-term': term,
      title: term.startsWith('-') ? `Cacher les prods dont la description contient « ${term.slice(1)} »` : `Prods dont la description contient « ${term} »`,
      onclick: () => {
        const words = search.value.split(/\s+/).filter(Boolean);
        const i = words.indexOf(term);
        if (i >= 0) words.splice(i, 1); else words.push(term);
        search.value = words.join(' ');
        render();
      },
    }, term.startsWith('-') ? `sans ${term.slice(1)}` : term));
  }
  let t;
  search.addEventListener('input', () => { clearTimeout(t); t = setTimeout(render, 120); });
  [sort, styleSel, bpmReq, noCredit].forEach((el) => el.addEventListener('change', render));
  [bpmMin, bpmMax].forEach((el) => el.addEventListener('input', render));
  bpmOn.addEventListener('change', () => {
    bpmBox.hidden = !bpmOn.checked;
    if (bpmOn.checked) {
      if (!bpmMin.value && !bpmMax.value && cfg.bpmRange?.()) { bpmMin.value = cfg.bpmRange().min; bpmMax.value = cfg.bpmRange().max; }
      if (sort.value === 'pertinence') sort.value = 'bpm-asc';
    } else if (sort.value.startsWith('bpm')) sort.value = 'pertinence';
    render();
  });

  function setOff(list) { prefs.off = [...list]; prefs.onlyMisleading = false; savePrefs(); }

  function render() {
    const src = cfg.source();
    root.hidden = !src.items.length && !src.showEmpty;
    head.replaceChildren(...(cfg.head ? cfg.head(src) : []));
    controls.hidden = !src.items.length;
    const plan = src.plan || null;
    const rows = src.items.map((beat, i) => {
      const r = analyze(beat, plan);
      if (src.manual) r.isBeat = true;
      return { ...r, _beat: beat, addedOrder: i };
    }).filter((r) => r.isBeat);

    const off = new Set(prefs.off);
    const counts = Object.fromEntries(CATEGORY_ORDER.map((c) => [c, 0]));
    rows.forEach((r) => counts[r.license.category]++);
    const misleading = rows.filter((r) => r.license.misleading).length;
    const tiles = CATEGORY_ORDER.map((c) => h('button', {
      type: 'button', class: `stat cat-${c}${off.has(c) || prefs.onlyMisleading ? ' off' : ''}`,
      'aria-pressed': String(!off.has(c)), title: off.has(c) ? 'Afficher' : 'Masquer',
      onclick: () => { if (off.has(c)) off.delete(c); else off.add(c); setOff(off); render(); },
    }, h('b', {}, counts[c]), h('span', {}, `${GROUP_ICON[c]} ${CATEGORIES[c].label}`)));
    if (misleading) {
      tiles.push(h('button', {
        type: 'button', class: `stat cat-warn${prefs.onlyMisleading ? '' : ' off'}`,
        title: 'Titre « free for profit » mais la description demande de payer pour Spotify',
        onclick: () => { prefs.onlyMisleading = !prefs.onlyMisleading; savePrefs(); render(); },
      }, h('b', {}, misleading), h('span', {}, '⚠️ Titres trompeurs')));
    }
    stats.replaceChildren(...tiles);

    const prev = styleSel.value;
    const styles = stylesIn(rows);
    styleSel.replaceChildren(h('option', { value: '' }, 'Tous'), ...styles.map((s) => h('option', { value: s.id }, `${s.label} (${s.count})`)));
    styleSel.value = styles.some((s) => s.id === prev) ? prev : '';

    const text = search.value.trim();
    const f = {
      licenses: prefs.onlyMisleading ? CATEGORY_ORDER : CATEGORY_ORDER.filter((c) => !off.has(c)),
      noCredit: noCredit.checked,
      style: styleSel.value,
      text,
      bpm: { enabled: bpmOn.checked, min: Number(bpmMin.value) || null, max: Number(bpmMax.value) || null, requireBpm: bpmReq.checked },
    };
    let filtered = filterResults(rows, f);
    if (prefs.onlyMisleading) filtered = filtered.filter((r) => r.license.misleading);
    const sorted = sort.value === 'recent' ? [...filtered].sort((a, b) => a.addedOrder - b.addedOrder) : sortResults(filtered, sort.value);
    const groups = groupByCategory(sorted);
    const terms = text ? parseTextQuery(text).include : [];
    const quickOn = new Set(text.split(/\s+/));
    $$('.chip', quick).forEach((c) => c.classList.toggle('on', quickOn.has(c.dataset.term)));
    const hiddenN = rows.length - filtered.length;
    count.textContent = rows.length ? `${filtered.length} prod(s) affichée(s)${hiddenN ? ` · ${hiddenN} masquée(s) par tes filtres (clique sur une catégorie pour l’afficher)` : ''}` : '';

    if (!rows.length) { results.replaceChildren(...(src.empty ? [src.empty()] : [])); return; }
    if (!groups.length) {
      results.replaceChildren(h('div', { class: 'nores' }, h('div', { style: 'font-size:34px' }, '🫥'), h('h3', {}, 'Aucune prod avec ces filtres'),
        h('p', {}, text ? `Aucune description ne contient « ${text} ». ` : '', 'Clique sur une catégorie en haut pour l’afficher, ou élargis la plage BPM.')));
      return;
    }
    results.replaceChildren(...groups.map((g) => h('section', { class: `group cat-${g.category}` },
      h('div', { class: 'group-head' },
        h('span', { class: 'gico', 'aria-hidden': 'true' }, GROUP_ICON[g.category]),
        h('div', {}, h('h2', {}, CATEGORIES[g.category].label, h('small', {}, g.items.length)), h('p', {}, CATEGORIES[g.category].help))),
      h('div', { class: 'grid' }, g.items.map((r) => renderCard(r._beat, r, { terms, example: src.example, actions: cfg.actions ? cfg.actions(r._beat, src) : [] }))))));
  }
  return { render, setOff };
}

// ---------------------------------------------------------------------------
// RECHERCHE : formulaire + plan

const SUGGESTIONS = [
  ['Vibe', ['rapide', 'énergique', 'musicale', 'sombre', 'triste', 'agressif', 'chill', 'planant', 'bouncy', 'joyeux']],
  ['Style', ['drill', 'rage', 'jerk', 'pluggnb', 'boom bap', 'detroit', 'phonk']],
  ['Instru', ['piano', 'guitare', 'synthé', 'cloches', 'violon']],
  ['Artiste', ['Lil Uzi', 'Pop Smoke', 'Travis Scott', 'Ken Carson', 'Gunna']],
];
const LICENSES = [
  ['ffp', '✅', 'Free for profit', 'Spotify sans payer'],
  ['upto', '⏳', 'Up to', 'Gratuit jusqu’à X streams'],
  ['fnp', '🎧', 'Free', 'Non-profit, payer pour Spotify'],
  ['paid', '💸', 'Payant', 'Lease / exclu'],
];
const promptEl = $('#prompt');

for (const [label, words] of SUGGESTIONS) {
  $('#suggestions').append(h('div', { class: 'sugg-row' }, h('b', {}, label), words.map((w) => h('button', {
    type: 'button', class: 'chip', 'data-word': w, onclick: () => toggleWord(w),
  }, w))));
}
for (const [lid, ico, label, sub] of LICENSES) {
  $('#licenseGrid').append(h('label', { class: `lic cat-${lid}`, for: `lic-${lid}` },
    h('input', { type: 'checkbox', name: 'lic', value: lid, id: `lic-${lid}` }),
    h('span', { class: 'lic-ico', 'aria-hidden': 'true' }, ico),
    h('span', {}, h('b', {}, label), h('small', {}, sub))));
}

function toggleWord(w) {
  const parts = promptEl.value.split(',').map((p) => p.trim()).filter(Boolean);
  const i = parts.findIndex((p) => p.toLowerCase() === w.toLowerCase());
  if (i >= 0) parts.splice(i, 1); else parts.push(w);
  promptEl.value = parts.join(', ');
  updatePlan();
}
function syncChips() {
  const txt = ` ${stripAccents(promptEl.value.toLowerCase())} `;
  $$('#suggestions .chip').forEach((c) => {
    const w = stripAccents(c.dataset.word.toLowerCase()).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    c.classList.toggle('on', new RegExp(`[^a-z]${w}[^a-z]`).test(txt));
  });
}

function readForm() {
  return {
    prompt: promptEl.value.trim(),
    manualQuery: $('#manualQuery').value.trim(),
    licenses: $$('input[name=lic]:checked').map((i) => i.value),
    depth: $('#depth').value,
  };
}
function writeForm(f) {
  promptEl.value = f.prompt || '';
  $('#manualQuery').value = f.manualQuery || '';
  const lic = new Set(f.licenses || []);
  $$('input[name=lic]').forEach((i) => { i.checked = lic.has(i.value); });
  $('#depth').value = f.depth || '';
  updatePlan();
}

let currentPlan = null;
function updatePlan() {
  const f = readForm();
  currentPlan = buildPlan(f.prompt, { licenses: f.licenses, device, depth: f.depth || undefined, manualQuery: f.manualQuery });
  renderPlan(currentPlan, f);
  syncChips();
  syncFavButton();
  local.set('form', f);
}

function renderPlan(plan, f) {
  const hasInput = !!(f.prompt || f.manualQuery);
  if (!lastSearch) $('#planTitle').textContent = hasInput ? (f.prompt || f.manualQuery) : 'Décris ta prod à gauche';
  $('#planSummary').textContent = `· ${plan.genres.map((g) => g.label).join(', ')} · ${plan.bpmRange.min}–${plan.bpmRange.max} BPM`;
  $('#planNotes').replaceChildren(...(hasInput ? plan.notes : []).map((n) => h('div', { class: 'note' }, '⚠️ ', n)));
  $('#pMoods').replaceChildren(...(plan.moods.length
    ? plan.moods.map((m) => h('span', { class: 'tag', title: `mots reconnus : ${m.matched.join(', ')}` }, m.label))
    : [h('span', { class: 'tag plain' }, 'aucune reconnue')]));
  $('#pInstr').textContent = plan.instruments.length ? `Instruments : ${plan.instruments.join(', ')}` : '';
  $('#pGenres').replaceChildren(...plan.genres.map((g) => h('span', { class: 'tag genre', title: g.why.join(', ') }, g.label)));
  $('#pArtists').replaceChildren(...plan.artists.map((a) => h('span', { class: 'tag artist', title: a.reason }, a.name)));
  $('#pBpm').replaceChildren(`${plan.bpmRange.min}–${plan.bpmRange.max}`, h('small', {}, 'BPM'));
  $('#pBpmWhy').textContent = plan.bpmRange.source;
  $('#qTitle').textContent = `${plan.queries.length} recherches · profondeur ${plan.depth.label.toLowerCase()}${plan.device === 'mobile' ? ' (mobile)' : ''}`;
  $('#queries').replaceChildren(...plan.queries.map((q) => h('li', { class: 'q' },
    h('div', { class: 'q-main' }, h('div', { class: 'q-text' }, q.q), h('div', { class: 'q-why' }, q.why)),
    h('div', { class: 'q-actions' },
      h('a', { class: 'mini', href: ytSearch(q.q), target: '_blank', rel: 'noopener', title: 'Voir cette recherche sur YouTube' }, 'YouTube ↗')))));
}

let planTimer;
const debouncedPlan = () => { clearTimeout(planTimer); planTimer = setTimeout(updatePlan, 150); };
promptEl.addEventListener('input', debouncedPlan);
$('#manualQuery').addEventListener('input', debouncedPlan);
$('#depth').addEventListener('change', updatePlan);
$('#licenseGrid').addEventListener('change', updatePlan);
$('#clearPrompt').addEventListener('click', () => { promptEl.value = ''; updatePlan(); promptEl.focus(); });
$('#formToggle').addEventListener('click', () => $('#searchForm').classList.remove('collapsed'));

$('#searchForm').addEventListener('submit', (e) => {
  e.preventDefault();
  const f = readForm();
  if (!f.prompt && !f.manualQuery) { toast('Écris d’abord une description, ex. « rapide, énergique et musicale »'); promptEl.focus(); return; }
  updatePlan();
  runSearch(f, currentPlan);
});
document.addEventListener('keydown', (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key === 'Enter' && $('#view-search').classList.contains('active')) {
    e.preventDefault();
    $('#searchForm').requestSubmit();
  }
});

// ---------------------------------------------------------------------------
// RECHERCHE AUTOMATIQUE via le connecteur « Parallel Search »
// (recherche web → liens YouTube → lecture de chaque page vidéo → description)

const SERVER = 'Parallel Search';
const MAX_VIDEOS = { rapide: 12, normal: 20, approfondie: 32 };
let mcpPromise = null;
const getMcp = () => (mcpPromise ||= (window.claude?.use ? window.claude.use('mcp').catch(() => null) : Promise.resolve(null)));
const schemas = {};

async function describe(tool) {
  if (schemas[tool]) return schemas[tool];
  const mcp = await getMcp();
  try {
    const d = await mcp.describeTool(SERVER, tool);
    if (d?.inputSchema) schemas[tool] = d.inputSchema;
  } catch { /* pas encore autorisé ou pas de schéma */ }
  return schemas[tool] || null;
}

const propsOf = (schema) => schema?.properties || {};
function searchInputs(schema, objective, queries) {
  const p = propsOf(schema);
  const keys = Object.keys(p);
  if (!keys.length) {
    const out = [];
    for (let i = 0; i < queries.length; i += 5) out.push({ objective, search_queries: queries.slice(i, i + 5) });
    return out;
  }
  const arrKey = keys.find((k) => /quer/i.test(k) && (p[k]?.type === 'array' || p[k]?.items));
  const strKey = keys.find((k) => /^(query|q|search_query|search|keywords?)$/i.test(k));
  const base = {};
  for (const k of keys) {
    if (/objective|goal|task|instruction|purpose/i.test(k)) base[k] = objective;
    else if (/max_?results|num_?results|limit|count/i.test(k) && /integer|number/.test(p[k]?.type)) base[k] = Math.min(p[k]?.maximum ?? 20, 20);
  }
  if (arrKey) {
    const size = Math.max(1, Math.min(p[arrKey]?.maxItems || 5, 5));
    const out = [];
    for (let i = 0; i < queries.length; i += size) out.push({ ...base, [arrKey]: queries.slice(i, i + size) });
    return out;
  }
  if (strKey) return queries.map((q) => ({ ...base, [strKey]: q }));
  return [{ ...base }];
}
function fetchInputs(schema, urls, objective) {
  const p = propsOf(schema);
  const keys = Object.keys(p);
  if (!keys.length) {
    const out = [];
    for (let i = 0; i < urls.length; i += 10) out.push({ urls: urls.slice(i, i + 10), objective });
    return out;
  }
  const arrKey = keys.find((k) => /urls/i.test(k));
  const strKey = keys.find((k) => /^url$/i.test(k));
  const base = {};
  for (const k of keys) {
    if (/objective|goal|task|instruction|purpose/i.test(k)) base[k] = objective;
    else if (/full_?content|include_?content/i.test(k) && p[k]?.type === 'boolean') base[k] = true;
  }
  if (arrKey) {
    const size = Math.max(1, Math.min(p[arrKey]?.maxItems || 10, 10));
    const out = [];
    for (let i = 0; i < urls.length; i += size) out.push({ ...base, [arrKey]: urls.slice(i, i + size) });
    return out;
  }
  if (strKey) return urls.map((u) => ({ ...base, [strKey]: u }));
  return [];
}

// Lit n'importe quelle forme de réponse et en sort {id → {title, text}}
const TEXT_KEYS = ['excerpts', 'excerpt', 'snippet', 'snippets', 'content', 'full_content', 'fullContent', 'text', 'markdown', 'description', 'body', 'summary'];
function textOf(o) {
  const parts = [];
  for (const k of TEXT_KEYS) {
    const v = o?.[k];
    if (typeof v === 'string') parts.push(v);
    else if (Array.isArray(v)) parts.push(v.filter((x) => typeof x === 'string').join('\n'));
  }
  return parts.join('\n').trim();
}
function harvest(payload, out = new Map()) {
  const add = (id, title, text) => {
    if (!id) return;
    const cur = out.get(id) || { title: '', text: '' };
    if (title && !cur.title) cur.title = String(title).replace(/\s*[-–|]\s*YouTube\s*$/i, '').trim();
    if (text && text.length > cur.text.length) cur.text = text;
    out.set(id, cur);
  };
  const walk = (node, depth = 0) => {
    if (depth > 12 || node == null) return;
    if (typeof node === 'string') {
      // texte libre / markdown : on récupère les liens YouTube et le texte autour
      YT_RE.lastIndex = 0;
      let m;
      const hits = [];
      while ((m = YT_RE.exec(node))) hits.push({ id: m[1], at: m.index });
      hits.forEach((hit, i) => {
        const end = hits[i + 1]?.at ?? Math.min(node.length, hit.at + 4000);
        const chunk = node.slice(hit.at, end);
        const before = node.slice(Math.max(0, hit.at - 200), hit.at);
        const md = before.match(/\[([^\]]{3,200})\]\([^)]*$/) || before.match(/(?:^|\n)#+\s*(.+)\s*$/) || before.match(/(?:title|titre)\s*[:=]\s*"?([^"\n]{3,200})"?\s*$/i);
        add(hit.id, md?.[1] || '', chunk);
      });
      return;
    }
    if (Array.isArray(node)) { node.forEach((n) => walk(n, depth + 1)); return; }
    if (typeof node === 'object') {
      const url = node.url || node.link || node.href || node.source || node.uri;
      const id = typeof url === 'string' ? youtubeId(url) : null;
      if (id) add(id, node.title || node.name || node.heading, textOf(node));
      for (const [k, v] of Object.entries(node)) {
        if (id && TEXT_KEYS.includes(k)) continue;
        walk(v, depth + 1);
      }
    }
  };
  walk(payload);
  return out;
}
function payloadOf(res) {
  if (!res) return null;
  if (res.payload != null) return res.payload;
  return (res.content || []).filter((b) => b.type === 'text').map((b) => b.text).join('\n');
}
// Garde la description, coupe les commentaires / vidéos suggérées de la page
function cleanDescription(text, title) {
  let t = String(text || '');
  if (title) {
    const i = t.indexOf(title);
    if (i >= 0 && i < t.length / 2) t = t.slice(i + title.length);
  }
  const stop = t.search(/\n\s*(?:#{1,4}\s*)?(?:\d[\d,.\s]*\s*)?(comments?|commentaires|up next|related videos|vidéos suggérées|transcript|show less|afficher moins)\b/i);
  if (stop > 80) t = t.slice(0, stop);
  // lignes de la page YouTube (vues, date) qui ne viennent pas du producteur
  t = t.replace(/^.*\b[\d.,]+\s*[kKmM]?\s*(?:views|vues)\b.*$/gm, '').replace(/^.*\b(?:subscribers|abonnés)\b.*$/gm, '');
  return t.trim().slice(0, DESC_MAX);
}

async function callWithSchema(tool, buildInputs) {
  const mcp = await getMcp();
  let schema = await describe(tool);
  const cacheOpt = { cache: { staleTime: 6 * 3600e3, gcTime: 24 * 3600e3 } };
  const runAll = async (inputs) => {
    const out = [];
    for (const input of inputs) out.push(await mcp.callTool(SERVER, tool, input, cacheOpt));
    return out;
  };
  try {
    return await runAll(buildInputs(schema));
  } catch (e) {
    if (!schema && (e?.code === 'tool_error' || e?.code === 'bad_request')) {
      schema = await describe(tool); // l'accès vient d'être donné : on lit le vrai schéma
      if (schema) return runAll(buildInputs(schema));
    }
    throw e;
  }
}

let lastSearch = local.get('lastSearch', null);
let searching = false;

function setStatus(content, { error = false, progress = null } = {}) {
  const box = $('#searchStatus');
  if (!content) { box.hidden = true; return; }
  box.hidden = false;
  box.className = `search-status${error ? ' error' : ''}`;
  box.replaceChildren(h('div', {}, content), progress != null ? h('div', { class: 'bar' }, h('i', { style: `width:${Math.round(progress * 100)}%` })) : null);
}

function showSetup(kind) {
  const card = $('#setupCard');
  if (!kind) { card.hidden = true; return; }
  card.hidden = false;
  const retry = h('button', { type: 'button', class: 'primary small', onclick: () => $('#searchForm').requestSubmit() }, '↻ Relancer la recherche');
  if (kind === 'connect') {
    card.replaceChildren(
      h('h3', {}, 'Une étape avant que je trouve les vidéos pour toi'),
      h('p', {}, 'Pour chercher sur YouTube et lire les descriptions, la page utilise « Parallel Search », un connecteur de recherche web gratuit, sans compte ni clé. À faire une seule fois :'),
      h('ol', {},
        h('li', {}, 'Ouvre claude.ai → ', h('b', {}, 'Paramètres → Connecteurs'), '.'),
        h('li', {}, 'Clique sur ', h('b', {}, 'Parcourir les connecteurs'), ', cherche ', h('b', {}, 'Parallel Search'), ' et clique sur ', h('b', {}, 'Connecter'), '.'),
        h('li', {}, 'Reviens ici et relance : la page te demandera une fois l’autorisation de l’utiliser.')),
      h('div', { class: 'row-actions' }, retry, h('a', { class: 'mini', href: 'https://claude.ai/settings/connectors', target: '_blank', rel: 'noopener' }, 'Ouvrir les connecteurs ↗')));
  } else if (kind === 'denied') {
    card.replaceChildren(
      h('h3', {}, 'L’accès à Parallel Search a été refusé pour cette page'),
      h('p', {}, 'Sans lui, la page ne peut pas chercher sur YouTube. Autorise-le dans le menu Permissions de cette page, puis relance.'),
      h('div', { class: 'row-actions' }, retry,
        h('button', { type: 'button', class: 'mini', onclick: async () => { try { const p = await window.claude?.use?.('permissions'); await p?.manage?.(); } catch { toast('Ouvre le menu Permissions de la page (en haut).'); } } }, '🔐 Permissions')));
  } else if (kind === 'reauth') {
    card.replaceChildren(h('h3', {}, 'Reconnecte Parallel Search'), h('p', {}, 'Dans claude.ai → Paramètres → Connecteurs, reconnecte « Parallel Search », puis relance.'), h('div', { class: 'row-actions' }, retry));
  } else if (kind === 'unavailable') {
    card.replaceChildren(h('h3', {}, 'Recherche automatique indisponible ici'),
      h('p', {}, 'Cette vue de la page ne peut pas utiliser les connecteurs. Ouvre la page sur claude.ai, ou utilise les liens « YouTube ↗ » de chaque recherche plus bas puis l’onglet Vérifier.'));
  }
}

function errorKind(e) {
  switch (e?.code) {
    case 'server_not_connected': case 'server_not_found': case 'selection_required': return 'connect';
    case 'not_in_manifest': case 'approval_required': case 'consent_required': case 'blocked_by_policy': return 'denied';
    case 'needs_reauth': return 'reauth';
    case 'not_granted': case 'capability_disabled': case 'capability_removed': return 'unavailable';
    default: return null;
  }
}

async function runSearch(f, plan) {
  if (searching) return;
  saveHistory(f, plan);
  const mcp = await getMcp();
  if (!mcp) { showSetup('unavailable'); return; }
  searching = true;
  $('#goBtn').disabled = true;
  $('#goBtn').textContent = 'Recherche en cours…';
  showSetup(null);
  $('#searchIntro').hidden = true;
  if (device === 'mobile') {
    $('#searchForm').classList.add('collapsed');
    $('#formToggleText').textContent = f.prompt || f.manualQuery;
  }
  $('#planCol').scrollIntoView({ behavior: 'smooth', block: 'start' });
  const depthId = plan.depth.id;
  const maxVideos = MAX_VIDEOS[depthId] || 20;
  const queries = plan.queries.map((q) => q.q);
  const objective = `Trouver des vidéos YouTube de prods rap (type beats) correspondant à : ${f.prompt || f.manualQuery}. Ne garder que des liens youtube.com/watch vers des instrumentales « type beat », idéalement free for profit.`;
  try {
    // 1) Recherche web → liens YouTube
    setStatus(h('span', {}, h('span', { class: 'spinner' }), `Recherche des vidéos sur YouTube (${queries.length} recherches)…`), { progress: 0.1 });
    const found = new Map();
    const searchRes = await callWithSchema('web_search', (schema) => searchInputs(schema, objective, queries.map((q) => `${q} youtube`)));
    searchRes.forEach((res) => {
      for (const [vid, info] of harvest(payloadOf(res))) {
        const cur = found.get(vid);
        if (!cur) found.set(vid, { ...info, foundBy: [] });
        else if (!cur.title && info.title) cur.title = info.title;
      }
    });
    // relie chaque vidéo aux recherches qui contiennent un mot de son titre (pour « Trouvée via »)
    for (const v of found.values()) {
      const t = stripAccents((v.title || '').toLowerCase());
      v.foundBy = queries.filter((q) => q.toLowerCase().split(/\s+/).filter((w) => w.length > 3 && !['type', 'beat', 'free', 'profit'].includes(w)).some((w) => t.includes(stripAccents(w))));
    }
    if (!found.size) {
      setStatus(h('span', {}, '😕 Aucune vidéo YouTube trouvée pour ces recherches. Essaie d’autres mots (un artiste, un courant) ou la profondeur « approfondie ».'), { error: true });
      return;
    }
    const ids = [...found.keys()].slice(0, maxVideos);

    // 2) Lecture de chaque page vidéo → description complète
    const urls = ids.map((vid) => `https://www.youtube.com/watch?v=${vid}`);
    let fetched = new Map();
    setStatus(h('span', {}, h('span', { class: 'spinner' }), `${found.size} vidéos trouvées. Lecture des descriptions (${ids.length})…`), { progress: 0.45 });
    try {
      const fetchRes = await callWithSchema('web_fetch', (schema) => fetchInputs(schema, urls,
        'Donner le titre exact de la vidéo et le texte COMPLET de sa description tel qu’écrit par le producteur (licence, free for profit, limites de streams, Spotify, crédit, BPM, tonalité, contact).'));
      fetchRes.forEach((res) => { for (const [vid, info] of harvest(payloadOf(res))) fetched.set(vid, info); });
    } catch (e) {
      if (errorKind(e)) throw e;
      fetched = new Map();
    }

    const items = ids.map((vid) => {
      const s = found.get(vid);
      const d = fetched.get(vid);
      const title = (d?.title || s.title || '').trim();
      const description = cleanDescription(d?.text || s.text || '', title);
      return {
        id: vid,
        url: `https://www.youtube.com/watch?v=${vid}`,
        title: title || `Vidéo YouTube ${vid}`,
        description,
        foundBy: s.foundBy,
        partial: !d?.text,
      };
    });
    lastSearch = { at: new Date().toISOString(), title: f.prompt || f.manualQuery, form: f, items };
    local.set('lastSearch', lastSearch);
    searchBoard.setOff(CATEGORY_ORDER.filter((c) => !(f.licenses.length ? f.licenses : CATEGORY_ORDER).includes(c)));
    const partial = items.filter((i) => i.partial).length;
    setStatus(h('span', {}, `✔ ${items.length} prods analysées${partial ? ` (${partial} avec un extrait seulement)` : ''}. Les catégories que tu n’as pas cochées sont masquées : clique dessus pour les voir.`), { progress: 1 });
    $('#planBox').open = false;
    renderSearchHead();
    searchBoard.render();
    updateHistoryCount(f, items);
  } catch (e) {
    const kind = errorKind(e);
    if (kind) { setStatus(null); showSetup(kind); }
    else {
      const msg = e?.code === 'server_unavailable' ? 'Parallel Search ne répond pas pour le moment.' : e?.code === 'tool_error' ? `Parallel Search a renvoyé une erreur : ${String(e.message || '').slice(0, 200)}` : `La recherche a échoué (${e?.code || 'erreur'}).`;
      setStatus(h('div', {}, '😕 ', msg, h('div', { class: 'row-actions' },
        h('button', { type: 'button', class: 'mini', onclick: () => $('#searchForm').requestSubmit() }, '↻ Réessayer'))), { error: true });
    }
  } finally {
    searching = false;
    $('#goBtn').disabled = false;
    $('#goBtn').textContent = 'Lancer la recherche';
  }
}

function renderSearchHead() {
  if (!lastSearch) return;
  $('#planTitle').textContent = lastSearch.title;
  $('#searchIntro').hidden = true;
}

function isKept(id) { return state.beats.some((b) => b.id === id); }
function keepBeat(beat) {
  if (isKept(beat.id)) return;
  state.beats = [{ id: beat.id, url: beat.url, title: beat.title, description: beat.description, channel: beat.channel, addedAt: new Date().toISOString() }, ...state.beats];
  persist.save('beats');
  updateListCount();
}

const searchBoard = createBoard($('#searchBoard'), 'search', {
  defaultOff: ['fnp', 'paid', 'unknown'],
  recentLabel: 'Ordre trouvé',
  bpmRange: () => currentPlan?.bpmRange,
  source: () => (lastSearch ? { items: lastSearch.items, plan: currentPlan, showEmpty: true } : { items: [] }),
  head: (src) => [h('h3', {}, `${src.items.length} prods trouvées`), h('span', { class: 'small-note' }, lastSearch ? `le ${new Date(lastSearch.at).toLocaleString('fr-FR', { dateStyle: 'short', timeStyle: 'short' })} · chaque description lue et vérifiée` : '')],
  actions: (beat) => [() => {
    const btn = h('button', { type: 'button', class: `act${isKept(beat.id) ? ' saved' : ''}`, title: 'Garder dans ma liste' }, isKept(beat.id) ? '✓' : '➕', h('span', {}, isKept(beat.id) ? 'Gardée' : 'Garder'));
    btn.addEventListener('click', () => {
      if (isKept(beat.id)) { showView('list'); return; }
      keepBeat(beat);
      btn.classList.add('saved');
      btn.replaceChildren('✓', h('span', {}, 'Gardée'));
      toast('Gardée dans ma liste', { label: 'Voir', run: () => showView('list') });
    });
    return btn;
  }],
});

// ---------------------------------------------------------------------------
// Historique & favoris

function formKey(f) { return JSON.stringify([f.prompt, f.manualQuery, [...(f.licenses || [])].sort(), f.depth || '']); }

function saveHistory(f, plan) {
  const key = formKey(f);
  const old = state.history.find((e) => formKey(e.form) === key);
  const entry = {
    id: old?.id || `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`,
    date: new Date().toISOString(),
    form: f,
    device,
    queries: plan.queries.map((q) => q.q),
    genres: plan.genres.map((g) => g.label),
    artists: plan.artists.map((a) => a.name),
    moods: plan.moods.map((m) => m.label),
    bpm: [plan.bpmRange.min, plan.bpmRange.max],
    found: old?.found,
    favorite: old?.favorite || false,
    name: old?.name,
    runs: (old?.runs || 0) + 1,
  };
  state.history = [entry, ...state.history.filter((e) => e.id !== entry.id)];
  persist.save('history');
  renderHistory();
  syncFavButton();
  return entry;
}
function updateHistoryCount(f, items) {
  const e = state.history.find((x) => formKey(x.form) === formKey(f));
  if (!e) return;
  const counts = Object.fromEntries(CATEGORY_ORDER.map((c) => [c, 0]));
  items.forEach((b) => counts[analyze(b).license.category]++);
  updateEntry(e.id, { found: counts });
}
function updateEntry(id, patch) {
  state.history = state.history.map((e) => (e.id === id ? { ...e, ...patch } : e));
  persist.save('history');
  renderHistory();
  syncFavButton();
}
function currentEntry() {
  const key = formKey(readForm());
  return state.history.find((e) => formKey(e.form) === key);
}
function syncFavButton() {
  const f = readForm();
  const btn = $('#favNow');
  btn.hidden = !(f.prompt || f.manualQuery);
  const e = currentEntry();
  btn.textContent = e?.favorite ? '★ En favori' : '☆ Mettre en favori';
  btn.classList.toggle('on', !!e?.favorite);
}
$('#favNow').addEventListener('click', () => {
  let e = currentEntry();
  if (!e) e = saveHistory(readForm(), currentPlan);
  updateEntry(e.id, { favorite: !e.favorite });
  toast(e.favorite ? 'Retirée des favoris' : 'Ajoutée aux favoris');
});

const entryTitle = (e) => e.name || e.form.prompt || e.form.manualQuery || 'Recherche sans titre';
const licenseSummary = (f) => (f.licenses || []).map((l) => CATEGORIES[l]?.label).join(' + ') || 'toutes licences';

function renderEntry(e) {
  const box = h('div', { class: `hist${e.favorite ? ' fav' : ''}` });
  const actions = h('div', { class: 'hist-actions' });
  const fillActions = () => {
    actions.replaceChildren(
      h('button', { type: 'button', class: 'primary small', onclick: () => { writeForm(e.form); showView('search'); runSearch(e.form, currentPlan); } }, '↻ Relancer'),
      h('button', { type: 'button', class: 'mini', onclick: () => { writeForm(e.form); showView('search'); $('#searchForm').classList.remove('collapsed'); promptEl.focus(); } }, '✏️ Modifier'),
      e.favorite ? h('button', { type: 'button', class: 'mini', onclick: rename }, '🏷️ Renommer') : null,
      h('button', { type: 'button', class: 'mini danger', onclick: remove }, '🗑️ Supprimer'),
    );
  };
  const rename = () => {
    const input = h('input', { type: 'text', value: entryTitle(e), 'aria-label': 'Nom du favori', id: `rename-${e.id}` });
    const ok = () => updateEntry(e.id, { name: input.value.trim() || undefined });
    input.addEventListener('keydown', (ev) => { if (ev.key === 'Enter') ok(); if (ev.key === 'Escape') fillActions(); });
    actions.replaceChildren(input, h('button', { type: 'button', class: 'primary small', onclick: ok }, 'OK'), h('button', { type: 'button', class: 'mini', onclick: fillActions }, 'Annuler'));
    input.focus();
    input.select();
  };
  const remove = () => {
    const before = state.history;
    state.history = state.history.filter((x) => x.id !== e.id);
    persist.save('history');
    renderHistory();
    toast('Recherche supprimée', { label: 'Annuler', run: () => { state.history = before; persist.save('history'); renderHistory(); } });
  };
  fillActions();
  const found = e.found ? CATEGORY_ORDER.filter((c) => e.found[c]).map((c) => h('span', { class: `tag plain cat-${c}`, style: 'color: var(--c)' }, `${GROUP_ICON[c]} ${e.found[c]}`)) : [];
  box.append(
    h('div', { class: 'hist-top' },
      h('button', { type: 'button', class: `star${e.favorite ? ' on' : ''}`, title: e.favorite ? 'Retirer des favoris' : 'Mettre en favori', 'aria-label': 'Favori', onclick: () => updateEntry(e.id, { favorite: !e.favorite }) }, '⭐'),
      h('div', { class: 'hist-title' }, entryTitle(e)),
      h('div', { class: 'hist-date' }, new Date(e.date).toLocaleString('fr-FR', { dateStyle: 'short', timeStyle: 'short' }), e.device === 'mobile' ? ' · 📱' : ' · 💻')),
    h('div', { class: 'tags' },
      ...(e.moods || []).map((m) => h('span', { class: 'tag' }, m)),
      ...(e.genres || []).map((g) => h('span', { class: 'tag genre' }, g)),
      ...(e.artists || []).map((a) => h('span', { class: 'tag artist' }, a)),
      h('span', { class: 'tag plain' }, `${e.bpm?.[0]}–${e.bpm?.[1]} BPM`),
      h('span', { class: 'tag plain' }, licenseSummary(e.form)),
      ...found,
      e.runs > 1 ? h('span', { class: 'tag plain' }, `lancée ${e.runs}×`) : null),
    h('div', { class: 'hist-queries' }, h('span', {}, 'Recherches utilisées :'), ...e.queries.map((q) => h('code', {}, q))),
    actions,
  );
  return box;
}

function renderHistory() {
  const onlyFav = $('#onlyFav').checked;
  const list = [...state.history].sort((a, b) => (b.favorite ? 1 : 0) - (a.favorite ? 1 : 0)).filter((e) => !onlyFav || e.favorite);
  $('#historyList').replaceChildren(...(list.length
    ? list.map(renderEntry)
    : [h('div', { class: 'empty-list' }, onlyFav
      ? '⭐ Aucun favori pour l’instant. Clique sur l’étoile d’une recherche pour la garder.'
      : '🕘 Pas encore de recherche. Lance une recherche : elle apparaîtra ici avec les requêtes utilisées.')]));
  $('#clearHistory').hidden = !state.history.length;
}
$('#onlyFav').addEventListener('change', renderHistory);
let clearArmed = null;
$('#clearHistory').addEventListener('click', () => {
  const btn = $('#clearHistory');
  if (!clearArmed) {
    btn.textContent = 'Confirmer : tout effacer (favoris gardés)';
    clearArmed = setTimeout(() => { btn.textContent = 'Tout effacer'; clearArmed = null; }, 4000);
    return;
  }
  clearTimeout(clearArmed);
  clearArmed = null;
  btn.textContent = 'Tout effacer';
  state.history = state.history.filter((e) => e.favorite);
  persist.save('history');
  renderHistory();
  toast('Historique effacé, favoris gardés');
});

// ---------------------------------------------------------------------------
// VÉRIFIER : colle titre + description → verdict immédiat

const EXAMPLES = [
  ['Titre trompeur', 'demo-baby1'],
  ['Spotify ❌', 'demo-gunna1'],
  ['Up to 5K streams', 'demo-uzi2'],
  ['Vraiment free', 'demo-uzi3'],
];
for (const [label, vid] of EXAMPLES) {
  $('#vExamples').append(h('button', {
    type: 'button', class: 'chip', onclick: () => {
      const v = DEMO_VIDEOS.find((d) => d.id === vid);
      $('#vUrl').value = '';
      $('#vTitle').value = v.title;
      $('#vDesc').value = v.description;
      updateVerify();
    },
  }, label));
}
for (const c of ['ffp', 'upto', 'fnp', 'paid']) {
  $('#legend').append(h('li', { class: `cat-${c}` }, h('b', {}, `${GROUP_ICON[c]} ${CATEGORIES[c].label}`), CATEGORIES[c].help));
}

function draftBeat() {
  const url = $('#vUrl').value.trim();
  const yid = youtubeId(url);
  return {
    id: yid || `b-${Date.now().toString(36)}`,
    url: yid ? `https://www.youtube.com/watch?v=${yid}` : (/^https?:\/\//.test(url) ? url : ''),
    title: $('#vTitle').value.trim(),
    description: $('#vDesc').value.trim().slice(0, DESC_MAX),
  };
}
let verifyTimer;
let sampleFn = null;
function updateVerify() {
  const b = draftBeat();
  local.set('draft', { url: $('#vUrl').value, title: $('#vTitle').value, desc: $('#vDesc').value });
  const has = !!(b.title || b.description);
  $('#vEmpty').hidden = has;
  $('#vResult').hidden = !has;
  $('#vAdd').disabled = !has;
  $('#vClaude').hidden = true;
  if (!has) return;
  const r = analyze(b);
  const already = state.beats.some((x) => x.id === b.id || (x.title === b.title && x.description === b.description));
  $('#vAdd').textContent = already ? '✓ Déjà dans ma liste' : '➕ Ajouter à ma liste';
  $('#vAdd').disabled = already;
  $('#vResult').replaceChildren(renderCard(b, r, { open: true, big: true }));
  if (sampleFn) {
    $('#vResult').append(h('div', { class: 'hint' },
      'Formulation inhabituelle ? ',
      h('button', { type: 'button', class: 'mini', onclick: askClaude }, '🤖 Demander l’avis de Claude'),
      ' (utilise ton forfait Claude)'));
  }
}
$('#vTitle').addEventListener('paste', (e) => {
  const text = e.clipboardData?.getData('text') || '';
  if (!text.includes('\n')) return;
  e.preventDefault();
  const [first, ...rest] = text.split(/\r?\n/);
  $('#vTitle').value = first.trim();
  if (!$('#vDesc').value.trim()) $('#vDesc').value = rest.join('\n').trim();
  updateVerify();
});
['#vUrl', '#vTitle', '#vDesc'].forEach((s) => $(s).addEventListener('input', () => { clearTimeout(verifyTimer); verifyTimer = setTimeout(updateVerify, 120); }));
$('#vClear').addEventListener('click', () => { $('#vUrl').value = ''; $('#vTitle').value = ''; $('#vDesc').value = ''; updateVerify(); $('#vTitle').focus(); });
$('#vAdd').addEventListener('click', () => {
  const b = { ...draftBeat(), addedAt: new Date().toISOString() };
  if (!b.title && !b.description) return;
  state.beats = [b, ...state.beats.filter((x) => x.id !== b.id)];
  persist.save('beats');
  updateListCount();
  updateVerify();
  toast('Ajoutée à ma liste', { label: 'Voir', run: () => showView('list') });
});
$('#listAdd').addEventListener('click', () => { showView('verify'); $('#vTitle').focus(); });

let claudeCtl = null;
async function askClaude() {
  const b = draftBeat();
  const box = $('#vClaude');
  box.hidden = false;
  box.replaceChildren(h('span', { class: 'spinner' }), 'Claude lit la description…');
  claudeCtl?.abort();
  claudeCtl = new AbortController();
  const prompt = [
    'Tu aides un rappeur à savoir s’il peut sortir un son sur Spotify avec une prod (beat) trouvée sur YouTube.',
    'Lis le titre et la description ci-dessous. La description fait foi sur le titre.',
    'Catégories : "ffp" = free for profit sans limite (Spotify OK sans payer) ; "upto" = free for profit jusqu’à une limite de streams ; "fnp" = gratuit seulement pour usage non commercial, il faut payer pour Spotify ; "paid" = payant ou vendue ; "unknown" = rien de clair.',
    'Réponds UNIQUEMENT avec un objet JSON : {"categorie": "ffp|upto|fnp|paid|unknown", "limite_streams": nombre ou null, "credit_obligatoire": true/false, "titre_trompeur": true/false, "explication": "2 phrases max en français simple", "citation": "la phrase exacte de la description qui décide, ou chaîne vide"}',
    '',
    `TITRE : ${b.title}`,
    'DESCRIPTION :',
    b.description.slice(0, 6000),
  ].join('\n');
  try {
    const ans = await sampleFn.json(prompt, { signal: claudeCtl.signal });
    const cat = CATEGORIES[ans?.categorie] ? ans.categorie : 'unknown';
    const algo = analyze(b).license.category;
    box.replaceChildren(
      h('h4', {}, '🤖 Avis de Claude'),
      h('div', { class: `cat-${cat}` }, h('b', { style: 'color: var(--c)' }, `${GROUP_ICON[cat]} ${cat === 'upto' && ans.limite_streams ? `Up to ${formatCount(Number(ans.limite_streams))} streams` : CATEGORIES[cat].label}`),
        ans.titre_trompeur ? ' · ⚠️ titre trompeur' : '', ans.credit_obligatoire ? ' · ✍️ crédit obligatoire' : ''),
      h('p', { style: 'margin:6px 0 0' }, String(ans.explication || '')),
      ans.citation ? h('q', {}, String(ans.citation)) : null,
      h('p', { class: 'agree', style: 'margin:8px 0 0' }, cat === algo ? '✔ Même verdict que l’algo.' : `≠ L’algo dit « ${CATEGORIES[algo].label} ». Relis la description pour trancher.`),
    );
  } catch (e) {
    if (e?.code === 'cancelled') return;
    const msg = {
      not_granted: 'Tu n’as pas autorisé cette page à utiliser Claude.',
      sampling_disabled: 'Claude n’est pas disponible pour ce compte.',
      rate_limited: 'Trop de demandes pour le moment : réessaie dans un moment.',
      invalid_json: 'Réponse illisible : réessaie.',
    }[e?.code] || 'Claude n’a pas pu répondre. Réessaie plus tard.';
    box.replaceChildren(h('h4', {}, '🤖 Avis de Claude'), msg);
    if (['not_granted', 'sampling_disabled', 'not_declared', 'capability_disabled', 'capability_removed'].includes(e?.code)) sampleFn = null;
  }
}

// ---------------------------------------------------------------------------
// MA LISTE

$('#hideExamples').addEventListener('click', () => { local.set('examplesHidden', true); listBoard.render(); });
function updateListCount() {
  const dot = $('#listCount');
  dot.hidden = !state.beats.length;
  dot.textContent = state.beats.length;
}
function removeBeat(id) {
  const before = state.beats;
  state.beats = state.beats.filter((b) => b.id !== id);
  persist.save('beats');
  listBoard.render();
  updateListCount();
  toast('Prod retirée', { label: 'Annuler', run: () => { state.beats = before; persist.save('beats'); listBoard.render(); updateListCount(); } });
}
const listBoard = createBoard($('#listBoard'), 'list', {
  defaultOff: ['paid', 'unknown'],
  recentLabel: 'Ajout récent',
  source: () => {
    let src;
    if (state.beats.length) src = { items: state.beats, manual: true };
    else if (!local.get('examplesHidden', false)) src = { items: DEMO_VIDEOS.map((v) => ({ id: v.id, title: v.title, description: v.description, channel: v.channel.replace(' (démo)', '') })), example: true };
    else src = { items: [] };
    $('#examplesBanner').hidden = !src.example;
    return {
      ...src,
      showEmpty: true,
      empty: () => h('div', { class: 'nores' }, h('div', { style: 'font-size:34px' }, '🗂️'), h('h3', {}, 'Ta liste est vide'),
        h('p', {}, 'Dans « Recherche », clique sur « ➕ Garder » sous une prod. Ou vérifie une prod à la main dans « Vérifier ».'),
        h('button', { type: 'button', class: 'primary small', onclick: () => showView('search') }, '🔎 Lancer une recherche')),
    };
  },
  actions: (beat, src) => (src.example ? [] : [() => h('button', { type: 'button', class: 'act', title: 'Retirer de ma liste', onclick: () => removeBeat(beat.id) }, '🗑️', h('span', {}, 'Retirer'))]),
});

// ---------------------------------------------------------------------------
// Démarrage

const DEFAULT_FORM = { prompt: 'rapide, énergique et musicale', manualQuery: '', licenses: ['ffp', 'upto'], depth: '' };
writeForm(local.get('form', DEFAULT_FORM));
const draft = local.get('draft', null);
if (draft) { $('#vUrl').value = draft.url || ''; $('#vTitle').value = draft.title || ''; $('#vDesc').value = draft.desc || ''; }
applyDevice();
updateVerify();
renderHistory();
updateListCount();
if (lastSearch) { renderSearchHead(); $('#planBox').open = false; }
searchBoard.render();
listBoard.render();
showView(location.hash.slice(1) || local.get('view', 'search'), { scroll: false });
persist.init();
window.claude?.use?.('sample').then((s) => { sampleFn = s || null; if (s) updateVerify(); }).catch(() => {});
})();
