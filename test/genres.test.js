import { test } from 'node:test';
import assert from 'node:assert/strict';
import { GENRES } from '../src/core/genres.js';
import { normalize } from '../src/core/text.js';
import { buildPlan, classifyStyles } from '../src/core/planner.js';
import { findArtists } from '../src/core/artistmatch.js';

const top = (p) => buildPlan(p, { licenses: ['ffp'] }).genres.map((g) => g.id);
const NICHE = new Set(GENRES.filter((g) => g.pop < 1).map((g) => g.id));

test('base de courants : ids uniques, un nom de courant = un seul courant', () => {
  const ids = GENRES.map((g) => g.id);
  assert.equal(new Set(ids).size, ids.length);
  const owner = new Map();
  for (const g of GENRES) {
    for (const a of g.aliases) {
      const k = normalize(a);
      assert.ok(!owner.has(k) || owner.get(k) === g.id, `« ${a} » dans ${owner.get(k)} et ${g.id}`);
      owner.set(k, g.id);
    }
  }
  assert.ok(GENRES.length >= 60);
});

test('le nom le plus précis l’emporte (« trap metal » n’est pas de la trap)', () => {
  assert.deepEqual(top('une prod trap metal'), ['trap-metal']);
  assert.deepEqual(top('uk drill sombre'), ['uk-drill']);
  assert.deepEqual(top('glitch hop'), ['glitch-hop']);
  assert.deepEqual(top('rare phonk'), ['rare-phonk']);
  assert.equal(top('boom bap sombre')[0], 'hardcore-boom-bap');
  assert.equal(classifyStyles('Ghostemane Type Beat "GRAVE" | Trap Metal')[0].id, 'trap-metal');
  assert.ok(!classifyStyles('Ghostemane Type Beat "GRAVE" | Trap Metal').some((s) => s.id === 'trap'));
  assert.ok(!classifyStyles('[FREE] Glitch Hop Type Beat').some((s) => s.id === 'hyperpop'));
});

test('ambiances seules : les courants majeurs passent devant les courants de niche', () => {
  for (const p of ['sombre et agressif', 'triste mélodique', 'planant triste', 'rapide énergique', 'chill']) {
    assert.ok(!NICHE.has(top(p)[0]), `${p} → ${top(p)[0]}`);
  }
  assert.equal(top('planant triste')[0], 'cloud');
});

test('sons bedroom / expérimentaux / rock reconnus', () => {
  assert.equal(top('bedroom lo-fi triste')[0], 'bedroom');
  assert.equal(top('son intime fait maison mélancolique')[0], 'bedroom');
  assert.equal(top('rock saturé qui crie')[0], 'trap-metal');
  assert.equal(top('trip hop planant')[0], 'trip-hop');
  assert.equal(top('comme bones')[0], 'sesh');
  assert.equal(top('suicideboys')[0], 'g59');
});

test('« lex luger » est un courant, pas le rappeur Luther', () => {
  const p = buildPlan('lex luger épique', { licenses: [] });
  assert.equal(p.genres[0].id, 'cinematic-trap');
  assert.deepEqual(p.recognized.map((r) => r.name), []);
  assert.equal(p.queries[0].q, 'Lex Luger type beat');
});

test('rappeurs FR liés aux nouveaux courants', () => {
  assert.equal(top('une prod à la Lonepsi')[0], 'bedroom');
  assert.equal(top('comme lujipeka')[0], 'rap-rock');
  assert.equal(top('odezenne')[0], 'trip-hop');
  assert.ok(top('kaaris').includes('cinematic-trap'));
  assert.ok(top('vîrus').includes('abstract'));
});

test('les mots courants ne deviennent pas des artistes', () => {
  const names = (t) => findArtists(t).map((m) => m.name);
  assert.deepEqual(names('plume légère, son moral du week end, flow technique'), []);
  assert.deepEqual(names('ambiance smokey, guitare saturée, rap de chambre'), []);
  assert.deepEqual(names('drill latino 145 bpm'), []);
});
