import { test } from 'node:test';
import assert from 'node:assert/strict';
import { quotedName, producersOf, usedByQueries, isBeatUpload, rateHit, pickHits, usedVerdict, usedByLinks } from '../src/core/usedby.js';

const PROD = { id: 'abcdefghijk', title: '[FREE] Ninho x Tiakola Type Beat "Lune" (prod. Orin)', channel: 'Orin Beats' };

test('nom de la prod et beatmaker', () => {
  assert.equal(quotedName(PROD.title), 'Lune');
  assert.equal(quotedName('[FREE] Ninho Type Beat 2026'), '');
  assert.equal(quotedName('Gazo Type Beat "FREE"'), '');
  assert.deepEqual(producersOf(PROD), ['Orin']);
  assert.deepEqual(producersOf({ title: 'Jul Type Beat "Soleil"', channel: 'KDB Music' }), ['KDB']);
  assert.deepEqual(producersOf({ title: 'Lucki Type Beat "Haze" | prod by kxvi & lowkey', channel: 'kxvi' }), ['kxvi & lowkey', 'kxvi']);
});

test('recherches', () => {
  assert.deepEqual(usedByQueries(PROD), ['Lune prod Orin', '"Lune" Orin', 'prod. Orin', 'prod by Orin']);
  // pas de nom entre guillemets : on cherche les sons qui créditent le beatmaker
  assert.deepEqual(usedByQueries({ title: 'Ninho Type Beat 2026', channel: 'Orin' }), ['prod. Orin', 'prod by Orin']);
  assert.deepEqual(usedByQueries({ title: '', channel: '' }), []);
});

test('les prods, tutos et kits ne sont pas des sons posés dessus', () => {
  for (const t of ['[FREE] Ninho Type Beat "Lune"', 'Lune - Instrumental', 'Lune (prod. Orin) | free for profit', 'How I made "Lune" for Ninho in FL Studio', 'Lune 140 BPM', 'Cooking up "Lune"', 'Orin Drum Kit 2026', 'Lune (Remake)']) {
    assert.equal(isBeatUpload(t), true, t);
  }
  for (const t of ['Ninho - Lune (Clip officiel)', 'Rappeur X - Lune (prod. Orin)', 'Freestyle Lune']) assert.equal(isBeatUpload(t), false, t);
});

test('tri des résultats', () => {
  const beat = { id: PROD.id, name: 'Lune', producers: ['Orin'], channel: 'Orin Beats' };
  const r = (title, extra = {}) => rateHit({ service: 'yt', id: 'zzzzzzzzzzz', title, uploader: 'Rappeur X', duration: 180, ...extra }, beat);
  assert.equal(r('Rappeur X - Lune (prod. Orin)').level, 'strong');
  assert.equal(r('Rappeur X - Nuit (prod. Orin)').level, 'credit');
  assert.equal(r('Rappeur X - Lune').level, 'name');
  assert.equal(r('Rappeur X - Soleil'), null);
  // « Lune » dans « Lunettes » : pas le nom
  assert.equal(r('Rappeur X - Lunettes'), null);
  // la prod elle-même, une autre de ses prods, le beatmaker qui poste : écartés
  assert.equal(r('Rappeur X - Lune (prod. Orin)', { id: PROD.id }), null);
  assert.equal(r('Ninho Type Beat "Lune 2" (prod. Orin)'), null);
  assert.equal(r('Lune (prod. Orin) snippet', { uploader: 'Orin Beats' }), null);
  // un mix d'une heure, un extrait de 20 s : écartés
  assert.equal(r('Rappeur X - Lune (prod. Orin)', { duration: 3600 }), null);
  assert.equal(r('Rappeur X - Lune (prod. Orin)', { duration: 20 }), null);
  // durée inconnue : gardé
  assert.equal(r('Rappeur X - Lune (prod. Orin)', { duration: -1 }).level, 'strong');
});

test('choix et ordre : les plus sûrs d’abord, sans doublon', () => {
  const items = [
    { service: 'yt', id: 'a1aaaaaaaaa', title: 'Rappeur A - Lune', uploader: 'Rappeur A', duration: 170, views: 9000 },
    { service: 'yt', id: 'b1bbbbbbbbb', title: 'Rappeur B - Lune (prod. Orin)', uploader: 'Rappeur B', duration: 150, views: 300 },
    { service: 'sc', url: 'https://soundcloud.com/rappeur-b/lune', title: 'Rappeur B - Lune (prod. Orin)', uploader: 'Rappeur B', duration: 150 },
    { service: 'yt', id: 'c1ccccccccc', title: '[FREE] Type Beat "Lune"', uploader: 'Autre', duration: 150 },
    { service: 'yt', id: 'd1ddddddddd', title: 'Rappeur C - Nuit (prod. Orin)', uploader: 'Rappeur C', duration: 200, views: 50000 },
  ];
  const got = pickHits(items, PROD);
  assert.deepEqual(got.map((x) => `${x.service}:${x.id || x.url}:${x.level}`), ['yt:b1bbbbbbbbb:strong', 'yt:d1ddddddddd:credit', 'yt:a1aaaaaaaaa:name']);
  assert.deepEqual(pickHits('rien', PROD), []);
});

test('ce qui s’affiche selon le son', () => {
  assert.equal(usedVerdict('name', { status: 'ok', same: true }), 'same');
  assert.equal(usedVerdict('credit', { status: 'ok', same: false }), null);
  assert.equal(usedVerdict('name', { status: 'fail' }), null);
  assert.equal(usedVerdict('strong', { status: 'ok', same: false }), 'differs');
  assert.equal(usedVerdict('strong', { status: 'noaudio' }), 'text');
  assert.equal(usedVerdict('strong', null), 'text');
});

test('liens de recherche pour le site', () => {
  const l = usedByLinks(PROD);
  assert.deepEqual(l.map((x) => x.label), ['YouTube', 'SoundCloud', 'Spotify']);
  assert.ok(l[0].url.endsWith('search_query=Lune%20prod%20Orin'));
  assert.deepEqual(usedByLinks({ title: '' }), []);
});
