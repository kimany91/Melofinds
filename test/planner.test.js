import { test } from 'node:test';
import assert from 'node:assert/strict';
import { buildPlan, classifyStyles } from '../src/core/planner.js';
import { extractBpm, extractKey } from '../src/core/bpm.js';

test('« rapide énergique et musicale » → courants rapides et mélodiques', () => {
  const p = buildPlan('rapide, énergique et musicale', { licenses: ['ffp'], device: 'desktop' });
  const moods = p.moods.map((m) => m.id);
  assert.deepEqual(moods.sort(), ['energetic', 'fast', 'melodic']);
  assert.equal(p.genres[0].id, 'melodic-hype');
  assert.ok(p.artists.some((a) => a.name === 'Lil Uzi Vert'));
  assert.ok(p.bpmRange.min >= 140);
  assert.ok(p.queries.every((q) => q.q.endsWith('free for profit')));
  assert.equal(p.queries.length, 5);
});

test('le mobile fait une recherche plus légère que le PC', () => {
  const mob = buildPlan('sombre drill', { device: 'mobile' });
  const pc = buildPlan('sombre drill', { device: 'desktop' });
  assert.ok(mob.queries.length < pc.queries.length);
  assert.ok(mob.depth.perQuery < pc.depth.perQuery);
  assert.equal(buildPlan('sombre drill', { device: 'mobile', depth: 'approfondie' }).queries.length, 8);
});

test('artiste cité et BPM explicite', () => {
  const p = buildPlan('comme Pop Smoke, 145 bpm', { licenses: ['fnp'] });
  assert.equal(p.artists[0].name, 'Pop Smoke');
  assert.equal(p.genres[0].id, 'ny-drill');
  assert.deepEqual([p.bpmRange.min, p.bpmRange.max], [140, 150]);
  assert.ok(p.queries[0].q.startsWith('Pop Smoke type beat'));
  assert.ok(p.queries[0].q.endsWith(' free'));
});

test('recherche directe placée en premier', () => {
  const p = buildPlan('', { manualQuery: 'Yeat type beat', licenses: ['ffp', 'upto'] });
  assert.equal(p.queries[0].q, 'Yeat type beat free for profit');
  assert.equal(p.queries[0].why, 'ta recherche directe');
});

test('description vide / inconnue → plan par défaut avec note', () => {
  const p = buildPlan('blabla');
  assert.equal(p.genres[0].id, 'trap');
  assert.equal(p.notes.length, 1);
});

test('classement des prods par courant', () => {
  assert.equal(classifyStyles('[FREE] Pop Smoke Type Beat "WOO" | NY Drill')[0].id, 'ny-drill');
  assert.ok(classifyStyles('Ken Carson x Playboi Carti type beat').some((s) => s.id === 'rage'));
});

test('BPM et tonalité', () => {
  assert.equal(extractBpm('Type Beat 160 BPM', ''), 160);
  assert.equal(extractBpm('Type Beat', 'BPM: 145 | Key: C# minor'), 145);
  assert.equal(extractBpm('Type Beat @140bpm', ''), 140);
  assert.equal(extractBpm('2026 Type Beat', 'no tempo here'), null);
  assert.equal(extractKey('', 'BPM: 145 | Key: C# minor'), 'C# min');
  assert.equal(extractKey('', 'Key: Bbm'), 'Bb min');
  assert.equal(extractKey('Key Glock Type Beat', ''), null);
});
