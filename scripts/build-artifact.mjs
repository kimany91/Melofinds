// Assemble la version « page Claude » de Melofinds en UN seul fichier HTML :
// le moteur (src/core) + les prods d'exemple + l'interface (artifact/).
//   node scripts/build-artifact.mjs   →   dist/melofinds.html (page Claude)
//                                     →   docs/index.html (version web, GitHub Pages)

import { readFileSync, writeFileSync, mkdirSync, copyFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';

const ROOT = fileURLToPath(new URL('..', import.meta.url));
const read = (p) => readFileSync(join(ROOT, p), 'utf8');

// Ordre = ordre des dépendances
const MODULES = [
  'src/core/text.js',
  'src/core/genres.js',
  'src/core/frartists.js',
  'src/core/artistmatch.js',
  'src/core/license.js',
  'src/core/bpm.js',
  'src/core/planner.js',
  'src/core/analyze.js',
  'src/core/filter.js',
  'src/core/ytparse.js',
  'src/core/tunebat.js',
  'src/core/usedby.js',
  'src/core/prodname.js',
  'src/youtube/demo.js',
];

function stripModule(src, name) {
  const out = src
    .split('\n')
    .filter((line) => !/^import\s.+from\s+['"].+['"];?\s*$/.test(line))
    .map((line) => line.replace(/^export\s+(?=(?:async\s+)?function|const|let|class)/, ''))
    .join('\n');
  if (/^\s*(import|export)\s/m.test(out)) throw new Error(`${name} : import/export non géré`);
  return `// ===== ${name} =====\n${out}`;
}

const core = MODULES.map((m) => stripModule(read(m), m)).join('\n\n');
const html = read('artifact/template.html')
  .replace('__BUILD__', () => new Date().toLocaleString('fr-FR', { timeZone: 'Europe/Paris', day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' }).replace(' ', ' à '))
  .replace('/*__STYLE__*/', () => read('artifact/style.css'))
  .replace('/*__CORE__*/', () => core.replace(/<\/script/gi, '<\\/script'))
  .replace('/*__APP__*/', () => read('artifact/app.js').replace(/<\/script/gi, '<\\/script'));

mkdirSync(join(ROOT, 'dist'), { recursive: true });
writeFileSync(join(ROOT, 'dist/melofinds.html'), html);
console.log(`dist/melofinds.html (${(html.length / 1024).toFixed(0)} Ko)`);

// Version web (GitHub Pages, dossier docs/) : même interface, page complète,
// recherche via l'API YouTube et lecteur intégré (interdit dans la page Claude).
const webHead = [
  '<!doctype html>',
  '<html lang="fr">',
  '<head>',
  '<meta charset="utf-8">',
  '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">',
  '<meta name="description" content="Trouve des prods rap sur YouTube, vérifie la licence (free for profit, up to, payant) et écoute-les direct.">',
  '<meta name="theme-color" content="#0b0c10">',
  '<link rel="icon" href="icon.svg" type="image/svg+xml">',
  '<link rel="preconnect" href="https://www.googleapis.com">',
  '<link rel="preconnect" href="https://www.youtube-nocookie.com">',
  '<link rel="preconnect" href="https://www.youtube.com">',
  '<link rel="preconnect" href="https://i.ytimg.com">',
  '<link rel="preconnect" href="https://www.google.com">',
  '<style>:root{padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}body{margin:0}img{max-width:100%}[hidden]{display:none!important}</style>',
  '<script>window.MF_TARGET = "web";</script>',
  '</head>',
  '<body>',
].join('\n');
const web = `${webHead}\n${html}\n</body>\n</html>\n`;
mkdirSync(join(ROOT, 'docs'), { recursive: true });
writeFileSync(join(ROOT, 'docs/index.html'), web);
writeFileSync(join(ROOT, 'docs/.nojekyll'), '');
copyFileSync(join(ROOT, 'public/icon.svg'), join(ROOT, 'docs/icon.svg'));
console.log(`docs/index.html (${(web.length / 1024).toFixed(0)} Ko)`);
