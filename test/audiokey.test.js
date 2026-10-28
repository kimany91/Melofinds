import { test } from 'node:test';
import assert from 'node:assert/strict';
import { analyzeAudio, keyFromChroma, tempoFromEnvelope } from '../src/core/audiokey.js';
import { synthBeat } from './support/synthbeat.js';

// Faux beats (808, kick, snare, hi-hats, accords, mélodie) au BPM et dans la clé connus,
// en son propre ou « haut-parleur de téléphone capté au micro ».
const CASES = [
  { bpm: 150, key: 'G# min', phone: true, halfTime: true, hats: 16 },
  { bpm: 140, key: 'E min', phone: false, halfTime: true, hats: 16 },
  { bpm: 128, key: 'D maj', phone: true, halfTime: true, hats: 16, detune: 0.3 },
  { bpm: 100, key: 'C# min', phone: false, halfTime: false, hats: 8 },
  { bpm: 88, key: 'F# min', phone: true, halfTime: false, hats: 8, detune: -0.25 },
  { bpm: 165, key: 'A# maj', phone: true, halfTime: true, hats: 16 },
];

test('BPM et clé retrouvés sur des prods de synthèse (son propre et micro de téléphone)', () => {
  for (const [i, c] of CASES.entries()) {
    const x = synthBeat({ ...c, seconds: 16, seed: i + 11 });
    const r = analyzeAudio(x, 22050);
    const what = `${c.bpm} ${c.key}${c.phone ? ' (tél)' : ''}`;
    assert.ok(Math.abs(r.bpm - c.bpm) <= 1 || Math.abs((r.bpmAlt || 0) - c.bpm) <= 1, `${what} → ${r.bpm} (ou ${r.bpmAlt})`);
    assert.equal(r.key, c.key, `${what} → ${r.key}`);
  }
});

test('demi-temps : la valeur « prod » (85-175) en premier, l’autre en alternative', () => {
  const r = analyzeAudio(synthBeat({ bpm: 150, key: 'A min', seconds: 16, phone: true, halfTime: true, hats: 16, seed: 3 }), 22050);
  assert.equal(r.bpm, 150);
  assert.equal(r.bpmAlt, 75);
});

test('clé : gamme puis tonique (préférence mineur), relative donnée en second', () => {
  // A mineur naturel net : la, do, mi forts
  const ch = [0.9, 0, 0.3, 0, 0.7, 0.4, 0, 0.5, 0, 1, 0, 0.3];
  const k = keyFromChroma(ch);
  assert.equal(k.key, 'A min');
  assert.equal(k.second, 'C maj');
  assert.equal(keyFromChroma(new Array(12).fill(0)), null);
});

test('silence ou bruit : pas de résultat inventé', () => {
  assert.equal(analyzeAudio(new Float32Array(22050 * 5), 22050), null);
  assert.equal(tempoFromEnvelope(new Float32Array(500), 86), null);
});
