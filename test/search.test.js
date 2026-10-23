import { test } from 'node:test';
import assert from 'node:assert/strict';
import { runSearch } from '../src/search.js';
import { createDemoProvider } from '../src/youtube/demo.js';
import { filterResults, sortResults, groupByCategory } from '../src/core/filter.js';
import { parseSearchPage, parseWatchPage } from '../src/youtube/scrape.js';
import { extractJsonAfter, parseViews } from '../src/youtube/util.js';

test('recherche complète en mode démo', async () => {
  const out = await runSearch({ prompt: 'rapide énergique musicale', licenses: ['ffp', 'upto'], device: 'desktop' }, createDemoProvider());
  assert.equal(out.source, 'demo');
  assert.ok(out.results.length > 3);
  const uzi = out.results.find((r) => r.id === 'demo-uzi2');
  assert.equal(uzi.license.category, 'upto');
  assert.equal(uzi.license.limit, 5000);
  const song = out.results.find((r) => r.id === 'demo-song1');
  if (song) assert.equal(song.isBeat, false);
});

test('filtre FFP : écarte les payantes et non-profit, garde les Up to à part', async () => {
  const out = await runSearch({ prompt: 'drill sombre', licenses: ['ffp', 'upto'], device: 'desktop', depth: 'approfondie' }, createDemoProvider());
  const kept = filterResults(out.results, { licenses: ['ffp', 'upto'] });
  assert.ok(kept.every((r) => ['ffp', 'upto'].includes(r.license.category)));
  const groups = groupByCategory(kept).map((g) => g.category);
  assert.ok(groups.indexOf('ffp') <= 0);
  const big = filterResults(out.results, { licenses: ['upto'], uptoMin: 50000 });
  assert.ok(big.every((r) => r.license.limit >= 50000));
});

test('filtre et tri BPM', () => {
  const mk = (id, bpm) => ({ id, bpm, isBeat: true, score: 0, styles: [], license: { category: 'ffp' } });
  const rs = [mk('a', 160), mk('b', 90), mk('c', null), mk('d', 140)];
  const f = filterResults(rs, { bpm: { enabled: true, min: 100, max: 165, requireBpm: true } });
  assert.deepEqual(f.map((r) => r.id).sort(), ['a', 'd']);
  assert.deepEqual(sortResults(f, 'bpm-asc').map((r) => r.id), ['d', 'a']);
  const keepUnknown = filterResults(rs, { bpm: { enabled: true, min: 100, max: 165 } });
  assert.ok(keepUnknown.some((r) => r.id === 'c'));
});

test('lecture des pages YouTube (format ytInitialData)', () => {
  const data = {
    contents: { twoColumnSearchResultsRenderer: { primaryContents: { sectionListRenderer: { contents: [{ itemSectionRenderer: { contents: [
      { videoRenderer: { videoId: 'abc123def45', title: { runs: [{ text: '[FREE] Yeat Type Beat "x}y"' }] }, ownerText: { runs: [{ text: 'Prod Z' }] }, viewCountText: { simpleText: '12,345 views' }, lengthText: { simpleText: '2:41' }, publishedTimeText: { simpleText: '3 weeks ago' } } },
      { adSlotRenderer: {} },
    ] } }] } } } },
  };
  const html = `<script>var ytInitialData = ${JSON.stringify(data)};</script>`;
  const list = parseSearchPage(html);
  assert.equal(list.length, 1);
  assert.equal(list[0].id, 'abc123def45');
  assert.equal(list[0].title, '[FREE] Yeat Type Beat "x}y"');
  assert.equal(list[0].views, 12345);
  assert.equal(list[0].duration, 161);

  const player = { videoDetails: { videoId: 'abc123def45', title: 't', shortDescription: 'FREE FOR PROFIT\n150 BPM', author: 'Prod Z', viewCount: '999', lengthSeconds: '161' }, microformat: { playerMicroformatRenderer: { publishDate: '2026-01-02' } } };
  const w = parseWatchPage(`<script>var ytInitialPlayerResponse = ${JSON.stringify(player)};var meta = {};</script>`);
  assert.equal(w.description, 'FREE FOR PROFIT\n150 BPM');
  assert.equal(w.views, 999);
  assert.equal(w.publishedAt, '2026-01-02');
});

test('utilitaires', () => {
  assert.deepEqual(extractJsonAfter('x = {"a":"}{","b":{"c":1}}; y', 'x ='), { a: '}{', b: { c: 1 } });
  assert.equal(parseViews('1.2M views'), 1200000);
  assert.equal(parseViews('3,456 views'), 3456);
});
