import { test } from 'node:test';
import assert from 'node:assert/strict';
import { analyzeLicense, findStreamLimit } from '../src/core/license.js';
import { normalize } from '../src/core/text.js';

const cat = (t, d) => analyzeLicense(t, d).category;

test('free for profit explicite → ffp', () => {
  const r = analyzeLicense('[FREE] Lil Uzi Vert Type Beat | Free For Profit', 'FREE FOR PROFIT ✅ just credit (prod. nova) in the title');
  assert.equal(r.category, 'ffp');
  assert.equal(r.spotify, 'oui');
  assert.equal(r.creditRequired, true);
  assert.equal(r.confidence, 'haute');
});

test('police fantaisie 𝗙𝗥𝗘𝗘 𝗙𝗢𝗥 𝗣𝗥𝗢𝗙𝗜𝗧 reconnue', () => {
  assert.equal(normalize('𝗙𝗥𝗘𝗘 𝗙𝗢𝗥 𝗣𝗥𝗢𝗙𝗜𝗧'), 'free for profit');
  assert.equal(cat('Type beat', '𝗙𝗥𝗘𝗘 𝗙𝗢𝗥 𝗣𝗥𝗢𝗙𝗜𝗧'), 'ffp');
});

test('variantes : f4p, free 4 profit, usage commercial libre', () => {
  assert.equal(cat('Drill type beat', 'F4P just credit'), 'ffp');
  assert.equal(cat('Drill type beat', 'free 4 profit'), 'ffp');
  assert.equal(cat('Drill type beat', 'You can use this beat on Spotify and all platforms'), 'ffp');
  assert.equal(cat('Drill type beat', 'no need to buy, just credit me'), 'ffp');
  assert.equal(cat('Prod', 'Tu peux sortir le son sur Spotify sans payer'), 'ffp');
});

test('limite de streams → upto avec la valeur', () => {
  const r = analyzeLicense('(FREE) Ken Carson Type Beat', 'FREE FOR PROFIT up to 5,000 streams. After that purchase a lease.');
  assert.equal(r.category, 'upto');
  assert.equal(r.limit, 5000);
  assert.equal(r.limitUnit, 'streams');
  assert.equal(r.label, 'Up to 5K streams');
  assert.equal(r.spotify, 'limité');
});

test('formats de limite variés', () => {
  const lim = (s) => findStreamLimit(normalize(s))?.value;
  assert.equal(lim('free for profit (100k streams max)'), 100000);
  assert.equal(lim("jusqu'à 10 000 écoutes"), 10000);
  assert.equal(lim('after 50k streams you must buy'), 50000);
  assert.equal(lim('ffp 1.5m streams'), 1500000);
  assert.equal(lim('limited to 2.000 plays'), 2000);
  assert.equal(lim('free for profit 100%'), undefined);
});

test('paliers de lease payants ne sont pas des limites gratuites', () => {
  const r = analyzeLicense('[FREE] Pop Smoke Type Beat', 'Free for non-profit use only.\nMP3 Lease $29.99 - up to 10,000 streams\nWAV Lease $49.99 - up to 50k streams');
  assert.equal(r.category, 'fnp');
  assert.equal(r.limit, null);
});

test('free for non-profit / il faut acheter pour Spotify → fnp', () => {
  assert.equal(cat('[FREE] Gunna Type Beat', 'Free for non-profit only. For profit use, you must purchase a lease'), 'fnp');
  assert.equal(cat('[FREE] beat', 'free for youtube only'), 'fnp');
  assert.equal(cat('[FREE] beat', 'Gratuit pour usage non commercial'), 'fnp');
});

test('« free for profit » contredit par une obligation d’achat → écarté de FFP', () => {
  const r = analyzeLicense('(FREE) Drill Type Beat', 'Free for profit but you need to buy a license to release on Spotify and Apple Music.');
  assert.equal(r.category, 'fnp');
  assert.equal(r.reasons.length >= 2, true);
});

test('négation explicite : Free for profit ❌', () => {
  assert.equal(cat('[FREE] Gunna Type Beat', 'Free for profit ❌ (must buy lease)'), 'fnp');
  assert.equal(cat('Gunna Type Beat', 'This beat is NOT free for profit'), 'fnp');
});

test('FREE seul sans précision → non-profit (confiance faible)', () => {
  const r = analyzeLicense('[FREE] Rod Wave Type Beat', 'Download link below');
  assert.equal(r.category, 'fnp');
  assert.equal(r.confidence, 'faible');
});

test('payant : lien beatstars / prix / SOLD', () => {
  assert.equal(cat('Future Type Beat "Toxic"', 'Buy this beat: https://beatstars.com/x | Leases from $25'), 'paid');
  assert.equal(cat('Lil Durk Type Beat (SOLD)', 'gone'), 'paid');
});

test('rien de clair → unknown', () => {
  assert.equal(cat('Lil Uzi Vert - Just Wanna Rock (Official Video)', 'Stream the album now'), 'unknown');
});

test('les raisons citent l’extrait original de la description', () => {
  const r = analyzeLicense('Beat', 'Intro\nFREE FOR PROFIT up to 10k streams\nOutro');
  assert.ok(r.reasons.some((x) => x.quote.includes('FREE FOR PROFIT up to 10k streams')));
});
