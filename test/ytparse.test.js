import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { parseResultsPage, cleanDescription, usefulDescription } from '../src/core/ytparse.js';
import { analyzeLicense } from '../src/core/license.js';

const fx = (n) => readFileSync(new URL(`./fixtures/${n}`, import.meta.url), 'utf8');

test('page de résultats YouTube réelle → vidéos avec titres exacts (pas « Now playing »)', () => {
  const list = parseResultsPage(fx('youtube-results-page.md'));
  assert.equal(list.length, 6);
  assert.deepEqual(list.map((v) => v.id), ['hWJOMF7o7gY', 'jXoQB_FW5VQ', 'yheXfiHiTFE', 'ykX7kHUoJbU', '6klhvgOGXog', 'WJKQAjkb_Ac']);
  assert.equal(list[1].title, '[FREE FOR PROFIT] Lil Uzi Vert Type Beat - "bankroll"');
  assert.equal(list[1].views, '369K');
  assert.equal(list[1].age, 'il y a 2 ans');
  assert.equal(list[3].title, '[FREE] Lil Uzi Vert Type Beat "Salute Me"');
  assert.ok(list.every((v) => !/now playing/i.test(v.title)));
});

test('page vidéo réelle → description propre, verdict Up to 5K', () => {
  const title = '[FREE FOR PROFIT] Lil Uzi Vert Type Beat - "bankroll"';
  const d = cleanDescription(fx('youtube-watch-bankroll.md'), title);
  assert.ok(usefulDescription(d));
  assert.ok(!d.includes('redir_token'));
  assert.ok(!/369K Views/.test(d));
  assert.ok(!d.includes(title), 'le titre ne doit pas compter comme une confirmation dans la description');
  const r = analyzeLicense(title, d);
  assert.equal(r.category, 'upto');
  assert.equal(r.limit, 5000);
});

test('page vidéo illisible (lecteur seulement) → détectée comme inutile', () => {
  const d = cleanDescription(fx('youtube-watch-chrome-only.md'), '[free for profit] lil uzi vert type beat - muffin');
  assert.equal(usefulDescription(d), false);
});

test('version mobile réelle : les vidéos suggérées ([SOLD]…, [FREE FOR PROFIT]…) sont retirées', () => {
  const title = '*free for profit* Lil Uzi Vert Type Beat - Skyline';
  const d = cleanDescription(readFileSync(new URL('./fixtures/youtube-watch-mobile-skyline.md', import.meta.url), 'utf8'), title);
  assert.ok(!/SOLD|Glo Up|Ascending|LITVILLE/.test(d), d);
  assert.ok(/dont need ya money/.test(d));
  const r = analyzeLicense(title, d);
  assert.equal(r.category, 'ffp');
  assert.equal(r.confidence, 'haute');
});

test('réel : « Maximum of 10.000 monetized streams… after that you have to buy a lease » → Up to 10K', () => {
  const r = analyzeLicense('(FREE FOR PROFIT) Juice WRLD x Lil Uzi Vert Type Beat "XO TOUR LIF3"',
    'BPM: 160 KEY: c This beat is FREE to use for ALL PLATFORMS including streaming services AS LONG AS YOU CREDIT ME and accept my terms when you use it. Maximum of 10.000 monetized streams/plays total on your song! after that you have to buy a lease! Must Credit (prod.');
  assert.equal(r.category, 'upto');
  assert.equal(r.limit, 10000);
  assert.equal(r.creditRequired, true);
});

test('réel : « can be used on all platforms including Spotify, as long as you give me credit » → FFP haute', () => {
  const r = analyzeLicense('(FREE FOR PROFIT) Lil Uzi Vert X Future Type Beat 2026 - "FREE LUCY" Free Type Beat',
    'Use it for whatever purpose you need, as long as you give me credit. My beats can be used on all platforms including Spotify, Apple Music, etc. (Prod. Yung Lexar) C♯ minor 150 BPM DOWNLOAD LINK:');
  assert.equal(r.category, 'ffp');
  assert.equal(r.confidence, 'haute');
  assert.equal(r.creditRequired, true);
});

test('pub YouTube « Credit Card » avant la vidéo ≠ description utile', () => {
  assert.equal(usefulDescription(cleanDescription('TD Cash Credit Card\n0:00\n0:00 / 0:15\nLive\n• Watch full video\nBack [](https://www.youtube.com/)', 'x')), false);
});
