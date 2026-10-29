import { test } from 'node:test';
import assert from 'node:assert/strict';
import { cleanProdTitle, prodFileName } from '../src/core/prodname.js';

// Mêmes cas que pc/test_melofinds_pc.py : le téléphone nomme les prods comme le PC.
test('jamais « free » dans le nom', () => {
  const cases = {
    '[FREE FOR PROFIT] Lil Uzi Vert Type Beat - "bankroll"': "Lil Uzi Vert Type Beat - 'bankroll'",
    '(FREE) Luther x Summrs Type Beat': 'Luther x Summrs Type Beat',
    'FREE Lucki Type Beat | Free For Profit': 'Lucki Type Beat',
    '[FREE] FFP Pluggnb Type Beat': 'Pluggnb Type Beat',
    'Free For Profit Beats - Dark Trap Type Beat': 'Dark Trap Type Beat',
    'Lil Uzi Type Beat - "Free"': 'Lil Uzi Type Beat',
    'Damso Type Beat (Free for non profit) 100% FREE': 'Damso Type Beat',
    'Instru rap gratuite | Royalty Free': 'Instru rap',
    '【FREE】 Yeat Type Beat': 'Yeat Type Beat',
  };
  for (const [inp, out] of Object.entries(cases)) {
    assert.equal(cleanProdTitle(inp), out, inp);
    assert.doesNotMatch(cleanProdTitle(inp).toLowerCase(), /free|ffp|gratuit/);
  }
});

test('clé, BPM et licence', () => {
  assert.equal(prodFileName({ title: '[FREE] Luther Type Beat - TREE', key: 'F# min', bpm: 140 }), 'Luther Type Beat - TREE [F# min, 140 BPM]');
  assert.equal(prodFileName({ title: 'Luther Type Beat', bpm: 150 }), 'Luther Type Beat [150 BPM]');
  assert.equal(prodFileName({ title: 'Luther Type Beat', key: 'C maj' }), 'Luther Type Beat [C maj]');
  assert.equal(prodFileName({ title: 'Luther Type Beat' }), 'Luther Type Beat');
  assert.equal(prodFileName({ title: '[FREE FOR PROFIT] Luther Type Beat - TREE', key: 'F# min', bpm: 140, lic: 'ffp' }), 'Luther Type Beat - TREE [F# min, 140 BPM] [FFP]');
  assert.equal(prodFileName({ title: '(FREE) Damso Type Beat', lic: 'fnp' }), 'Damso Type Beat [F]');
  assert.equal(prodFileName({ title: 'Luther Type Beat', bpm: 150, lic: 'upto', limit: 5000 }), 'Luther Type Beat [150 BPM] [FFP, UPTO 5000]');
  assert.equal(prodFileName({ title: 'Luther Type Beat', lic: 'upto', limit: 'pas un nombre' }), 'Luther Type Beat [FFP, UPTO]');
  assert.equal(prodFileName({ title: 'Luther Type Beat', lic: 'paid' }), 'Luther Type Beat');
  assert.equal(prodFileName({ title: 'Luther Type Beat', lic: '../../evil' }), 'Luther Type Beat');
  const t = "Lucki Type Beat 'Haze'";
  assert.equal(prodFileName({ title: t, key: 'C# min', bpm: 150, lic: 'ffp', tbKey: true, tbBpm: true }), "Lucki Type Beat 'Haze' [(Finded) Key C# minor, 150 BPM] [FFP]");
  assert.equal(prodFileName({ title: t, key: 'C# min', bpm: 150, tbBpm: true }), "Lucki Type Beat 'Haze' [C# min] [(Finded) 150 BPM]");
});

test('caractères dangereux', () => {
  const n = prodFileName({ title: '..\\..\\Windows\\system32/evil:*?"<>|.exe' });
  for (const ch of '\\/:*?"<>|') assert.ok(!n.includes(ch), ch);
  assert.equal(prodFileName({ title: 'CON' }), 'Prod CON');
});
