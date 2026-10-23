import { buildPlan, defaultDepth, DEPTHS } from '/core/planner.js';
import { filterResults, sortResults, groupByCategory, stylesIn } from '/core/filter.js';
import { CATEGORIES, formatCount } from '/core/license.js';

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
// Stockage local (historique, favoris, réglages)

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

// ---------------------------------------------------------------------------
// Appareil : l'algo s'adapte (mise en page, nombre de requêtes, lecteur…)

function detectDevice() {
  const forced = store.get('device', '');
  if (forced === 'mobile' || forced === 'desktop') return forced;
  const ua = /Mobi|Android|iPhone|iPad|iPod/i.test(navigator.userAgent);
  const narrow = window.innerWidth < 760;
  return ua || narrow ? 'mobile' : 'desktop';
}

let device = detectDevice();
function applyDevice() {
  document.body.classList.toggle('mobile', device === 'mobile');
  document.body.classList.toggle('desktop', device === 'desktop');
  const forced = store.get('device', '');
  $('#deviceBadge').textContent = `${device === 'mobile' ? '📱 Mode mobile' : '💻 Mode PC'}${forced ? ' (forcé)' : ''}`;
  const auto = $('#depth option[value=""]');
  auto.textContent = `Auto (${DEPTHS[defaultDepth(device)].label.toLowerCase()} sur ${device === 'mobile' ? 'mobile' : 'PC'})`;
  updatePreview();
  if (lastResponse) renderResults();
}
$('#deviceBadge').addEventListener('click', () => {
  const forced = store.get('device', '');
  if (forced) store.set('device', '');
  else store.set('device', device === 'mobile' ? 'desktop' : 'mobile');
  device = detectDevice();
  applyDevice();
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

const SUGGESTIONS = ['rapide', 'énergique', 'musicale', 'sombre', 'triste', 'agressif', 'chill', 'planant', 'bouncy', 'old school', 'drill', 'rage', 'pluggnb', 'jerk', 'piano', 'guitare', 'Lil Uzi', 'Pop Smoke', 'Travis Scott'];
const promptEl = $('#prompt');
const sugBox = $('#suggestions');
for (const s of SUGGESTIONS) {
  sugBox.append(h('button', {
    type: 'button',
    class: 'chip',
    onclick: () => {
      const cur = promptEl.value.trim();
      const words = cur.toLowerCase().split(/[\s,]+/);
      if (words.includes(s.toLowerCase())) {
        promptEl.value = cur.replace(new RegExp(`(^|,?\\s*)${s}(?=,|\\s|$)`, 'i'), '').replace(/^[,\s]+/, '');
      } else {
        promptEl.value = cur ? `${cur}, ${s}` : s;
      }
      updatePreview();
      syncSuggestionState();
    },
  }, s));
}
function syncSuggestionState() {
  const lower = promptEl.value.toLowerCase();
  $$('.chip', sugBox).forEach((c) => c.classList.toggle('on', lower.includes(c.textContent.toLowerCase())));
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
  $('#bpmBox').hidden = !f.bpm?.enabled;
  syncLicenseUi();
  syncSuggestionState();
  updatePreview();
}

function syncLicenseUi() {
  $('#uptoMinRow').hidden = !$('input[name=lic][value=upto]').checked;
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
  if ($('#bpmEnabled').checked && !$('#bpmMin').value && !$('#bpmMax').value) fillBpmFromPlan();
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
  box.append(sect('Courants de rap choisis',
    h('div', { class: 'tags' }, plan.genres.map((g) => h('span', { class: 'tag genre', title: g.why.join(', ') }, `${g.label} · ${g.bpm[0]}-${g.bpm[1]} BPM`)))));
  box.append(sect('Artistes US « type beat »',
    h('div', { class: 'tags' }, plan.artists.map((a) => h('span', { class: 'tag artist', title: a.reason }, a.name)))));
  box.append(sect('BPM conseillé', h('span', {}, `${plan.bpmRange.min}–${plan.bpmRange.max} BPM `), h('span', { class: 'why' }, `(${plan.bpmRange.source})`)));
  box.append(sect(`Requêtes YouTube (${plan.queries.length}) · profondeur ${plan.depth.label.toLowerCase()}${plan.device === 'mobile' ? ' (mobile)' : ''}`,
    h('ol', {}, plan.queries.map((q) => h('li', {},
      h('code', {}, q.q), ' ',
      h('span', { class: 'why' }, `← ${q.why}${withCounts && q.count != null ? ` · ${q.count} vidéo(s)` : ''}${q.error ? ` · ⚠️ ${q.error}` : ''}`),
    )))));
}

let previewTimer;
promptEl.addEventListener('input', () => { clearTimeout(previewTimer); previewTimer = setTimeout(() => { updatePreview(); syncSuggestionState(); }, 150); });
$('#manualQuery').addEventListener('input', () => { clearTimeout(previewTimer); previewTimer = setTimeout(updatePreview, 150); });
$('#depth').addEventListener('change', updatePreview);

// Les filtres de licence / BPM / crédit s'appliquent tout de suite aux résultats.
$$('input[name=lic]').forEach((i) => i.addEventListener('change', () => { syncLicenseUi(); updatePreview(); renderResults(); }));
$('#uptoMin').addEventListener('change', renderResults);
$('#noCredit').addEventListener('change', renderResults);
$('#bpmEnabled').addEventListener('change', () => {
  const on = $('#bpmEnabled').checked;
  $('#bpmBox').hidden = !on;
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

// ---------------------------------------------------------------------------
// Recherche

let lastResponse = null;
let lastHistoryId = null;

$('#searchForm').addEventListener('submit', (e) => {
  e.preventDefault();
  runSearch(readForm());
});

async function runSearch(f, { fromHistoryId = null, forceSource = null } = {}) {
  if (!f.prompt && !f.manualQuery) {
    showStatus('Écris d’abord une description (ex. « rapide, énergique et musicale ») ou une recherche directe.', 'error');
    promptEl.focus();
    return;
  }
  const plan = planFor(f);
  const btn = $('#goBtn');
  btn.disabled = true;
  btn.textContent = 'Recherche en cours…';
  showStatus(h('span', {}, h('span', { class: 'spinner' }), `Recherche de ${plan.queries.length} requête(s) sur YouTube et lecture des descriptions…`));
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
    hideStatus();
    if (data.warnings?.length) {
      showStatus(h('div', {}, h('b', {}, 'À savoir :'), h('ul', {}, data.warnings.map((w) => h('li', {}, w)))));
    }
    if (f.bpm.enabled && !f.bpm.min && !f.bpm.max) {
      $('#bpmMin').value = data.plan.bpmRange.min;
      $('#bpmMax').value = data.plan.bpmRange.max;
    }
    lastHistoryId = saveHistory(f, data, fromHistoryId);
    renderResults();
    if (device === 'mobile') {
      $('#searchForm').classList.add('collapsed');
      $('#resultsHead').scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  } catch (err) {
    const box = h('div', {},
      h('b', {}, '😕 La recherche a échoué : '), err.message,
      err.hint ? h('p', { class: 'muted' }, err.hint) : null,
      err.source !== 'demo' ? h('button', { type: 'button', class: 'chip', onclick: () => runSearch(f, { fromHistoryId, forceSource: 'demo' }) }, '🎲 Essayer en mode démo (prods fictives)') : null,
      ' ',
      h('button', { type: 'button', class: 'chip ghost', onclick: () => $('#settings').showModal() }, '⚙️ Ajouter une clé API'),
    );
    showStatus(box, 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = 'Chercher les prods';
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

function renderResults() {
  const data = lastResponse;
  const out = $('#results');
  if (!data) return;
  $('#empty').hidden = true;
  $('#resultsHead').hidden = false;
  const f = readForm();

  // Filtre « style » : options issues des résultats
  const styleSel = $('#styleFilter');
  const prevStyle = styleSel.value;
  const styles = stylesIn(data.results.filter((r) => r.isBeat));
  styleSel.replaceChildren(h('option', { value: '' }, 'Tous'), ...styles.map((s) => h('option', { value: s.id }, `${s.label} (${s.count})`)));
  styleSel.value = styles.some((s) => s.id === prevStyle) ? prevStyle : '';

  const filtered = filterResults(data.results, {
    licenses: f.licenses,
    uptoMin: f.uptoMin,
    noCredit: f.noCredit,
    bpm: f.bpm,
    style: styleSel.value,
  });
  const sorted = sortResults(filtered, $('#sort').value);
  const groups = groupByCategory(sorted);

  // Résumé
  const st = data.stats;
  const sum = $('#summary');
  sum.replaceChildren(
    h('span', {}, `${st.analysed} vidéos analysées (description complète lue) via `, h('b', {}, data.sourceLabel || data.source), ` en ${(st.ms / 1000).toFixed(1)} s`),
    ...Object.entries(st.counts).filter(([, n]) => n).map(([c, n]) => h('span', { class: `pill cat-${c}` }, `${CATEGORIES[c].label} : ${n}`)),
    st.notBeats ? h('span', { class: 'muted' }, `· ${st.notBeats} hors-sujet écartée(s) (pas des instrus)`) : null,
  );
  renderPlan($('#planUsedBody'), data.plan, true);
  const hidden = data.results.filter((r) => r.isBeat).length - filtered.length;
  $('#count').textContent = `${filtered.length} prod(s) affichée(s)${hidden > 0 ? ` · ${hidden} masquée(s) par tes filtres` : ''}`;

  out.replaceChildren();
  if (!groups.length) {
    out.append(h('div', { class: 'empty' }, h('div', { class: 'empty-art' }, '🫥'), h('h2', {}, 'Aucune prod avec ces filtres'),
      h('p', {}, 'Coche d’autres licences, élargis la plage BPM ou relance en profondeur « approfondie ».')));
    return;
  }
  const bpmRange = data.plan.bpmRange;
  for (const g of groups) {
    const cat = CATEGORIES[g.category];
    const grid = h('div', { class: 'grid' }, g.items.map((r) => renderCard(r, bpmRange)));
    out.append(h('section', { class: `group cat-${g.category}` },
      h('div', { class: 'group-head' }, h('h2', {}, `${cat.label} · ${g.items.length}`), h('p', {}, cat.help)),
      grid));
  }
}

function renderCard(r, bpmRange) {
  const card = $('#cardTpl').content.firstElementChild.cloneNode(true);
  card.classList.add(`cat-${r.license.category}`);
  const thumb = $('.thumb', card);
  const img = $('img', thumb);
  if (r.thumbnail) {
    img.src = r.thumbnail;
    img.alt = r.title;
  } else {
    img.remove();
    thumb.prepend(h('div', { class: 'placeholder' }, r.styles[0]?.label || 'Type beat', r.demo ? ' · démo' : ''));
  }
  $('.duration', thumb).textContent = fmtDuration(r.duration);

  // PC : lecteur intégré au clic. Mobile : ouvre YouTube (l'appli si installée).
  if (r.url) {
    if (device === 'desktop') {
      thumb.addEventListener('click', () => {
        thumb.replaceChildren(h('iframe', {
          src: `https://www.youtube-nocookie.com/embed/${r.id}?autoplay=1`,
          allow: 'autoplay; encrypted-media; picture-in-picture',
          allowfullscreen: true,
          title: r.title,
        }));
      }, { once: true });
    } else {
      thumb.addEventListener('click', () => window.open(r.url, '_blank', 'noopener'));
    }
  }

  const titleEl = $('.title', card);
  titleEl.append(r.url ? h('a', { href: r.url, target: '_blank', rel: 'noopener' }, r.title) : r.title);
  $('.meta', card).textContent = [r.channel, r.views != null ? `${formatCount(r.views)} vues` : null, r.publishedText || fmtDate(r.publishedAt)].filter(Boolean).join(' · ');

  const L = r.license;
  const badges = $('.badges', card);
  badges.append(h('span', { class: 'badge lic', title: CATEGORIES[L.category].help }, L.label));
  badges.append(h('span', { class: 'badge', title: 'Peut-on sortir le son sur Spotify sans payer ?' }, `Spotify : ${L.spotify}`));
  if (r.bpm) {
    const inRange = bpmRange && r.bpm >= bpmRange.min && r.bpm <= bpmRange.max;
    badges.append(h('span', { class: `badge bpm${inRange ? ' in' : ''}`, title: inRange ? 'Dans la plage BPM conseillée' : '' }, `${r.bpm} BPM`));
  }
  if (r.key) badges.append(h('span', { class: 'badge' }, `🎹 ${r.key}`));
  if (L.creditRequired) badges.append(h('span', { class: 'badge warn' }, 'Crédit obligatoire'));
  for (const s of r.styles) badges.append(h('span', { class: 'badge' }, s.label));
  badges.append(h('span', { class: 'badge conf', title: 'Confiance de l’algo dans la catégorie' }, `confiance ${L.confidence}`));

  $('.reasons', card).append(...L.reasons.map((x) => h('li', {}, x.text, x.quote ? h('q', {}, x.quote) : null)));
  $('.found', card).textContent = `Trouvée via : ${r.foundBy.map((q) => `« ${q} »`).join(', ')}${r.fullDescription ? '' : ' · ⚠️ description partielle'}`;
  $('.desc pre', card).textContent = r.description || '(description vide)';
  return card;
}

// ---------------------------------------------------------------------------
// Historique & favoris

function getHistory() { return store.get('history', []); }
function setHistory(list) { store.set('history', list.slice(0, 150)); }

function saveHistory(f, data, existingId) {
  const list = getHistory();
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
    total: data.results.filter((r) => r.isBeat).length,
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

function renderEntry(e, { onChange }) {
  const star = h('button', {
    class: `star${e.favorite ? ' on' : ''}`,
    title: e.favorite ? 'Retirer des favoris' : 'Mettre en favori',
    'aria-label': 'Favori',
    onclick: () => { updateEntry(e.id, { favorite: !e.favorite }); onChange(); },
  }, '⭐');
  return h('div', { class: 'hist' },
    h('div', { class: 'hist-top' },
      star,
      h('div', { class: 'hist-title' }, entryTitle(e)),
      h('div', { class: 'hist-date' }, new Date(e.date).toLocaleString('fr-FR', { dateStyle: 'short', timeStyle: 'short' }), e.device === 'mobile' ? ' 📱' : ' 💻'),
    ),
    h('div', { class: 'tags' },
      ...(e.moods || []).map((m) => h('span', { class: 'tag' }, m)),
      ...(e.genres || []).map((g) => h('span', { class: 'tag genre' }, g)),
      ...(e.artists || []).map((a) => h('span', { class: 'tag artist' }, a)),
    ),
    h('div', { class: 'muted' },
      `${licenseSummary(e.form)} · ${e.total} prod(s) · BPM conseillé ${e.bpmRange?.min}–${e.bpmRange?.max}`,
      e.form.bpm?.enabled ? ` · filtre BPM ${e.form.bpm.min || '…'}–${e.form.bpm.max || '…'}` : '',
      e.runs > 1 ? ` · relancée ${e.runs} fois` : ''),
    h('div', { class: 'hist-queries' }, 'Recherches utilisées : ', ...e.queries.map((q) => h('code', {}, q))),
    h('div', { class: 'hist-actions' },
      h('button', { class: 'chip', onclick: () => { writeForm(e.form); showView('search'); runSearch(e.form, { fromHistoryId: e.id }); } }, '↻ Relancer'),
      h('button', { class: 'chip ghost', onclick: () => { writeForm(e.form); showView('search'); $('#searchForm').classList.remove('collapsed'); } }, '✏️ Modifier'),
      e.favorite ? h('button', {
        class: 'chip ghost',
        onclick: () => {
          const name = prompt('Nom du favori :', entryTitle(e));
          if (name != null) { updateEntry(e.id, { name: name.trim() || undefined }); onChange(); }
        },
      }, '🏷️ Renommer') : null,
      h('button', { class: 'chip ghost danger', onclick: () => { setHistory(getHistory().filter((x) => x.id !== e.id)); onChange(); } }, '🗑️'),
    ),
  );
}

function renderHistory() {
  const box = $('#historyList');
  const list = getHistory();
  box.replaceChildren(...(list.length
    ? list.map((e) => renderEntry(e, { onChange: renderHistory }))
    : [h('p', { class: 'muted' }, 'Pas encore de recherche. Tes demandes apparaîtront ici avec les requêtes utilisées.')]));
}

function renderFavorites() {
  const box = $('#favoritesList');
  const list = getHistory().filter((e) => e.favorite);
  box.replaceChildren(...(list.length
    ? list.map((e) => renderEntry(e, { onChange: renderFavorites }))
    : [h('p', { class: 'muted' }, 'Aucun favori. Dans l’historique, clique sur ⭐ pour garder une recherche et la relancer en un clic.')]));
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

const dlg = $('#settings');
$('#settingsBtn').addEventListener('click', async () => {
  const s = store.get('settings', {});
  $('#sourcePref').value = s.source || '';
  $('#apiKey').value = s.apiKey || '';
  try {
    const st = await (await fetch('/api/status')).json();
    $('#serverInfo').textContent = st.demo
      ? 'Le serveur tourne en mode démo (MELOFINDS_DEMO=1).'
      : st.apiKey ? 'Le serveur a déjà une clé YouTube API configurée.' : 'Le serveur n’a pas de clé API : recherche sans clé par défaut.';
  } catch {
    $('#serverInfo').textContent = '';
  }
  dlg.showModal();
});
$('#saveSettings').addEventListener('click', () => {
  store.set('settings', { source: $('#sourcePref').value, apiKey: $('#apiKey').value.trim() });
});

// ---------------------------------------------------------------------------
// Démarrage

const DEFAULT_FORM = { prompt: '', licenses: ['ffp', 'upto'], uptoMin: 0, bpm: { enabled: false } };
writeForm(store.get('lastForm', DEFAULT_FORM));
applyDevice();
window.addEventListener('beforeunload', () => store.set('lastForm', readForm()));
document.addEventListener('visibilitychange', () => { if (document.hidden) store.set('lastForm', readForm()); });
