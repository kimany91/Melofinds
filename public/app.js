import { buildPlan, defaultDepth, DEPTHS } from '/core/planner.js';
import { filterResults, sortResults, groupByCategory, stylesIn, parseTextQuery } from '/core/filter.js';
import { CATEGORIES, CATEGORY_ORDER, formatCount } from '/core/license.js';

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
// Stockage local (historique, favoris, prods sauvegardées, réglages)

const store = {
  get(k, fallback) {
    try {
      const v = localStorage.getItem(`mf.${k}`);
      return v == null ? fallback : JSON.parse(v);
    } catch {
      return fallback;
    }
  },
  set(k, v) {
    try { localStorage.setItem(`mf.${k}`, JSON.stringify(v)); } catch { /* stockage indisponible */ }
  },
};

let toastTimer;
function toast(msg) {
  const t = $('#toast');
  t.textContent = msg;
  t.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove('show'), 1800);
}

// ---------------------------------------------------------------------------
// Thème

function applyTheme() {
  const t = store.get('theme', '');
  if (t) document.documentElement.dataset.theme = t;
  else delete document.documentElement.dataset.theme;
  const dark = t ? t === 'dark' : !matchMedia('(prefers-color-scheme: light)').matches;
  $('#themeBtn').textContent = dark ? '🌙' : '☀️';
}
$('#themeBtn').addEventListener('click', () => {
  const dark = document.documentElement.dataset.theme
    ? document.documentElement.dataset.theme === 'dark'
    : !matchMedia('(prefers-color-scheme: light)').matches;
  store.set('theme', dark ? 'light' : 'dark');
  applyTheme();
});

// ---------------------------------------------------------------------------
// Appareil : l'algo s'adapte (mise en page, nombre de requêtes, lecteur…)

function detectDevice() {
  const forced = store.get('device', '');
  if (forced === 'mobile' || forced === 'desktop') return forced;
  const ua = /Mobi|Android|iPhone|iPad|iPod/i.test(navigator.userAgent);
  return ua || window.innerWidth < 760 ? 'mobile' : 'desktop';
}

let device = detectDevice();
function applyDevice() {
  document.body.classList.toggle('mobile', device === 'mobile');
  document.body.classList.toggle('desktop', device === 'desktop');
  const forced = store.get('device', '');
  $('#deviceBadge').textContent = `${device === 'mobile' ? '📱 Mobile' : '💻 PC'}${forced ? ' · forcé' : ''}`;
  $('#depth option[value=""]').textContent = `Auto · ${DEPTHS[defaultDepth(device)].label.toLowerCase()} sur ${device === 'mobile' ? 'mobile' : 'PC'}`;
  updatePreview();
  if (lastResponse) renderResults();
}
$('#deviceBadge').addEventListener('click', () => {
  const forced = store.get('device', '');
  store.set('device', forced ? '' : device === 'mobile' ? 'desktop' : 'mobile');
  device = detectDevice();
  applyDevice();
  toast(device === 'mobile' ? 'Mode mobile : recherche plus légère' : 'Mode PC : recherche plus complète');
});
let resizeTimer;
window.addEventListener('resize', () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => {
    const d = detectDevice();
    if (d !== device) { device = d; applyDevice(); }
  }, 200);
});

// ---------------------------------------------------------------------------
// Onglets

function showView(name) {
  $$('.tab').forEach((t) => t.classList.toggle('active', t.dataset.view === name));
  $$('.view').forEach((v) => v.classList.toggle('active', v.id === `view-${name}`));
  if (name === 'history') renderHistory();
  if (name === 'favorites') renderFavorites();
  window.scrollTo({ top: 0 });
}
$$('.tab').forEach((t) => t.addEventListener('click', () => showView(t.dataset.view)));

// ---------------------------------------------------------------------------
// Formulaire

const SUGGESTIONS = [
  ['Vibe', ['rapide', 'énergique', 'musicale', 'sombre', 'triste', 'agressif', 'chill', 'planant', 'bouncy', 'joyeux']],
  ['Style', ['drill', 'rage', 'jerk', 'pluggnb', 'boom bap', 'detroit', 'phonk']],
  ['Instru', ['piano', 'guitare', 'synthé', 'cloches', 'violon']],
  ['Artiste', ['Lil Uzi', 'Pop Smoke', 'Travis Scott', 'Ken Carson', 'Gunna']],
];
const EXAMPLES = ['rapide, énergique et musicale', 'sombre, drill, 145 bpm', 'triste, guitare, pain music', 'chill, old school, jazzy', 'comme Ken Carson, rage'];

const promptEl = $('#prompt');
const sugBox = $('#suggestions');
for (const [label, words] of SUGGESTIONS) {
  sugBox.append(h('div', { class: 'sugg-row' }, h('b', {}, label), words.map((s) => h('button', {
    type: 'button',
    class: 'chip',
    'data-word': s,
    onclick: () => toggleWord(s),
  }, s))));
}
function toggleWord(s) {
  const parts = promptEl.value.split(',').map((p) => p.trim()).filter(Boolean);
  const i = parts.findIndex((p) => p.toLowerCase() === s.toLowerCase());
  if (i >= 0) parts.splice(i, 1);
  else parts.push(s);
  promptEl.value = parts.join(', ');
  updatePreview();
}
function syncSuggestionState() {
  const parts = promptEl.value.toLowerCase();
  $$('.chip', sugBox).forEach((c) => {
    const w = c.dataset.word.toLowerCase();
    c.classList.toggle('on', new RegExp(`(^|[^a-zà-ÿ])${w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}($|[^a-zà-ÿ])`).test(parts));
  });
}
$('#clearPrompt').addEventListener('click', () => { promptEl.value = ''; updatePreview(); promptEl.focus(); });

for (const ex of EXAMPLES) {
  $('#heroTry').append(h('button', {
    type: 'button',
    onclick: () => { promptEl.value = ex; $('#manualQuery').value = ''; updatePreview(); runSearch(readForm()); },
  }, `« ${ex} »`));
}

function readForm() {
  return {
    prompt: promptEl.value.trim(),
    manualQuery: $('#manualQuery').value.trim(),
    licenses: $$('input[name=lic]:checked').map((i) => i.value),
    uptoMin: Number($('#uptoMin').value) || 0,
    noCredit: $('#noCredit').checked,
    bpm: {
      enabled: $('#bpmEnabled').checked,
      min: Number($('#bpmMin').value) || null,
      max: Number($('#bpmMax').value) || null,
      requireBpm: $('#bpmRequire').checked,
    },
    depth: $('#depth').value,
  };
}

function writeForm(f) {
  promptEl.value = f.prompt || '';
  $('#manualQuery').value = f.manualQuery || '';
  const lic = new Set(f.licenses || []);
  $$('input[name=lic]').forEach((i) => { i.checked = lic.has(i.value); });
  $('#uptoMin').value = String(f.uptoMin || 0);
  $('#noCredit').checked = !!f.noCredit;
  $('#bpmEnabled').checked = !!f.bpm?.enabled;
  $('#bpmMin').value = f.bpm?.min ?? '';
  $('#bpmMax').value = f.bpm?.max ?? '';
  $('#bpmRequire').checked = !!f.bpm?.requireBpm;
  $('#depth').value = f.depth || '';
  syncBpmUi();
  syncLicenseUi();
  updatePreview();
}

function syncLicenseUi() {
  $('#uptoMinRow').hidden = !$('input[name=lic][value=upto]').checked;
}
function syncBpmUi() {
  const on = $('#bpmEnabled').checked;
  $('#bpmBox').hidden = !on;
  $('#bpmHint').hidden = on;
}

// Aperçu en direct du plan (calculé dans le navigateur, sans requête)
let currentPlan = null;
function planFor(f) {
  return buildPlan(f.prompt, { licenses: f.licenses, device, depth: f.depth || undefined, manualQuery: f.manualQuery });
}
function updatePreview() {
  const f = readForm();
  currentPlan = planFor(f);
  renderPlan($('#previewBody'), currentPlan, false);
  $('#previewCount').textContent = f.prompt || f.manualQuery ? `· ${currentPlan.queries.length} requêtes` : '';
  syncSuggestionState();
}
function fillBpmFromPlan() {
  if (!currentPlan) return;
  $('#bpmMin').value = currentPlan.bpmRange.min;
  $('#bpmMax').value = currentPlan.bpmRange.max;
}

function renderPlan(box, plan, withCounts) {
  box.replaceChildren();
  const sect = (title, ...kids) => h('div', {}, h('h4', {}, title), ...kids);
  if (plan.notes?.length) box.append(...plan.notes.map((n) => h('div', { class: 'note' }, '⚠️ ', n)));
  box.append(sect('Ambiances comprises',
    plan.moods.length
      ? h('div', { class: 'tags' }, plan.moods.map((m) => h('span', { class: 'tag', title: `mots reconnus : ${m.matched.join(', ')}` }, m.label)))
      : h('span', { class: 'why' }, 'aucune'),
    plan.instruments.length ? h('div', { class: 'why' }, `Instruments : ${plan.instruments.join(', ')}`) : null,
  ));
  box.append(sect('Courants de rap',
    h('div', { class: 'tags' }, plan.genres.map((g) => h('span', { class: 'tag genre', title: g.why.join(', ') }, `${g.label} · ${g.bpm[0]}-${g.bpm[1]}`)))));
  box.append(sect('Artistes US « type beat »',
    h('div', { class: 'tags' }, plan.artists.map((a) => h('span', { class: 'tag artist', title: a.reason }, a.name)))));
  box.append(sect('BPM conseillé', h('span', {}, `${plan.bpmRange.min}–${plan.bpmRange.max} BPM `), h('span', { class: 'why' }, `(${plan.bpmRange.source})`)));
  box.append(sect(`Recherches YouTube · ${plan.queries.length} · profondeur ${plan.depth.label.toLowerCase()}${plan.device === 'mobile' ? ' (mobile)' : ''}`,
    h('ol', {}, plan.queries.map((q) => h('li', {},
      h('code', {}, q.q), ' ',
      h('span', { class: 'why' }, `← ${q.why}${withCounts && q.count != null ? ` · ${q.count} vidéo(s)` : ''}${q.error ? ` · ⚠️ ${q.error}` : ''}`),
    )))));
}

let previewTimer;
const debouncedPreview = () => { clearTimeout(previewTimer); previewTimer = setTimeout(updatePreview, 150); };
promptEl.addEventListener('input', debouncedPreview);
$('#manualQuery').addEventListener('input', debouncedPreview);
$('#depth').addEventListener('change', updatePreview);

// Les filtres s'appliquent tout de suite aux résultats déjà trouvés.
$$('input[name=lic]').forEach((i) => i.addEventListener('change', () => { syncLicenseUi(); updatePreview(); renderResults(); }));
$('#uptoMin').addEventListener('change', renderResults);
$('#noCredit').addEventListener('change', renderResults);
$('#bpmEnabled').addEventListener('change', () => {
  const on = $('#bpmEnabled').checked;
  syncBpmUi();
  if (on) {
    if (!$('#bpmMin').value && !$('#bpmMax').value) fillBpmFromPlan();
    if ($('#sort').value === 'pertinence') $('#sort').value = 'bpm-asc';
  } else if ($('#sort').value.startsWith('bpm')) {
    $('#sort').value = 'pertinence';
  }
  renderResults();
});
['#bpmMin', '#bpmMax', '#bpmRequire'].forEach((s) => $(s).addEventListener('input', renderResults));
$('#bpmFromPlan').addEventListener('click', () => { fillBpmFromPlan(); renderResults(); });
$('#sort').addEventListener('change', renderResults);
$('#styleFilter').addEventListener('change', renderResults);
$('#formToggle').addEventListener('click', () => $('#searchForm').classList.remove('collapsed'));

// Recherche dans les descriptions
const QUICK_TERMS = ['spotify', 'crédit', 'untagged', 'wav', 'contact', '-lease'];
let descTimer;
$('#descSearch').addEventListener('input', () => { clearTimeout(descTimer); descTimer = setTimeout(renderResults, 120); });
for (const term of QUICK_TERMS) {
  $('#quickTerms').append(h('button', {
    type: 'button',
    class: 'chip',
    'data-term': term,
    title: term.startsWith('-') ? `Cacher les prods dont la description contient « ${term.slice(1)} »` : `Prods dont la description contient « ${term} »`,
    onclick: () => {
      const input = $('#descSearch');
      const words = input.value.split(/\s+/).filter(Boolean);
      const i = words.indexOf(term);
      if (i >= 0) words.splice(i, 1);
      else words.push(term);
      input.value = words.join(' ');
      renderResults();
    },
  }, term.startsWith('-') ? `sans ${term.slice(1)}` : term));
}

// Raccourcis : Ctrl/Cmd + Entrée = chercher, « / » = chercher dans les descriptions
document.addEventListener('keydown', (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') { e.preventDefault(); runSearch(readForm()); }
  if (e.key === '/' && !/INPUT|TEXTAREA|SELECT/.test(document.activeElement?.tagName) && lastResponse) {
    e.preventDefault();
    $('#descSearch').focus();
  }
});

// ---------------------------------------------------------------------------
// Recherche

let lastResponse = null;
let onlyMisleading = false;

$('#searchForm').addEventListener('submit', (e) => {
  e.preventDefault();
  runSearch(readForm());
});

function showSkeleton(n) {
  $('#empty').hidden = true;
  $('#results').replaceChildren(h('div', { class: 'grid' }, Array.from({ length: n }, () => h('div', { class: 'card skeleton' },
    h('div', { class: 'thumb' }),
    h('div', { class: 'card-body' }, h('div', { class: 'sk', style: 'width:40%' }), h('div', { class: 'sk', style: 'width:90%' }), h('div', { class: 'sk', style: 'width:70%' }), h('div', { class: 'sk', style: 'width:55%' }))))));
}

async function runSearch(f, { fromHistoryId = null, forceSource = null } = {}) {
  if (!f.prompt && !f.manualQuery) {
    showStatus('✍️ Écris d’abord une description (ex. « rapide, énergique et musicale ») ou une recherche directe.', 'info');
    $('#searchForm').classList.remove('collapsed');
    promptEl.focus();
    return;
  }
  const plan = planFor(f);
  const btn = $('#goBtn');
  btn.disabled = true;
  $('span', btn).textContent = 'Recherche…';
  showStatus(h('span', {}, h('span', { class: 'spinner' }), `${plan.queries.length} recherches YouTube en cours, puis lecture complète de chaque description…`));
  if (!lastResponse) showSkeleton(device === 'mobile' ? 3 : 6);
  const settings = store.get('settings', {});
  const headers = { 'Content-Type': 'application/json' };
  if (settings.apiKey) headers['x-youtube-key'] = settings.apiKey;
  try {
    const res = await fetch('/api/search', {
      method: 'POST',
      headers,
      body: JSON.stringify({
        prompt: f.prompt,
        manualQuery: f.manualQuery,
        licenses: f.licenses,
        device,
        depth: f.depth || undefined,
        source: forceSource || settings.source || undefined,
      }),
    });
    const data = await res.json().catch(() => ({ error: `Réponse invalide du serveur (${res.status})` }));
    if (!res.ok || data.error) throw Object.assign(new Error(data.error || `Erreur ${res.status}`), { hint: data.hint, source: data.source });
    lastResponse = data;
    onlyMisleading = false;
    hideStatus();
    if (data.warnings?.length) {
      showStatus(h('div', {}, h('b', {}, 'À savoir'), h('ul', {}, data.warnings.map((w) => h('li', {}, w)))), 'info');
    }
    if (f.bpm.enabled && !f.bpm.min && !f.bpm.max) {
      $('#bpmMin').value = data.plan.bpmRange.min;
      $('#bpmMax').value = data.plan.bpmRange.max;
    }
    saveHistory(f, data, fromHistoryId);
    renderResults();
    if (device === 'mobile') {
      $('#searchForm').classList.add('collapsed');
      $('#formToggleText').textContent = f.prompt || f.manualQuery;
    }
    $('#resultsHead').scrollIntoView({ behavior: 'smooth', block: 'start' });
  } catch (err) {
    if (!lastResponse) { $('#results').replaceChildren(); $('#empty').hidden = false; }
    showStatus(h('div', {},
      h('b', {}, '😕 La recherche a échoué : '), err.message,
      err.hint ? h('p', { class: 'muted' }, err.hint) : null,
      h('div', { class: 'actions' },
        err.source !== 'demo' ? h('button', { type: 'button', class: 'mini', onclick: () => runSearch(f, { fromHistoryId, forceSource: 'demo' }) }, '🎲 Essayer en mode démo') : null,
        h('button', { type: 'button', class: 'mini', onclick: () => $('#settingsBtn').click() }, '⚙️ Ajouter une clé YouTube'),
      ),
    ), 'error');
  } finally {
    btn.disabled = false;
    $('span', btn).textContent = 'Chercher les prods';
  }
}

function showStatus(content, kind = '') {
  const el = $('#status');
  el.className = `status ${kind}`;
  el.replaceChildren(content);
  el.hidden = false;
}
function hideStatus() { $('#status').hidden = true; }

// ---------------------------------------------------------------------------
// Rendu des résultats

const GROUP_ICON = { ffp: '✅', upto: '⏳', fnp: '🎧', paid: '💸', unknown: '❓' };
const KEYLINE_ICON = { licence: '📜', credit: '✍️', tempo: '🎚️', contact: '✉️' };
const KW_RE = /(free\s*(?:for|4)\s*profit|non[\s-]*profit|spotify|apple\s*music|streaming|youtube\s*only|lease|licen[cs]e|licence|cr[eé]dit|untagged|up\s*to\s*[\d.,\s]+k?\s*(?:streams?|plays?)|[\d.,]+\s*k?\s*(?:streams?|plays?|écoutes)|❌|✅)/gi;

function fmtDuration(s) {
  if (!s) return '';
  const m = Math.floor(s / 60);
  return `${m}:${String(Math.round(s % 60)).padStart(2, '0')}`;
}
function fmtDate(d) {
  if (!d) return '';
  const t = Date.parse(d);
  if (Number.isNaN(t)) return d;
  return new Date(t).toLocaleDateString('fr-FR', { day: 'numeric', month: 'short', year: 'numeric' });
}
const stripAccents = (s) => s.normalize('NFD').replace(/[̀-ͯ]/g, '');

/** Surligne les mots cherchés (<mark>) et les mots-clés de licence (<mark class="kw">). */
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

function currentFilters() {
  const f = readForm();
  return {
    licenses: onlyMisleading ? CATEGORY_ORDER : f.licenses,
    uptoMin: f.uptoMin,
    noCredit: f.noCredit,
    bpm: f.bpm,
    style: $('#styleFilter').value,
    text: $('#descSearch').value.trim(),
  };
}

function renderStats(data) {
  const beats = data.results.filter((r) => r.isBeat);
  const lic = new Set(readForm().licenses);
  const misleading = beats.filter((r) => r.license.misleading).length;
  const tiles = CATEGORY_ORDER.map((c) => {
    const n = data.stats.counts[c] || 0;
    return h('button', {
      type: 'button',
      class: `stat cat-${c}${lic.has(c) && !onlyMisleading ? '' : ' off'}`,
      title: lic.has(c) ? 'Cliquer pour masquer' : 'Cliquer pour afficher',
      onclick: () => {
        onlyMisleading = false;
        const box = $(`input[name=lic][value=${c}]`);
        box.checked = !box.checked;
        syncLicenseUi();
        updatePreview();
        renderResults();
      },
    }, h('b', {}, n), h('span', {}, `${GROUP_ICON[c]} ${CATEGORIES[c].label}`));
  });
  if (misleading) {
    tiles.push(h('button', {
      type: 'button',
      class: `stat cat-warn${onlyMisleading ? '' : ' off'}`,
      title: 'Titre « free for profit » mais la description demande de payer pour Spotify',
      onclick: () => { onlyMisleading = !onlyMisleading; renderResults(); },
    }, h('b', {}, misleading), h('span', {}, '⚠️ Titres trompeurs')));
  }
  $('#stats').replaceChildren(...tiles);
}

function renderResults() {
  const data = lastResponse;
  if (!data) return;
  const out = $('#results');
  $('#empty').hidden = true;
  $('#resultsHead').hidden = false;

  // Filtre « style » : options issues des résultats
  const styleSel = $('#styleFilter');
  const prevStyle = styleSel.value;
  const styles = stylesIn(data.results.filter((r) => r.isBeat));
  styleSel.replaceChildren(h('option', { value: '' }, 'Tous'), ...styles.map((s) => h('option', { value: s.id }, `${s.label} (${s.count})`)));
  styleSel.value = styles.some((s) => s.id === prevStyle) ? prevStyle : '';

  const f = currentFilters();
  let filtered = filterResults(data.results, f);
  if (onlyMisleading) filtered = filtered.filter((r) => r.license.misleading);
  const sorted = sortResults(filtered, $('#sort').value);
  const groups = groupByCategory(sorted);
  const terms = f.text ? parseTextQuery(f.text).include : [];

  renderStats(data);
  const quickOn = new Set($('#descSearch').value.split(/\s+/));
  $$('#quickTerms .chip').forEach((c) => c.classList.toggle('on', quickOn.has(c.dataset.term)));

  const st = data.stats;
  const hidden = data.results.filter((r) => r.isBeat).length - filtered.length;
  $('#count').replaceChildren(
    h('b', {}, `${filtered.length} prod(s)`),
    ` · ${st.analysed} vidéos lues via ${data.sourceLabel || data.source} en ${(st.ms / 1000).toFixed(1)} s`,
    hidden > 0 ? ` · ${hidden} masquée(s) par tes filtres` : '',
    st.notBeats ? ` · ${st.notBeats} hors-sujet écartée(s)` : '',
  );
  renderPlan($('#planUsedBody'), data.plan, true);

  out.replaceChildren();
  if (!groups.length) {
    out.append(h('div', { class: 'nores' }, h('div', { style: 'font-size:34px' }, '🫥'), h('h3', {}, 'Aucune prod avec ces filtres'),
      h('p', {}, f.text ? `Rien ne contient « ${f.text} » dans sa description. ` : '', 'Clique sur une catégorie en haut, élargis la plage BPM ou relance en profondeur « approfondie ».')));
    return;
  }
  for (const g of groups) {
    const cat = CATEGORIES[g.category];
    out.append(h('section', { class: `group cat-${g.category}` },
      h('div', { class: 'group-head' },
        h('span', { class: 'gico' }, GROUP_ICON[g.category]),
        h('div', {}, h('h2', {}, cat.label, h('small', {}, g.items.length)), h('p', {}, cat.help))),
      h('div', { class: 'grid' }, g.items.map((r) => renderCard(r, { bpmRange: data.plan.bpmRange, terms })))));
  }
}

function getSaved() { return store.get('saved', []); }
function isSaved(id) { return getSaved().some((r) => r.id === id); }
function toggleSaved(r) {
  const list = getSaved();
  const next = isSaved(r.id) ? list.filter((x) => x.id !== r.id) : [{ ...r, savedAt: new Date().toISOString() }, ...list].slice(0, 200);
  store.set('saved', next);
  updateFavCount();
  return isSaved(r.id);
}

function renderCard(r, { bpmRange = null, terms = [] } = {}) {
  const L = r.license;
  const card = h('article', { class: `card cat-${L.category}${L.misleading ? ' misleading' : ''}` });

  // Vignette (PC : lecteur intégré ; mobile : ouvre YouTube / l'appli)
  const thumb = h('div', { class: 'thumb', title: r.url ? 'Écouter' : '' });
  if (r.thumbnail) thumb.append(h('img', { src: r.thumbnail, alt: '', loading: 'lazy' }));
  else thumb.append(h('div', { class: 'ph' }, h('div', {}, r.styles[0]?.label || 'Type beat', r.demo ? h('small', {}, 'prod de démo') : null)));
  thumb.append(h('span', { class: 'ribbon' }, L.label));
  if (r.duration) thumb.append(h('span', { class: 'dur' }, fmtDuration(r.duration)));
  if (r.url) thumb.append(h('span', { class: 'play' }));
  const play = () => {
    if (!r.url) return toast('Prod de démo : pas de vidéo à lire');
    if (device === 'mobile') return window.open(r.url, '_blank', 'noopener');
    if ($('iframe', thumb)) return;
    thumb.replaceChildren(h('iframe', {
      src: `https://www.youtube-nocookie.com/embed/${encodeURIComponent(r.id)}?autoplay=1`,
      allow: 'autoplay; encrypted-media; picture-in-picture',
      allowfullscreen: true,
      title: r.title,
    }));
  };
  thumb.addEventListener('click', play);
  card.append(thumb);

  const body = h('div', { class: 'card-body' });
  const dots = { haute: 3, moyenne: 2, faible: 1 }[L.confidence] || 1;
  body.append(h('div', { class: 'verdict' }, verdictText(L),
    h('span', { class: 'conf', title: `Confiance de l’algo : ${L.confidence}` }, h('span', { class: 'conf-dots' }, [1, 2, 3].map((i) => h('i', { class: i <= dots ? 'on' : null }))))));
  body.append(h('h3', { class: 'title', title: r.title }, r.url ? h('a', { href: r.url, target: '_blank', rel: 'noopener' }, r.title) : r.title));
  body.append(h('div', { class: 'meta' }, [r.channel, r.views != null ? `${formatCount(r.views)} vues` : null, r.publishedText || fmtDate(r.publishedAt)].filter(Boolean).join(' · ')));

  if (L.misleading) {
    body.append(h('div', { class: 'alert' }, h('span', {}, '⚠️'), h('span', {}, h('b', {}, 'Titre trompeur. '), 'Le titre dit « free for profit », mais la description demande de payer pour sortir le son sur Spotify.')));
  }

  const badges = h('div', { class: 'badges' });
  if (r.bpm) {
    const inRange = bpmRange && r.bpm >= bpmRange.min && r.bpm <= bpmRange.max;
    badges.append(h('span', { class: `badge bpm${inRange ? ' in' : ''}`, title: inRange ? 'Dans la plage BPM conseillée' : 'BPM' }, `${r.bpm} BPM`));
  }
  if (r.key) badges.append(h('span', { class: 'badge' }, `🎹 ${r.key}`));
  if (L.creditRequired) badges.append(h('span', { class: 'badge credit' }, '✍️ Crédit obligatoire'));
  for (const s of r.styles || []) badges.append(h('span', { class: 'badge' }, s.label));
  if (badges.childNodes.length) body.append(badges);

  // Infos clés lues dans la description
  const lines = r.keyLines || [];
  if (lines.length) {
    body.append(h('ul', { class: 'keyinfo' },
      h('li', { class: 'keyinfo-title' }, '📋 Lu dans la description'),
      lines.slice(0, 5).map((l) => h('li', { class: l.type }, h('i', {}, KEYLINE_ICON[l.type] || '•'), h('span', {}, highlight(l.text, terms))))));
  } else if (!r.description) {
    body.append(h('div', { class: 'muted' }, 'Description vide.'));
  }
  card.append(body);

  // Actions
  const saveBtn = h('button', { type: 'button', class: `act${isSaved(r.id) ? ' on' : ''}`, title: 'Sauvegarder la prod' }, '💾', h('span', {}, isSaved(r.id) ? 'Gardée' : 'Garder'));
  saveBtn.addEventListener('click', () => {
    const on = toggleSaved(r);
    saveBtn.classList.toggle('on', on);
    $('span', saveBtn).textContent = on ? 'Gardée' : 'Garder';
    toast(on ? 'Prod sauvegardée dans Favoris' : 'Prod retirée');
  });
  const details = h('div', { class: 'details', hidden: true });
  const detailBtn = h('button', { type: 'button', class: 'act', title: 'Pourquoi cette catégorie ?' }, 'ℹ️', h('span', {}, 'Pourquoi'));
  detailBtn.addEventListener('click', () => {
    details.hidden = !details.hidden;
    detailBtn.classList.toggle('on', !details.hidden);
    if (!details.hidden && !details.childNodes.length) fillDetails(details, r, terms);
  });
  card.append(h('div', { class: 'actions' },
    h('button', { type: 'button', class: 'act', onclick: play, title: 'Écouter' }, '▶', h('span', {}, 'Écouter')),
    detailBtn,
    saveBtn,
    r.url ? h('button', {
      type: 'button',
      class: 'act',
      title: 'Copier le lien',
      onclick: async () => {
        try { await navigator.clipboard.writeText(r.url); toast('Lien copié'); } catch { window.prompt('Lien :', r.url); }
      },
    }, '🔗', h('span', {}, 'Lien')) : null,
  ));
  card.append(details);
  return card;
}

function fillDetails(box, r, terms) {
  const L = r.license;
  box.append(h('ul', { class: 'reasons' }, L.reasons.map((x) => h('li', {}, x.text, x.quote ? h('q', {}, highlight(x.quote, terms)) : null))));
  box.append(h('div', { class: 'found' },
    r.foundBy?.length ? `Trouvée via : ${r.foundBy.map((q) => `« ${q} »`).join(', ')}` : '',
    r.fullDescription === false ? ' · ⚠️ description partielle' : ' · ✔ description complète lue'));
  const pre = h('pre', {});
  pre.append(highlight(r.description || '(description vide)', terms));
  box.append(h('details', { class: 'desc', open: terms.length ? true : null }, h('summary', {}, 'Description complète'), pre));
}

// ---------------------------------------------------------------------------
// Historique & favoris

function getHistory() { return store.get('history', []); }
function setHistory(list) { store.set('history', list.slice(0, 150)); updateFavCount(); }

function saveHistory(f, data, existingId) {
  const list = getHistory();
  const beats = data.results.filter((r) => r.isBeat);
  const entry = {
    id: existingId || `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`,
    date: new Date().toISOString(),
    form: f,
    device,
    source: data.source,
    queries: data.plan.queries.map((q) => q.q),
    genres: data.plan.genres.map((g) => g.label),
    artists: data.plan.artists.map((a) => a.name),
    moods: data.plan.moods.map((m) => m.label),
    bpmRange: data.plan.bpmRange,
    counts: data.stats.counts,
    misleading: beats.filter((r) => r.license.misleading).length,
    total: beats.length,
  };
  const old = list.find((x) => x.id === existingId);
  if (old) {
    entry.favorite = old.favorite;
    entry.name = old.name;
    entry.runs = (old.runs || 1) + 1;
  }
  setHistory([entry, ...list.filter((x) => x.id !== entry.id)]);
  return entry.id;
}

function updateEntry(id, patch) {
  setHistory(getHistory().map((x) => (x.id === id ? { ...x, ...patch } : x)));
}

function entryTitle(e) {
  return e.name || e.form.prompt || e.form.manualQuery || 'Recherche sans titre';
}

function licenseSummary(f) {
  return (f.licenses || []).map((l) => (l === 'upto' && f.uptoMin ? `Up to ≥ ${formatCount(f.uptoMin)}` : CATEGORIES[l]?.label)).join(' + ') || 'toutes licences';
}

function relaunch(e) {
  writeForm(e.form);
  showView('search');
  runSearch(e.form, { fromHistoryId: e.id });
}

function renderEntry(e, { onChange }) {
  const star = h('button', {
    class: `star${e.favorite ? ' on' : ''}`,
    title: e.favorite ? 'Retirer des favoris' : 'Mettre en favori',
    'aria-label': 'Favori',
    onclick: () => { updateEntry(e.id, { favorite: !e.favorite }); toast(e.favorite ? 'Retirée des favoris' : 'Ajoutée aux favoris'); onChange(); },
  }, '⭐');
  return h('div', { class: 'hist' },
    h('div', { class: 'hist-top' },
      star,
      h('div', { class: 'hist-title' }, entryTitle(e)),
      h('div', { class: 'hist-date' }, new Date(e.date).toLocaleString('fr-FR', { dateStyle: 'short', timeStyle: 'short' }), e.device === 'mobile' ? ' · 📱' : ' · 💻'),
    ),
    h('div', { class: 'tags' },
      ...(e.moods || []).map((m) => h('span', { class: 'tag' }, m)),
      ...(e.genres || []).map((g) => h('span', { class: 'tag genre' }, g)),
      ...(e.artists || []).map((a) => h('span', { class: 'tag artist' }, a)),
    ),
    h('div', { class: 'hist-meta' },
      h('span', {}, licenseSummary(e.form)),
      ...CATEGORY_ORDER.filter((c) => e.counts?.[c]).map((c) => h('span', { class: `c cat-${c}` }, `${GROUP_ICON[c]} ${e.counts[c]}`)),
      e.misleading ? h('span', { class: 'c cat-warn' }, `⚠️ ${e.misleading} trompeur(s)`) : null,
      h('span', {}, `BPM ${e.bpmRange?.min}–${e.bpmRange?.max}`),
      e.form.bpm?.enabled ? h('span', {}, `filtre ${e.form.bpm.min || '…'}–${e.form.bpm.max || '…'} BPM`) : null,
      e.runs > 1 ? h('span', {}, `relancée ${e.runs}×`) : null,
    ),
    h('div', { class: 'hist-queries' }, h('span', {}, 'Recherches utilisées :'), ...e.queries.map((q) => h('code', {}, q))),
    h('div', { class: 'hist-actions' },
      h('button', { class: 'primary', onclick: () => relaunch(e) }, '↻ Relancer'),
      h('button', { class: 'mini', onclick: () => { writeForm(e.form); showView('search'); $('#searchForm').classList.remove('collapsed'); } }, '✏️ Modifier'),
      e.favorite ? h('button', {
        class: 'mini',
        onclick: () => {
          const name = window.prompt('Nom du favori :', entryTitle(e));
          if (name != null) { updateEntry(e.id, { name: name.trim() || undefined }); onChange(); }
        },
      }, '🏷️ Renommer') : null,
      h('button', { class: 'mini danger', onclick: () => { setHistory(getHistory().filter((x) => x.id !== e.id)); onChange(); } }, '🗑️ Supprimer'),
    ),
  );
}

function renderHistory() {
  const list = getHistory();
  $('#historyList').replaceChildren(...(list.length
    ? list.map((e) => renderEntry(e, { onChange: renderHistory }))
    : [h('div', { class: 'empty-list' }, '🕘 Pas encore de recherche. Tes demandes apparaîtront ici avec les requêtes utilisées.')]));
}

function renderFavorites() {
  const list = getHistory().filter((e) => e.favorite);
  $('#favoritesList').replaceChildren(...(list.length
    ? list.map((e) => renderEntry(e, { onChange: renderFavorites }))
    : [h('div', { class: 'empty-list' }, '⭐ Aucun favori. Dans l’historique, clique sur l’étoile pour garder une recherche.')]));
  const saved = getSaved();
  $('#savedList').replaceChildren(...(saved.length
    ? saved.map((r) => renderCard(r))
    : [h('div', { class: 'empty-list' }, '💾 Aucune prod sauvegardée. Clique sur « Garder » sous une prod.')]));
}

function updateFavCount() {
  const n = getHistory().filter((e) => e.favorite).length + getSaved().length;
  const dot = $('#favCount');
  dot.hidden = !n;
  dot.textContent = n;
}

$('#clearHistory').addEventListener('click', () => {
  const favs = getHistory().filter((e) => e.favorite);
  if (confirm(`Effacer l’historique ?${favs.length ? ` Tes ${favs.length} favori(s) sont gardés.` : ''}`)) {
    setHistory(favs);
    renderHistory();
  }
});

// ---------------------------------------------------------------------------
// Réglages

$('#settingsBtn').addEventListener('click', async () => {
  const s = store.get('settings', {});
  $('#sourcePref').value = s.source || '';
  $('#apiKey').value = s.apiKey || '';
  $('#serverInfo').textContent = '';
  $('#settings').showModal();
  try {
    const st = await (await fetch('/api/status')).json();
    $('#serverInfo').textContent = st.demo
      ? 'ℹ️ Le serveur tourne en mode démo (MELOFINDS_DEMO=1).'
      : st.apiKey ? '✔ Le serveur a déjà une clé YouTube API.' : 'ℹ️ Le serveur n’a pas de clé API : recherche sans clé par défaut.';
  } catch { /* serveur injoignable */ }
});
$('#saveSettings').addEventListener('click', () => {
  store.set('settings', { source: $('#sourcePref').value, apiKey: $('#apiKey').value.trim() });
  toast('Réglages enregistrés');
});

// ---------------------------------------------------------------------------
// Démarrage

const DEFAULT_FORM = { prompt: '', licenses: ['ffp', 'upto'], uptoMin: 0, bpm: { enabled: false } };
applyTheme();
writeForm(store.get('lastForm', DEFAULT_FORM));
applyDevice();
updateFavCount();
const saveForm = () => store.set('lastForm', readForm());
window.addEventListener('pagehide', saveForm);
document.addEventListener('visibilitychange', () => { if (document.hidden) saveForm(); });
