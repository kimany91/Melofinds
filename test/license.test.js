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

// --- Vraies descriptions YouTube (lues via Parallel Search) -------------------

test('réel : « surpasses 5000 (5k) monetized streams… buy a license » → Up to 5K', () => {
  const r = analyzeLicense('[FREE FOR PROFIT] Lil Uzi Vert Type Beat - "bankroll"',
    '►BUY THIS BEAT(untagged): https://bsta.rs/33a587d4e bpm: 155 key: B min\n🕊 IMPORTANT terms / must read * MUST credit the producer: tao x jvsper * You can not content ID your songs using my beats unless you are the exclusive owner of the beat. By downloading/using this beat, you agree that whenever your song using this musical piece surpasses 5000 (5k) monetized streams or plays, you\'ll buy a license as soon as possible.');
  assert.equal(r.category, 'upto');
  assert.equal(r.limit, 5000);
  assert.equal(r.creditRequired, true);
});

test('réel : « [FREE] … free for Non Profit use only… purchase/lease to upload to streaming » → Free', () => {
  const r = analyzeLicense('[FREE] Lil Uzi Vert Type Beat "Salute Me"',
    'Key: E Major BPM: 140 🌏 Beat https://bsta.rs/9cead7d65 Beats are free for Non Profit use only! Must Credit: (Prod. 99LA) You must purchase/lease in order to upload to streaming services. Failure to do so may result in a copyright claim.');
  assert.equal(r.category, 'fnp');
  assert.equal(r.confidence, 'haute');
});

// --- « YouTube / SoundCloud only » = pas libre pour Spotify ------------------

test('« soundcloud and youtube only » dans la description → pas free for profit (titre trompeur)', () => {
  const T = '[FREE FOR PROFIT] Lucki x Summrs Type Beat - "Lost"';
  for (const d of [
    'Soundcloud and youtube only',
    'This beat is free for profit\nSoundcloud and Youtube only !',
    'YouTube & SoundCloud only. Buy a lease for Spotify: link',
    'Free for YouTube/SoundCloud use only',
    'For non-monetized YouTube videos only',
    'Only allowed on YouTube and SoundCloud',
    'Usage: youtube, soundcloud, tiktok only',
    'Uniquement youtube et soundcloud',
    'Pour youtube / soundcloud seulement',
    'You can only use it on youtube and soundcloud',
    'free for profit up to 5000 streams, soundcloud & youtube only',
  ]) {
    const r = analyzeLicense(T, d);
    assert.equal(r.category, 'fnp', d);
    assert.equal(r.misleading, true, d);
  }
});

test('YouTube / SoundCloud cités sans « only » → reste free for profit', () => {
  const T = '[FREE FOR PROFIT] Type Beat';
  assert.equal(cat(T, 'Free for profit, use it on spotify, youtube, soundcloud, anywhere'), 'ffp');
  assert.equal(cat(T, 'Subscribe to my youtube! Follow my soundcloud. Free for profit, no credit needed'), 'ffp');
  assert.equal(cat(T, 'Free for profit: allowed on Spotify, Apple Music, YouTube, SoundCloud. Not for youtube only'), 'ffp');
});

test('« only free for profit on YouTube and SoudCloud » + licence pour Spotify → pas free for profit', () => {
  const d = `• this is only free for profit on YouTube and SoudCloud.
• do not use YouTube's Content ID on your songs.
• must credit (prod.geesyn).
• to use this beat for profit on all platforms (Spotify, Apple Music, etc..) you need to purchase a license`;
  for (const T of ['[FREE] Nettspend Type Beat "Glow" (prod. geesyn)', 'Nettspend Type Beat "Glow"']) {
    assert.equal(cat(T, d), 'fnp', T);
  }
  const r = analyzeLicense('[FREE FOR PROFIT] Nettspend Type Beat', d);
  assert.equal(r.category, 'fnp');
  assert.equal(r.misleading, true);  // titre trompeur signalé
  assert.equal(r.creditRequired, true);
  // chaque morceau du piège, seul
  assert.equal(cat('[FREE FOR PROFIT] Type Beat', 'This is only free for profit on YouTube.'), 'fnp');
  assert.equal(cat('[FREE FOR PROFIT] Type Beat', 'Free for profit only on SoundCloud'), 'fnp');
  assert.equal(cat('[FREE FOR PROFIT] Type Beat', 'To use this beat for profit on all platforms (Spotify, Apple Music, etc..) you need to purchase a license'), 'fnp');
  assert.equal(cat('[FREE FOR PROFIT] Type Beat', 'youtube & souncloud only'), 'fnp');
  // la citation affichée reste juste (positions inchangées)
  assert.match(r.reasons.map((x) => x.quote).join(' '), /only free for profit on YouTube and SoudCloud/);
});
