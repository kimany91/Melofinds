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

## Lancer l'app

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
