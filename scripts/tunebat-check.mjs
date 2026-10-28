// Essai réel de Tunebat Analyzer (lancé sur GitHub : .github/workflows/tunebat-check.yml).
// Fait exactement comme la fenêtre de l'appli Android (TunebatActivity.java) : ouvre
// tunebat.com/Analyzer, sert le fichier à l'adresse /__melofinds__/…, le donne au champ
// « Select Files » (DataTransfer), puis lit le tableau des résultats.
import { chromium } from 'playwright';
import fs from 'node:fs';

const file = process.argv[2];
const name = 'Melofinds-TEST0000001.wav';
const browser = await chromium.launch();
const page = await browser.newPage({ userAgent: 'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Mobile Safari/537.36', viewport: { width: 412, height: 900 } });
await page.route(`https://tunebat.com/__melofinds__/${name}`, (r) => r.fulfill({ status: 200, contentType: 'audio/wav', body: fs.readFileSync(file) }));
page.on('console', (m) => { if (m.type() === 'error') console.log('console:', m.text().slice(0, 160)); });
await page.goto('https://tunebat.com/Analyzer', { waitUntil: 'domcontentloaded', timeout: 60000 });
await page.waitForTimeout(6000);
console.log('titre :', await page.title());
console.log('champs fichier :', await page.locator('input[type=file]').count(), JSON.stringify(await page.$$eval('input[type=file]', (els) => els.map((e) => ({ accept: e.accept, multiple: e.multiple, cls: e.className })))));
const inj = await page.evaluate(async (n) => {
  try {
    const b = await (await fetch('/__melofinds__/' + n)).blob();
    const f = new File([b], n, { type: 'audio/wav' });
    const dt = new DataTransfer(); dt.items.add(f);
    const i = document.querySelector('input[type=file]');
    if (!i) return 'pas de champ';
    i.files = dt.files;
    i.dispatchEvent(new Event('change', { bubbles: true }));
    i.dispatchEvent(new Event('input', { bubbles: true }));
    return `donné (${b.size} octets)`;
  } catch (e) { return 'erreur ' + e; }
}, name);
console.log('injection :', inj);
const read = (n) => {
  n = n.toLowerCase(); const o = {};
  for (const t of document.querySelectorAll('table')) {
    const hs = [...t.querySelectorAll('th')].map((x) => x.innerText.trim().toLowerCase());
    for (const tr of t.querySelectorAll('tr')) {
      const c = [...tr.querySelectorAll('td')].map((x) => x.innerText.trim()); if (!c.length) continue;
      const row = c.join(' | '); if (!row.toLowerCase().includes(n)) continue; o.row = row;
      hs.forEach((h, k) => { if (/key|clé|tonalit/.test(h)) o.key = c[k]; if (/bpm|tempo/.test(h)) o.bpm = c[k]; if (/camelot/.test(h)) o.camelot = c[k]; });
    }
  }
  if (!o.row) { const x = document.body.innerText; const k = x.toLowerCase().indexOf(n); if (k >= 0) o.row = x.slice(k, k + 240); }
  return o;
};
for (let s = 0; s < 60; s++) {
  await page.waitForTimeout(2000);
  const o = await page.evaluate(read, name.replace('.wav', ''));
  if (s % 5 === 0 || o.key) console.log(`t+${2 * (s + 1)} s :`, JSON.stringify(o));
  if (o.key && (o.bpm || /\d{2,3}/.test(o.row || ''))) { console.log('RÉSULTAT :', JSON.stringify(o)); break; }
}
const tables = await page.$$eval('table', (ts) => ts.map((t) => t.outerHTML.slice(0, 1500)));
console.log('tableaux :', tables.length);
tables.forEach((t, i) => console.log(`tableau ${i} :`, t));
console.log('texte (début) :', (await page.evaluate(() => document.body.innerText)).slice(0, 1500).replace(/\n+/g, ' / '));
await browser.close();
