import { test } from 'node:test';
import assert from 'node:assert/strict';
import { playlistIdOf, parsePlaylistPage } from '../src/core/ytparse.js';

test('lien de playlist collé dans la recherche', () => {
  const id = 'PLx0sYbCqOb8TBPRdmBHs5Iftvv9TPboYG';
  assert.equal(playlistIdOf(`https://www.youtube.com/playlist?list=${id}`), id);
  assert.equal(playlistIdOf(`https://youtube.com/playlist?list=${id}&si=AbC123xyz`), id);
  assert.equal(playlistIdOf(`https://m.youtube.com/playlist?list=${id}`), id);
  assert.equal(playlistIdOf(`https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=${id}&index=3`), id);
  assert.equal(playlistIdOf(`https://music.youtube.com/playlist?list=${id}`), id);
  assert.equal(playlistIdOf(`https://youtu.be/dQw4w9WgXcQ?list=${id}`), id);
  assert.equal(playlistIdOf(`  ${id}  `), id);
  // non répertoriée : même forme de lien
  assert.equal(playlistIdOf('https://www.youtube.com/playlist?list=PLu5yHuGq7sQtQyuWl3nGqnTmXn8T4y9Ze'), 'PLu5yHuGq7sQtQyuWl3nGqnTmXn8T4y9Ze');
  // pas une playlist
  assert.equal(playlistIdOf('https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=RDdQw4w9WgXcQ&start_radio=1'), null);
  assert.equal(playlistIdOf('https://www.youtube.com/watch?v=dQw4w9WgXcQ'), null);
  assert.equal(playlistIdOf('ninho type beat'), null);
  assert.equal(playlistIdOf('https://evil.example/?list=PLx0sYbCqOb8TBPRdmBHs5Iftvv9TPboYG'), null);
});

test('page de playlist lue en markdown', () => {
  const md = `# Mes prods
[Tout lire](https://www.youtube.com/watch?v=aaaaaaaaaaa&list=PLx)
1. [![](https://i.ytimg.com/vi/aaaaaaaaaaa/hq.jpg)](https://www.youtube.com/watch?v=aaaaaaaaaaa&list=PLx&index=1)
   [3:12](https://www.youtube.com/watch?v=aaaaaaaaaaa&list=PLx&index=1)
   [[FREE] Ninho Type Beat "Lune"](https://www.youtube.com/watch?v=aaaaaaaaaaa&list=PLx&index=1)
2. [Gazo Type Beat - Nuit](/watch?v=bbbbbbbbbbb&list=PLx&index=2)
3. [Gazo Type Beat - Nuit](https://www.youtube.com/watch?v=bbbbbbbbbbb&list=PLx&index=2)`;
  assert.deepEqual(parsePlaylistPage(md), [
    { id: 'aaaaaaaaaaa', title: '[FREE] Ninho Type Beat "Lune"' },
    { id: 'bbbbbbbbbbb', title: 'Gazo Type Beat - Nuit' },
  ]);
});
