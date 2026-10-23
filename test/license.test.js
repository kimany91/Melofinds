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

// --- Titre « free for profit » vs description : la description fait foi -----

test('titre FFP mais description « free for non-profit, lease pour Spotify » → écarté + titre trompeur', () => {
  const r = analyzeLicense('[FREE FOR PROFIT] Lil Baby Type Beat', 'This beat is free for non-profit only. Purchase a lease for Spotify.');
  assert.equal(r.category, 'fnp');
  assert.equal(r.misleading, true);
  assert.equal(r.confidence, 'haute');
});

test('titre FFP mais « Spotify ❌ » dans la description', () => {
  const r = analyzeLicense('Free For Profit Gunna Type Beat', 'YouTube ✅\nSpotify ❌\nApple Music ❌');
  assert.equal(r.category, 'fnp');
  assert.equal(r.misleading, true);
});

test('titre FFP mais « youtube only » / payer pour les plateformes', () => {
  assert.equal(analyzeLicense('FREE FOR PROFIT Type Beat', 'free for profit on youtube only. For streaming platforms buy a lease.').misleading, true);
  assert.equal(analyzeLicense('FREE FOR PROFIT Type Beat', 'Pour Spotify il faut acheter la licence').category, 'fnp');
  assert.equal(analyzeLicense('FREE FOR PROFIT Type Beat', 'DM me before releasing on Spotify').category, 'fnp');
  assert.equal(analyzeLicense('FREE FOR PROFIT Type Beat', 'You cannot upload this beat to Spotify without a lease').category, 'fnp');
});

test('description qui confirme → FFP confiance haute ; titre seul → confiance moyenne', () => {
  const ok = analyzeLicense('FREE FOR PROFIT Type Beat', 'Spotify ✅ Apple Music ✅ just credit me');
  assert.equal(ok.category, 'ffp');
  assert.equal(ok.confidence, 'haute');
  assert.equal(ok.misleading, false);
  const titleOnly = analyzeLicense('FREE FOR PROFIT Type Beat', 'Instagram: @prodx');
  assert.equal(titleOnly.category, 'ffp');
  assert.equal(titleOnly.confidence, 'moyenne');
});

test('« sans licence / no lease needed » ne déclenche pas de faux « payant »', () => {
  assert.equal(cat('FREE FOR PROFIT beat', 'You can upload it to Spotify, no lease needed'), 'ffp');
  assert.equal(cat('FREE FOR PROFIT beat', 'Sur Spotify sans payer, juste crédit'), 'ffp');
});

test('titre FFP + limite dans la description → Up to (pas trompeur)', () => {
  const r = analyzeLicense('FREE FOR PROFIT Type Beat', 'free for profit up to 10k streams, then buy a lease');
  assert.equal(r.category, 'upto');
  assert.equal(r.misleading, false);
});

test('infos clés extraites de la description', async () => {
  const { extractKeyLines } = await import('../src/core/license.js');
  const lines = extractKeyLines('🔥 New beat\nFREE FOR PROFIT up to 5k streams\nCredit: (prod. nova)\nBPM 150 | Key: A minor\nBusiness: nova@mail.com\n#trap #beat');
  assert.deepEqual(lines.map((l) => l.type), ['licence', 'credit', 'tempo', 'contact']);
});

test('liens Spotify du producteur ≠ obligation de payer', () => {
  assert.equal(cat('FREE FOR PROFIT Type Beat', 'Free for profit, just credit\nFollow me on Spotify: https://open.spotify.com/x | Buy untagged: beatstars.com/x'), 'ffp');
  assert.equal(cat('FREE FOR PROFIT Type Beat', 'Free for profit\nListen to my album on Spotify'), 'ffp');
});

test('« Free For Profit » en fin de titre + « 1.2K views » à la ligne suivante ≠ limite', () => {
  const r = analyzeLicense('[FREE] Type Beat | Free For Profit', '1.2K views · 3 weeks ago\nFREE FOR PROFIT just credit');
  assert.equal(r.category, 'ffp');
  assert.equal(r.limit, null);
});
