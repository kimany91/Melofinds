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
