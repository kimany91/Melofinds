import { test } from 'node:test';
import assert from 'node:assert/strict';
import { beatName, tbQueries, tbKey, tbPick, similarity } from '../src/core/tunebat.js';

// Résultats au format de l'API Tunebat (n = titre, as = artistes, d = durée en ms, k = clé, b = BPM)
const ITEMS = [
  { n: 'COLD', as: ['Nemzzz'], d: 160000, k: 'A♯ minor', b: 142 },
  { n: 'NEMZZZ TYPE BEAT', as: ['Nemzzz'], d: 173000, k: 'D major', b: 145 },
  { n: 'Haze', as: ['Kxvi Beats'], d: 151000, k: 'C♯ Minor', b: 150.2 },
  { n: 'Haze', as: ['Someone Else'], d: 200000, k: 'E minor', b: 90 },
];

test('nom de la prod et recherches', () => {
  assert.equal(beatName('[FREE] Lucki Type Beat "Haze" | Free For Profit'), 'Haze');
  assert.equal(beatName('Lucki x Summrs Type Beat - “Nuit Blanche” (prod. kxvi)'), 'Nuit Blanche');
  assert.deepEqual(tbQueries({ title: '[FREE] Lucki Type Beat "Haze"', channel: 'Kxvi Beats' }), ['Haze Kxvi', 'Haze']);
});

test('clés Tunebat → format de l’app', () => {
  assert.equal(tbKey('A♯ minor'), 'A# min');
  assert.equal(tbKey('D Major'), 'D maj');
  assert.equal(tbKey('B♭ minor'), 'Bb min');
  assert.equal(tbKey('???'), null);
});

test('ne garde que le bon morceau', () => {
  const p = tbPick(ITEMS, { title: 'Lucki Type Beat "Haze"', channel: 'Kxvi Beats', duration: 152 });
  assert.deepEqual([p.key, p.bpm], ['C# min', 150]);
  // même titre, autre beatmaker et autre durée : refusé
  assert.equal(tbPick([ITEMS[3]], { title: 'Lucki Type Beat "Haze"', channel: 'Kxvi Beats', duration: 152 }), null);
  // sans chaîne : la durée identique suffit avec un titre proche
  assert.equal(tbPick(ITEMS, { title: 'NEMZZZ TYPE BEAT', channel: '', duration: 175 }).bpm, 145);
  // rien qui colle : null (pas de faux BPM)
  assert.equal(tbPick(ITEMS, { title: 'Pop Smoke Type Beat "Dior"', channel: 'Random', duration: 120 }), null);
  assert.equal(tbPick('pas une liste', { title: 'x' }), null);
  assert.ok(similarity('Kxvi Beats', 'kxvi beats') === 1);
});

// ReccoBeats (réponse réelle du 28/10/2026, recherche « nemzzz »)
import { rbKey, rbQueries, rbPick, rbFeatures } from '../src/core/tunebat.js';
const RB = [{ id: '7bb8c52a-9175-4332-98e3-0c69cbe74636', trackTitle: 'nemzzzjazz', artists: [{ name: 'prod. shrugg' }], durationMs: 132003, href: 'https://open.spotify.com/track/40dxP5R4cLCoIb752Ik5yb' },
  { id: 'autre', trackTitle: 'Jazz', artists: [{ name: 'Someone' }], durationMs: 200000 }];

test('ReccoBeats : clé, recherches, bon morceau seulement', () => {
  assert.equal(rbKey(7, 1), 'G maj');
  assert.equal(rbKey(10, 0), 'A# min');
  assert.equal(rbKey(-1, 1), null);
  assert.deepEqual(rbFeatures({ tempo: 140.214, key: 7, mode: 1 }), { bpm: 140, key: 'G maj' });
  assert.deepEqual(rbFeatures({ tempo: 300, key: -1, mode: 1 }), null);
  assert.deepEqual(rbQueries({ title: 'Nemzzz Type Beat "nemzzzjazz"', channel: 'shrugg beats' }), [{ searchText: 'nemzzzjazz', artist: 'shrugg' }, { searchText: 'nemzzzjazz' }]);
  // même beatmaker (« prod. shrugg ») et même titre
  assert.equal(rbPick(RB, { title: 'Nemzzz Type Beat "nemzzzjazz"', channel: 'shrugg' })?.id, RB[0].id);
  // même titre et même durée, chaîne inconnue
  assert.equal(rbPick(RB, { title: '[FREE] "nemzzzjazz"', channel: '', duration: 133 })?.id, RB[0].id);
  // autre beatmaker, autre durée : rien (mieux vaut « BPM ? » qu'un faux BPM)
  assert.equal(rbPick(RB, { title: 'Nemzzz Type Beat "nemzzzjazz"', channel: 'geesyn', duration: 90 }), null);
  assert.equal(rbPick(RB, { title: 'Type beat "jazz"', channel: 'geesyn' }), null);
});
