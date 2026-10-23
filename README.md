# Melofinds 🎛️

Moteur de recherche de prods YouTube pour rappeurs. Tu décris la prod que tu veux,
l'algo trouve les type beats, **lit toute la description de chaque vidéo** et te dit
si tu peux vraiment sortir ton son sur Spotify sans payer.

## Ce que fait l'algo

1. **Comprend ta description** : « rapide, énergique et musicale » → ambiances
   (rapide, énergique, mélodique) → courants de rap (Melodic bounce, Jerk, Rage)
   → artistes US « type beat » (Lil Uzi Vert, Nettspend, Playboi Carti…) → plage
   de BPM conseillée → requêtes YouTube. Tout est affiché dans
   « 🧠 Ce que l'algo a utilisé ».
2. **Cherche sur YouTube** et récupère la **description complète** de chaque vidéo.
3. **Vérifie la licence dans la description** (la description fait foi, pas le titre) :
   | Catégorie | Ça veut dire |
   |---|---|
   | ✅ **Free for profit** | Sortie sur Spotify & co sans payer (souvent avec crédit) |
   | ⏳ **Up to** | Free for profit jusqu'à X streams (ex. « Up to 5K streams »), ensuite licence |
   | 🎧 **Free** | Gratuit pour YouTube/SoundCloud seulement, payer pour Spotify |
   | 💸 **Payant** | Lease / exclu à acheter, ou prod déjà vendue |
   | ❓ **Inconnu** | Rien de clair |

   ⚠️ **Titres trompeurs** : si le titre dit « FREE FOR PROFIT » mais que la
   description dit « for Spotify you need to buy a lease », « Spotify ❌ »,
   « YouTube only », « DM me before releasing »… la prod est **retirée de
   Free for profit** et signalée.
4. **Range et filtre** : cases de licences, limite « Up to » minimum, crédit
   obligatoire, tri/filtre **BPM** (à activer), style de rap, et **recherche dans
   les descriptions** (`spotify`, `wav`, `"free for profit"`, `-lease` pour exclure).
5. **S'adapte à l'appareil** : sur mobile, recherche plus légère (moins de requêtes
   et de données), mise en page compacte, ouverture dans l'appli YouTube. Sur PC,
   recherche plus complète, grille de cartes et lecteur intégré.
6. **Historique & favoris** : chaque demande est gardée avec les requêtes
   utilisées. ⭐ pour la mettre en favori et la relancer en un clic. 💾 pour
   garder une prod.

## L'ouvrir dans Claude (sans rien installer)

Une version de Melofinds est publiée comme page dans Claude : elle s'ouvre
dans le navigateur, sur PC comme sur mobile.

- **Recherche** : tu décris ta prod, tu cliques « Lancer » → la page cherche
  les type beats sur YouTube, ouvre chaque vidéo, lit sa description et
  t'affiche les liens rangés : Free for profit, Up to, Free, Payant, titres
  trompeurs. Elle passe par le connecteur gratuit **Parallel Search**
  (à brancher une fois dans claude.ai → Paramètres → Connecteurs).
- **Vérifier** : colle le titre et la description d'une vidéo → verdict immédiat.
- **Ma liste** : les prods gardées, triées par licence, BPM et style, avec
  recherche dans les descriptions.
- **Historique & favoris** : gardés dans ton compte Claude.

Le code de cette page est dans `artifact/` ; `npm run build:artifact`
produit `dist/melofinds.html` (même moteur que l'appli, tout en un fichier).

## Version web (pour écouter les prods dans l'app)

La page Claude interdit tout lecteur vidéo. La version web n'a pas cette limite :
un clic sur une prod lance le son dans la page (lecteur YouTube caché + mini-barre),
avec toujours un bouton « YouTube » pour ouvrir la vidéo.

- Adresse : https://kimany91.github.io/Melofinds/
- Fichier : `docs/index.html` (généré par `npm run build:artifact`)
- Mise en ligne (une fois) : GitHub → Settings → Pages → « Deploy from a branch »
  → choisir la branche qui contient `docs/` et le dossier `/docs` → Save.
- Recherche : YouTube Data API v3 avec ta clé gratuite (collée dans l'app, gardée
  dans ton navigateur). Chaque recherche lit la description complète de toutes les
  vidéos. Quota : environ 25 recherches par jour et par clé.

## Lancer l'app complète (recherche YouTube automatique)

Il faut [Node.js](https://nodejs.org) 18 ou plus. Aucune dépendance à installer.

```bash
npm start                      # http://localhost:3000
```

### Source des vidéos

- **Avec une clé YouTube Data API** (recommandé, plus fiable) :
  ```bash
  YOUTUBE_API_KEY=AIza... npm start
  ```
  Clé gratuite sur <https://console.cloud.google.com> → « YouTube Data API v3 ».
  Quota gratuit : ~100 recherches YouTube par jour (une recherche Melofinds
  en utilise 3 à 8 ; les résultats sont mis en cache 6 h). Tu peux aussi coller
  ta clé dans ⚙️ Réglages de l'app.
- **Sans clé** : l'app lit directement les pages YouTube. Plus lent, et peut
  casser si YouTube change ses pages.
- **Démo** (prods fictives, pour tester l'interface) :
  ```bash
  npm run demo
  ```

Pour l'ouvrir sur ton téléphone : lance le serveur sur ton PC et ouvre
`http://<ip-de-ton-pc>:3000` depuis le téléphone (même Wi-Fi).

## Tests

```bash
npm test
```

## Organisation du code

```
server.js              serveur HTTP + API /api/search
src/core/license.js    lecture des descriptions → catégorie de licence, titres trompeurs, infos clés
src/core/planner.js    description → ambiances → courants → artistes → requêtes
src/core/genres.js     base de connaissances (courants, artistes US, BPM)
src/core/bpm.js        BPM et tonalité
src/core/filter.js     filtres, tris, recherche dans les descriptions
src/search.js          orchestration de la recherche
src/youtube/           sources : API officielle, pages YouTube, démo
public/                interface (HTML/CSS/JS, sans framework)
```
