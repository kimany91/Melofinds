// Source « démo » : prods FICTIVES pour essayer l'interface sans accès à
// YouTube (pas de clé, réseau bloqué…). Les descriptions reprennent les
// formulations qu'on trouve vraiment sous les type beats, pour montrer
// comment l'algo les classe.

import { normalize } from '../core/text.js';

const V = (id, title, channel, views, publishedAt, description) => ({
  id: `demo-${id}`,
  title,
  channel,
  views,
  publishedAt,
  duration: 150 + ((views / 7) % 60),
  description,
  demo: true,
});

export const DEMO_VIDEOS = [
  V('uzi1', '[FREE] Lil Uzi Vert Type Beat - "Starlight" | Free For Profit 160 BPM', 'prod. nova (démo)', 48200, '2026-09-12',
    'FREE FOR PROFIT ✅ just credit (prod. nova) in the title\nBPM: 160 | Key: F# minor\nUntagged: beatstars link\n#lilUziVert #typebeat #freeforprofit'),
  V('uzi2', '(FREE) Lil Uzi Vert x Lil Tecca Type Beat "Sugar Rush"', 'kaybeats (démo)', 12900, '2026-10-02',
    '𝗙𝗥𝗘𝗘 𝗙𝗢𝗥 𝗣𝗥𝗢𝗙𝗜𝗧 up to 5,000 streams on Spotify / Apple Music.\nAfter 5k streams you must purchase a lease.\n155 bpm, key: C major'),
  V('tecca1', 'Lil Tecca Type Beat "Bubblegum" [FREE] 150bpm', 'melo.wav (démo)', 30500, '2026-08-21',
    'Free for non-profit use only. For profit use (Spotify, Apple Music…) you need to buy a lease: https://beatstars.com/demo\nMP3 Lease $29.99 - up to 10,000 streams\nWAV Lease $49.99 - up to 50,000 streams'),
  V('carti1', '[FREE] Playboi Carti x Ken Carson Type Beat "VAMP" | Rage', 'opium.lab (démo)', 88100, '2026-07-30',
    'free for profit (100k streams max)\nafter that hit me for a license\n165 BPM\n#rage #playboicarti #kencarson'),
  V('carti2', 'Ken Carson Type Beat - "Lights Out" (SOLD)', 'opium.lab (démo)', 9100, '2026-06-04',
    'This beat is SOLD. Check my other beats.'),
  V('yeat1', 'Yeat Type Beat "Bell Ringer" | Rage Type Beat 2026', 'tonka (démo)', 21000, '2026-10-11',
    'Buy this beat (instant delivery): https://bsta.rs/demo\nLeases starting at $25\n150 BPM'),
  V('nett1', '[FREE] Nettspend Type Beat "Jerk Season" | free for profit', 'xan.prod (démo)', 7400, '2026-10-15',
    'FREE FOR PROFIT — tu peux sortir le son sur Spotify sans payer, juste crédit obligatoire.\n168 bpm'),
  V('pop1', '[FREE] Pop Smoke Type Beat "WOO" | NY Drill Type Beat 2026', 'brklyn (démo)', 64000, '2026-05-19',
    'Free for profit ❌ (must buy a lease to release)\nfree for youtube only\n144 BPM | key: G minor'),
  V('pop2', '(FREE) Dark NY Drill Type Beat x Pop Smoke "Opps" | free for profit', 'shadowbeats (démo)', 15300, '2026-09-28',
    'Free for profit but you need to buy a license to release on Spotify and Apple Music.\n142 BPM'),
  V('fivio1', 'Fivio Foreign Type Beat - "Big Drip" | Hard Drill Free For Profit', 'drillszn (démo)', 33600, '2026-08-08',
    'FREE FOR PROFIT up to 10k streams. After 10k streams purchase a lease.\nPlease credit (prod. drillszn)\n140bpm'),
  V('kingvon1', '[FREE] King Von Type Beat "Opp Block" | Chicago Drill', 'chiraq808 (démo)', 51200, '2026-04-01',
    'Free beat. Download link below.\n138 BPM'),
  V('rod1', '[FREE] Rod Wave Type Beat "Rain" | Emotional Guitar Type Beat', 'soulwave (démo)', 102300, '2026-03-14',
    'FREE FOR PROFIT 💯 No need to buy, just put (prod. soulwave) in the title.\nBPM 128\nGuitar, piano, pain music'),
  V('durk1', 'Lil Durk Type Beat - "Voice of the Heroes" | Melodic Trap', 'h3ro (démo)', 23000, '2026-02-26',
    'Purchase the beat: beatstars.com/demo\nExclusive rights available\n145 BPM'),
  V('future1', '[FREE] Future x Metro Boomin Type Beat "EVIL" | Dark Trap', 'metr0nome (démo)', 76000, '2026-09-01',
    'free for profit ✔\nunlimited streams, no strings attached\nBPM: 145 | Key: D# minor\n#darktrap #future #metroboomin'),
  V('savage1', '21 Savage Type Beat "Blood" | free for profit up to 2000 streams', 'south4 (démo)', 8800, '2026-10-19',
    'Free for profit up to 2,000 streams. Need more? Grab a lease.\n134 bpm'),
  V('travis1', '[FREE] Travis Scott Type Beat "Astro" | Psychedelic Trap', 'cactus.jack.fan (démo)', 41000, '2026-07-07',
    '100% free / royalty free. Use it how you want.\n136 BPM'),
  V('summrs1', '[FREE] Summrs Type Beat "pink clouds" | Pluggnb', 'plugsoft (démo)', 18700, '2026-06-17',
    'free for profit (credit me)\n150 bpm | key: A major\n#pluggnb #summrs'),
  V('joey1', 'Joey Bada$$ Type Beat "Brooklyn Soul" | Boom Bap Free For Profit', 'dusty.mpc (démo)', 27400, '2026-01-29',
    'Free for profit. Sample cleared by me (original composition).\n90 BPM, jazzy, old school'),
  V('mac1', '[FREE] Mac Miller Type Beat "Sunday Morning" | Chill Jazzy', 'lofi.lou (démo)', 36500, '2026-05-02',
    'Free for non commercial use. Contact me for leasing.\n88 BPM'),
  V('kendrick1', 'Kendrick Lamar Type Beat "Compton Sun" | West Coast Free For Profit 2026', 'g.funk.dept (démo)', 29800, '2026-08-30',
    'FREE FOR PROFIT up to 50k streams on all platforms\n96 BPM'),
  V('glock1', '[FREE] Key Glock Type Beat "Paper Route" | Memphis', 'mphs (démo)', 14200, '2026-09-09',
    'free for profit just credit\n150 BPM, cowbell'),
  V('jersey1', '[FREE] Jersey Club Type Beat "Bounce" | Bandmanrill Type Beat', 'njclub (démo)', 11100, '2026-10-05',
    'FREE FOR PROFIT (5k streams), then purchase a license\n142 BPM'),
  V('babyface1', 'Babyface Ray Type Beat "Motor City" | Detroit Type Beat', 'det.keys (démo)', 9600, '2026-07-21',
    'Leases: $20 / $40 / $100 exclusive\nBPM 100'),
  V('baby1', '[FREE FOR PROFIT] Lil Baby Type Beat "Real Story" | Melodic Trap 2026', 'trapwave (démo)', 54300, '2026-10-08',
    'Thanks for listening 🙏\nThis beat is free for non-profit only (YouTube, SoundCloud).\nFor Spotify / Apple Music you need to purchase a lease: https://beatstars.com/demo\n145 BPM | Key: E minor\nBusiness: trapwave@mail.com'),
  V('gunna1', 'FREE FOR PROFIT Gunna Type Beat "Wunna Drip" | Energetic Trap', 'dripz (démo)', 26100, '2026-09-21',
    'YouTube ✅\nSpotify ❌\nApple Music ❌\nDM me before releasing on streaming platforms.\n150 bpm'),
  V('uzi3', '[FREE FOR PROFIT] Lil Uzi Vert Type Beat "Neon Pink" | Fast Energetic Synth', 'neonprod (démo)', 19400, '2026-10-20',
    'FREE FOR PROFIT ✅\nSpotify ✅ Apple Music ✅ — no lease needed, just credit (prod. neon)\nBPM: 158 | Key: G# minor\nUntagged WAV on beatstars if you want to support'),
  V('song1', 'Lil Uzi Vert - Just Wanna Rock (Official Video)', 'Artiste officiel (démo)', 9000000, '2022-10-17',
    'Stream the album now.'),
];

/** Recherche « démo » : classe les vidéos fictives selon les mots de la requête. */
export function createDemoProvider() {
  return {
    name: 'demo',
    label: 'Démo (prods fictives)',
    async search(q, max = 20) {
      const words = normalize(q).split(/\s+/).filter((w) => w.length > 2 && !['type', 'beat', 'free', 'for', 'profit'].includes(w));
      const scored = DEMO_VIDEOS.map((v) => {
        const t = normalize(`${v.title} ${v.description}`);
        return { v, s: words.filter((w) => t.includes(w)).length };
      }).filter((x) => x.s > 0);
      scored.sort((a, b) => b.s - a.s);
      const list = scored.length ? scored.map((x) => x.v) : DEMO_VIDEOS.slice(0, 6);
      return list.slice(0, max).map(({ id, title, channel }) => ({ id, title, channel, description: '' }));
    },
    async details(ids) {
      const out = new Map();
      for (const id of ids) {
        const v = DEMO_VIDEOS.find((d) => d.id === id);
        if (v) out.set(id, { ...v, fullDescription: true });
      }
      return out;
    },
  };
}
