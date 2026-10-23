(() => {
'use strict';
// Melofinds, version page Claude. Le moteur (buildPlan, analyzeVideo, filterResults…)
// est chargé juste avant ce script ; ici, seulement l'interface.

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
// Données gardées : historique + ma liste.
// Dans ton compte Claude (capacité « db », dossier privé) quand c'est possible,
// sinon dans ce navigateur seulement.

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
            this.save(key); // première fois : on envoie ce que ce navigateur avait déjà
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
        else if (e?.code === 'invalid_argument' || e?.code === 'revoked' || e?.code === 'not_granted') { this.mode = 'local'; setSync(); }
      });
    }, 500);
  },
};
function setSync() {
  $('#syncBadge').textContent = persist.mode === 'db' ? '☁️ Sauvé dans ton compte' : '💾 Sauvé dans ce navigateur';
}
function renderFor(key) {
  if (key === 'history') { renderHistory(); syncFavButton(); }
  else { renderList(); updateListCount(); }
}

// ---------------------------------------------------------------------------
// Appareil : l'algo s'adapte (mise en page, nombre de recherches)

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
  if (name === 'list') renderList();
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

// ---------------------------------------------------------------------------
// RECHERCHE : description → courants → artistes → recherches YouTube

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
for (const [id, ico, label, sub] of LICENSES) {
  $('#licenseGrid').append(h('label', { class: `lic cat-${id}`, for: `lic-${id}` },
    h('input', { type: 'checkbox', name: 'lic', value: id, id: `lic-${id}` }),
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
  $('#planTitle').textContent = hasInput ? (f.prompt || f.manualQuery) : 'Décris ta prod à gauche';
  $('#planNotes').replaceChildren(...(hasInput ? plan.notes : []).map((n) => h('div', { class: 'note' }, '⚠️ ', n)));
  $('#pMoods').replaceChildren(...(plan.moods.length
    ? plan.moods.map((m) => h('span', { class: 'tag', title: `mots reconnus : ${m.matched.join(', ')}` }, m.label))
    : [h('span', { class: 'tag plain' }, 'aucune reconnue')]));
  $('#pInstr').textContent = plan.instruments.length ? `Instruments : ${plan.instruments.join(', ')}` : '';
  $('#pGenres').replaceChildren(...plan.genres.map((g) => h('span', { class: 'tag genre', title: g.why.join(', ') }, g.label)));
  $('#pArtists').replaceChildren(...plan.artists.map((a) => h('a', {
    class: 'tag artist', href: ytSearch(`${a.name} type beat${plan.licenseSuffix ? ` ${plan.licenseSuffix}` : ''}`), target: '_blank', rel: 'noopener', title: a.reason,
  }, a.name)));
  $('#pBpm').replaceChildren(`${plan.bpmRange.min}–${plan.bpmRange.max}`, h('small', {}, 'BPM'));
  $('#pBpmWhy').textContent = plan.bpmRange.source;
  $('#qTitle').textContent = `${plan.queries.length} recherches YouTube · profondeur ${plan.depth.label.toLowerCase()}${plan.device === 'mobile' ? ' (mobile)' : ''}`;
  $('#queries').replaceChildren(...plan.queries.map((q) => h('li', { class: 'q' },
    h('div', { class: 'q-main' }, h('div', { class: 'q-text' }, q.q), h('div', { class: 'q-why' }, q.why)),
    h('div', { class: 'q-actions' },
      h('button', { type: 'button', class: 'mini', title: 'Copier la recherche', onclick: () => copyText(q.q, 'Recherche copiée') }, '⧉'),
      h('a', { class: 'yt', href: ytSearch(q.q), target: '_blank', rel: 'noopener' }, '▶ YouTube ↗')))));
}

let planTimer;
const debouncedPlan = () => { clearTimeout(planTimer); planTimer = setTimeout(updatePlan, 150); };
promptEl.addEventListener('input', debouncedPlan);
$('#manualQuery').addEventListener('input', debouncedPlan);
$('#depth').addEventListener('change', updatePlan);
$('#licenseGrid').addEventListener('change', updatePlan);
$('#clearPrompt').addEventListener('click', () => { promptEl.value = ''; updatePlan(); promptEl.focus(); });
$('#formToggle').addEventListener('click', () => $('#searchForm').classList.remove('collapsed'));
$('#goVerify').addEventListener('click', () => { showView('verify'); $('#vTitle').focus(); });

$('#searchForm').addEventListener('submit', (e) => {
  e.preventDefault();
  const f = readForm();
  if (!f.prompt && !f.manualQuery) { toast('Écris d’abord une description, ex. « rapide, énergique et musicale »'); promptEl.focus(); return; }
  updatePlan();
  saveHistory(f, currentPlan);
  toast('Recherche gardée dans l’historique');
  if (device === 'mobile') {
    $('#searchForm').classList.add('collapsed');
    $('#formToggleText').textContent = f.prompt || f.manualQuery;
    $('#planCol').scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
});
document.addEventListener('keydown', (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key === 'Enter' && $('#view-search').classList.contains('active')) {
    e.preventDefault();
    $('#searchForm').requestSubmit();
  }
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
      h('button', { type: 'button', class: 'primary small', onclick: () => { writeForm(e.form); showView('search'); saveHistory(e.form, currentPlan); } }, '↻ Relancer'),
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
      e.runs > 1 ? h('span', { class: 'tag plain' }, `lancée ${e.runs}×`) : null),
    h('div', { class: 'hist-queries' }, h('span', {}, 'Recherches utilisées :'),
      ...e.queries.map((q) => h('a', { href: ytSearch(q), target: '_blank', rel: 'noopener' }, h('code', {}, q)))),
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
      : '🕘 Pas encore de recherche gardée. Lance une recherche : elle apparaîtra ici avec les requêtes YouTube utilisées.')]));
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
// Cartes de prod (Vérifier + Ma liste)

function youtubeId(url) {
  const m = String(url || '').match(/(?:youtu\.be\/|v=|\/shorts\/|\/embed\/|\/live\/)([\w-]{11})/);
  return m ? m[1] : null;
}
function analyze(beat) {
  return analyzeVideo({ id: beat.id, title: beat.title, description: beat.description, channel: beat.channel, views: beat.views }, null);
}

function renderCard(beat, r, { terms = [], open = false, big = false, onRemove = null, example = false } = {}) {
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
  body.append(h('h3', { class: 'title', title: beat.title }, beat.title || '(sans titre)'));
  const meta = [beat.channel, beat.addedAt ? `ajoutée le ${new Date(beat.addedAt).toLocaleDateString('fr-FR')}` : null].filter(Boolean).join(' · ');
  if (meta) body.append(h('div', { class: 'meta' }, meta));
  if (L.misleading) {
    body.append(h('div', { class: 'alert' }, h('span', { 'aria-hidden': 'true' }, '⚠️'),
      h('span', {}, h('b', {}, 'Titre trompeur. '), 'Le titre dit « free for profit », mais la description demande de payer pour sortir le son sur Spotify.')));
  }
  const badges = h('div', { class: 'badges' });
  if (L.creditRequired) badges.append(h('span', { class: 'badge credit' }, '✍️ Crédit obligatoire'));
  badges.append(h('span', { class: 'badge' }, `Spotify : ${L.spotify}`));
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
    beat.url ? h('button', { type: 'button', class: 'act', title: 'Copier le lien', onclick: () => copyText(beat.url, 'Lien copié') }, '🔗', h('span', {}, 'Lien')) : null,
    onRemove ? h('button', { type: 'button', class: 'act', title: 'Retirer de ma liste', onclick: onRemove }, '🗑️', h('span', {}, 'Retirer')) : null));
  card.append(details);
  return card;
}

// ---------------------------------------------------------------------------
// VÉRIFIER : colle titre + description → verdict immédiat

const EXAMPLES = [
  ['Titre trompeur', 'demo-baby1'],
  ['Spotify ❌', 'demo-gunna1'],
  ['Up to 5K streams', 'demo-uzi2'],
  ['Vraiment free', 'demo-uzi3'],
];
for (const [label, id] of EXAMPLES) {
  $('#vExamples').append(h('button', {
    type: 'button', class: 'chip', onclick: () => {
      const v = DEMO_VIDEOS.find((d) => d.id === id);
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
  const card = renderCard(b, r, { open: true, big: true });
  $('#vResult').replaceChildren(card);
  if (sampleFn) {
    $('#vResult').append(h('div', { class: 'hint' },
      'Formulation inhabituelle ? ',
      h('button', { type: 'button', class: 'mini', onclick: askClaude }, '🤖 Demander l’avis de Claude'),
      ' (utilise ton forfait Claude)'));
  }
}
// Coller tout d'un coup dans « Titre » : 1re ligne = titre, le reste = description
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

// Avis de Claude (facultatif) via la capacité « sample »
let sampleFn = null;
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
// MA LISTE : tri par licence, BPM, style, recherche dans les descriptions

const listPrefs = local.get('listPrefs', { off: ['paid', 'unknown'], onlyMisleading: false });
const QUICK_TERMS = ['spotify', 'crédit', 'untagged', 'wav', 'contact', '-lease'];
for (const term of QUICK_TERMS) {
  $('#quickTerms').append(h('button', {
    type: 'button', class: 'chip', 'data-term': term,
    title: term.startsWith('-') ? `Cacher les prods dont la description contient « ${term.slice(1)} »` : `Prods dont la description contient « ${term} »`,
    onclick: () => {
      const input = $('#descSearch');
      const words = input.value.split(/\s+/).filter(Boolean);
      const i = words.indexOf(term);
      if (i >= 0) words.splice(i, 1); else words.push(term);
      input.value = words.join(' ');
      renderList();
    },
  }, term.startsWith('-') ? `sans ${term.slice(1)}` : term));
}
let descTimer;
$('#descSearch').addEventListener('input', () => { clearTimeout(descTimer); descTimer = setTimeout(renderList, 120); });
['#sort', '#styleFilter', '#bpmRequire', '#noCredit'].forEach((s) => $(s).addEventListener('change', renderList));
['#bpmMin', '#bpmMax'].forEach((s) => $(s).addEventListener('input', renderList));
$('#bpmEnabled').addEventListener('change', () => {
  const on = $('#bpmEnabled').checked;
  $('#bpmBox').hidden = !on;
  if (on && $('#sort').value === 'pertinence') $('#sort').value = 'bpm-asc';
  if (!on && $('#sort').value.startsWith('bpm')) $('#sort').value = 'pertinence';
  renderList();
});
$('#hideExamples').addEventListener('click', () => { local.set('examplesHidden', true); renderList(); });

function listSource() {
  if (state.beats.length) return { items: state.beats, example: false };
  if (local.get('examplesHidden', false)) return { items: [], example: false };
  return { items: DEMO_VIDEOS.map((v) => ({ id: v.id, title: v.title, description: v.description, channel: v.channel.replace(' (démo)', '') })), example: true };
}

function updateListCount() {
  const dot = $('#listCount');
  dot.hidden = !state.beats.length;
  dot.textContent = state.beats.length;
}

function renderList() {
  const { items, example } = listSource();
  $('#examplesBanner').hidden = !example;
  const analysed = items.map((b, i) => ({ beat: b, r: { ...analyze(b), addedOrder: i, publishedAt: b.addedAt } }));
  const results = analysed.map((a) => ({ ...a.r, _beat: a.beat }));
  const beats = results.filter((r) => r.isBeat || !example);
  beats.forEach((r) => { r.isBeat = true; }); // une prod collée à la main compte toujours

  // Compteurs = filtres de licence cliquables
  const off = new Set(listPrefs.off);
  const counts = Object.fromEntries(CATEGORY_ORDER.map((c) => [c, 0]));
  beats.forEach((r) => counts[r.license.category]++);
  const misleading = beats.filter((r) => r.license.misleading).length;
  const tiles = CATEGORY_ORDER.map((c) => h('button', {
    type: 'button', class: `stat cat-${c}${off.has(c) || listPrefs.onlyMisleading ? ' off' : ''}`,
    'aria-pressed': String(!off.has(c)), title: off.has(c) ? 'Afficher' : 'Masquer',
    onclick: () => {
      listPrefs.onlyMisleading = false;
      if (off.has(c)) off.delete(c); else off.add(c);
      listPrefs.off = [...off];
      local.set('listPrefs', listPrefs);
      renderList();
    },
  }, h('b', {}, counts[c]), h('span', {}, `${GROUP_ICON[c]} ${CATEGORIES[c].label}`)));
  if (misleading) {
    tiles.push(h('button', {
      type: 'button', class: `stat cat-warn${listPrefs.onlyMisleading ? '' : ' off'}`,
      title: 'Titre « free for profit » mais la description demande de payer pour Spotify',
      onclick: () => { listPrefs.onlyMisleading = !listPrefs.onlyMisleading; local.set('listPrefs', listPrefs); renderList(); },
    }, h('b', {}, misleading), h('span', {}, '⚠️ Titres trompeurs')));
  }
  $('#stats').replaceChildren(...tiles);

  // Filtre « style »
  const styleSel = $('#styleFilter');
  const prev = styleSel.value;
  const styles = stylesIn(beats);
  styleSel.replaceChildren(h('option', { value: '' }, 'Tous'), ...styles.map((s) => h('option', { value: s.id }, `${s.label} (${s.count})`)));
  styleSel.value = styles.some((s) => s.id === prev) ? prev : '';

  const text = $('#descSearch').value.trim();
  const f = {
    licenses: listPrefs.onlyMisleading ? CATEGORY_ORDER : CATEGORY_ORDER.filter((c) => !off.has(c)),
    noCredit: $('#noCredit').checked,
    style: styleSel.value,
    text,
    bpm: { enabled: $('#bpmEnabled').checked, min: Number($('#bpmMin').value) || null, max: Number($('#bpmMax').value) || null, requireBpm: $('#bpmRequire').checked },
  };
  let filtered = filterResults(beats, f);
  if (listPrefs.onlyMisleading) filtered = filtered.filter((r) => r.license.misleading);
  let sorted = sortResults(filtered, $('#sort').value === 'recent' ? 'pertinence' : $('#sort').value);
  if ($('#sort').value === 'recent') sorted = [...filtered].sort((a, b) => a.addedOrder - b.addedOrder);
  const groups = groupByCategory(sorted);
  const terms = text ? parseTextQuery(text).include : [];
  const quickOn = new Set(text.split(/\s+/));
  $$('#quickTerms .chip').forEach((c) => c.classList.toggle('on', quickOn.has(c.dataset.term)));

  const hidden = beats.length - filtered.length;
  $('#count').textContent = beats.length
    ? `${filtered.length} prod(s) affichée(s)${hidden ? ` · ${hidden} masquée(s) par tes filtres` : ''}${example ? ' · exemples' : ''}`
    : '';

  const out = $('#listResults');
  if (!beats.length) {
    out.replaceChildren(h('div', { class: 'nores' }, h('div', { style: 'font-size:34px' }, '🗂️'), h('h3', {}, 'Ta liste est vide'),
      h('p', {}, 'Va dans « Vérifier », colle le titre et la description d’une prod YouTube, puis « Ajouter à ma liste ».'),
      h('button', { type: 'button', class: 'primary small', onclick: () => showView('verify') }, '📖 Vérifier une prod')));
    return;
  }
  if (!groups.length) {
    out.replaceChildren(h('div', { class: 'nores' }, h('div', { style: 'font-size:34px' }, '🫥'), h('h3', {}, 'Aucune prod avec ces filtres'),
      h('p', {}, text ? `Aucune description ne contient « ${text} ». ` : '', 'Clique sur une catégorie en haut pour l’afficher, ou élargis la plage BPM.')));
    return;
  }
  out.replaceChildren(...groups.map((g) => h('section', { class: `group cat-${g.category}` },
    h('div', { class: 'group-head' },
      h('span', { class: 'gico', 'aria-hidden': 'true' }, GROUP_ICON[g.category]),
      h('div', {}, h('h2', {}, CATEGORIES[g.category].label, h('small', {}, g.items.length)), h('p', {}, CATEGORIES[g.category].help))),
    h('div', { class: 'grid' }, g.items.map((r) => renderCard(r._beat, r, {
      terms,
      example,
      onRemove: example ? null : () => removeBeat(r._beat.id),
    }))))));
}

function removeBeat(id) {
  const before = state.beats;
  state.beats = state.beats.filter((b) => b.id !== id);
  persist.save('beats');
  renderList();
  updateListCount();
  toast('Prod retirée', { label: 'Annuler', run: () => { state.beats = before; persist.save('beats'); renderList(); updateListCount(); } });
}

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
showView(location.hash.slice(1) || local.get('view', 'search'), { scroll: false });
persist.init();
window.claude?.use?.('sample').then((s) => { sampleFn = s || null; if (s) updateVerify(); }).catch(() => {});
})();
