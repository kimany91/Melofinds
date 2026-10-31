import { test } from 'node:test';
import assert from 'node:assert/strict';
import { findArtists, suggestArtists, ARTIST_COUNT } from '../src/core/artistmatch.js';
import { FR_ARTISTS } from '../src/core/frartists.js';
import { GENRES, GENRE_BY_ID } from '../src/core/genres.js';
import { buildPlan } from '../src/core/planner.js';

const names = (t) => findArtists(t).map((m) => m.name);

test('grosse base : ≥150 rappeurs FR, ≥35 courants, ≥200 artistes US', () => {
  assert.ok(ARTIST_COUNT.fr >= 150, `FR ${ARTIST_COUNT.fr}`);
  assert.ok(GENRES.length >= 35);
  assert.ok(ARTIST_COUNT.us >= 200, `US ${ARTIST_COUNT.us}`);
});

test('chaque rappeur FR pointe vers des courants et des artistes US connus', () => {
  const us = new Set(GENRES.flatMap((g) => g.artists));
  for (const a of FR_ARTISTS) {
    assert.ok(a.styles.length, a.name);
    for (const s of a.styles) assert.ok(GENRE_BY_ID[s], `${a.name} → courant inconnu ${s}`);
    for (const u of a.us) assert.ok(us.has(u), `${a.name} → artiste US inconnu ${u}`);
  }
});

test('reconnaît les rappeurs FR cités, même mal écrits', () => {
  assert.deepEqual(names('une prod à la luther'), ['Luther']);
  assert.deepEqual(names('Damso'), ['Damso']);
  assert.deepEqual(names('bu$hi'), ['Bu$hi']);
  assert.deepEqual(names('bushi x la feve'), ['Bu$hi', 'La Fève']);
  assert.deepEqual(names("jok'air"), ['Jok’Air']);
  assert.deepEqual(names('jok air mélodique'), ['Jok’Air']);
  assert.deepEqual(names('cœurco'), ['Coeurco']);
  assert.deepEqual(names('coeur co'), ['Coeurco']);
  assert.deepEqual(names('luv resval'), ['Luv Resval']);
  assert.deepEqual(names('freeze corlone'), ['Freeze Corleone']);
});

test('reconnaît les artistes US, même mal écrits', () => {
  assert.deepEqual(names('travis scot et pop smok'), ['Travis Scott', 'Pop Smoke']);
  assert.deepEqual(names('lil uzi x carti'), ['Lil Uzi Vert', 'Playboi Carti']);
});

test('ne prend pas des mots courants pour des rappeurs', () => {
  assert.deepEqual(names('une prod de feu rapide énergique'), []);
  assert.deepEqual(names('drill sombre 145 bpm'), []);
  assert.deepEqual(names('nos prods plugg avec du piano'), []);
  assert.deepEqual(names('juillet'), []);
});

test('autocomplétion', () => {
  assert.equal(suggestArtists('lut')[0].name, 'Luther');
  assert.equal(suggestArtists('dams')[0].name, 'Damso');
  assert.ok(suggestArtists('la f').some((s) => s.name === 'La Fève'));
});

test('« une prod à la Luther » : type beats Luther + US du même son + courants de Luther', () => {
  const p = buildPlan('une prod à la luther', { licenses: ['ffp'], device: 'desktop' });
  assert.equal(p.recognized[0].name, 'Luther');
  assert.equal(p.queries[0].q, 'Luther type beat free for profit');
  assert.ok(p.queries.some((q) => q.q.startsWith('Lucki type beat')));
  assert.ok(p.genres.some((g) => g.id === 'pluggnb'));
});

test('« Bu$hi » est cherché en « Bushi type beat »', () => {
  const p = buildPlan('bu$hi', { licenses: [], device: 'desktop' });
  assert.equal(p.queries[0].q, 'Bushi type beat');
});

test('nouvelle scène : GAL, LEDOUBLE, lucboy, LightBoy… reconnus et reliés aux bons courants', () => {
  assert.deepEqual(names('une prod à la gal'), ['GAL']);
  assert.deepEqual(names('ledouble x gal'), ['LEDOUBLE', 'GAL']);
  assert.deepEqual(names('le double'), ['LEDOUBLE']);
  assert.deepEqual(names('lucboy'), ['lucboy']);
  assert.deepEqual(names('light boy mélancolique'), ['LightBoy']);
  assert.deepEqual(names('lightbo'), ['LightBoy']);  // mal écrit
  assert.deepEqual(names('poisson chat et lushe'), ['poissonchat', 'Lushe']);
  const gal = FR_ARTISTS.find((a) => a.name === 'GAL');
  assert.ok(gal.styles.includes('griselda') && gal.us.includes('Roc Marciano'));
  const ld = FR_ARTISTS.find((a) => a.name === 'LEDOUBLE');
  assert.ok(ld.styles.includes('atl-classic') && ld.us.includes('Gucci Mane'));
  const p = buildPlan('une prod à la lucboy', { licenses: ['ffp'], device: 'desktop' });
  assert.equal(p.recognized[0].name, 'lucboy');
  assert.ok(p.queries.some((q) => /^lucboy type beat/i.test(q.q)));
});

test('les mots courants ne déclenchent pas les nouveaux noms', () => {
  assert.deepEqual(names('une prod qui tape grave'), []);
  assert.deepEqual(names('la galère légale'), []);
  assert.deepEqual(names('un poisson et un chat'), []);
  assert.deepEqual(names('enfant lumière'), []);
});
