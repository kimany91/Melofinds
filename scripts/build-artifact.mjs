// Assemble la version « page Claude » de Melofinds en UN seul fichier HTML :
// le moteur (src/core) + les prods d'exemple + l'interface (artifact/).
//   node scripts/build-artifact.mjs   →   dist/melofinds.html

import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';

const ROOT = fileURLToPath(new URL('..', import.meta.url));
const read = (p) => readFileSync(join(ROOT, p), 'utf8');

// Ordre = ordre des dépendances
const MODULES = [
  'src/core/text.js',
  'src/core/genres.js',
  'src/core/license.js',
  'src/core/bpm.js',
  'src/core/planner.js',
  'src/core/analyze.js',
  'src/core/filter.js',
  'src/core/ytparse.js',
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
  .replace('/*__STYLE__*/', () => read('artifact/style.css'))
  .replace('/*__CORE__*/', () => core.replace(/<\/script/gi, '<\\/script'))
  .replace('/*__APP__*/', () => read('artifact/app.js').replace(/<\/script/gi, '<\\/script'));

mkdirSync(join(ROOT, 'dist'), { recursive: true });
writeFileSync(join(ROOT, 'dist/melofinds.html'), html);
console.log(`dist/melofinds.html (${(html.length / 1024).toFixed(0)} Ko)`);
