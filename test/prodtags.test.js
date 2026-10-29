import { test } from 'node:test';
import assert from 'node:assert/strict';
import { prodTags } from '../src/core/prodtags.js';

test('étiquettes d’une prod : rappeurs, courants, ambiances', () => {
  const a = prodTags({ title: '[FREE] Ninho x Tiakola Type Beat "Lune" (prod. Orin)', description: 'Melodic afro drill. #drill #melodic', bpm: 140 });
  assert.ok(a.includes('Ninho type beat') && a.includes('Tiakola type beat'), a.join());
  assert.ok(a.includes('Mélodique'), a.join());
  const b = prodTags({ title: 'young nudy x lucki type beat - bliss', description: 'dark hard trap beat', bpm: 159 });
  assert.ok(b.includes('Young Nudy type beat') && b.includes('Lucki type beat'), b.join());
  assert.ok(b.includes('Sombre') && b.includes('Agressif') && b.includes('Rapide'), b.join());
  const c = prodTags({ title: 'Pluggnb Type Beat "Love"', description: 'chill sad vibes', bpm: 70 });
  assert.ok(c.includes('Chill') && c.includes('Lent'), c.join());
  assert.equal(new Set(c.map((x) => x.toLowerCase())).size, c.length);
  assert.ok(prodTags({ title: 'x'.repeat(500) }).length <= 10);
  assert.deepEqual(prodTags({}), []);
});
