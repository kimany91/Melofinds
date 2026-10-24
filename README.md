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
   La base couvre plus de 60 courants : les grands (trap, drill, plugg, rage,
   boom bap…) et les plus pointus (bedroom, lo-fi sombre / TeamSESH, G59,
   horrorcore, rare phonk, Memphis 90s, trap metal, rap rock, punk rap,
   industrial, trip hop, glitch hop, hip house, grime, Lex Luger, Toronto / OVO,
   chiptune, country trap…). Les courants pointus ne sortent que si on les
   nomme, si on cite un de leurs artistes (FR ou US), ou si l'ambiance colle
   vraiment (« intime, fait maison, mélancolique » → bedroom). Le nom le plus
   précis gagne : « trap metal » ne lance pas de la trap classique.
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
   **Durée minimum** (bouton « Durée ») : 1:00+, 2:00+, 3:00+ ou ta propre durée (`2:20`) ;
   tri « Plus longues » / « Plus courtes ».
   **Tunebat** : quand une prod n'a pas de BPM ou de clé, l'app les cherche sur
   [Tunebat](https://tunebat.com) (prods sorties sur Spotify par leur beatmaker) et
   les affiche **en bleu** (« · Tunebat » / « BPM · TB »). Un résultat n'est gardé que
   s'il colle vraiment (même beatmaker, titre proche ou même durée) : jamais de faux BPM.
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
- Recherche **sans clé** : via les serveurs publics Piped (miroirs libres de YouTube),
  avec bascule automatique si l'un tombe. En octobre 2026, ils donnent les vidéos,
  les vues, la date et le début de la description ; la description complète et les
  likes sont souvent bloqués par YouTube (l'app le signale dans la fiche de la prod).
- Facultatif : une clé YouTube Data API v3 gratuite (collée dans l'app, gardée dans
  ton navigateur) pour lire toutes les descriptions et les likes. Quota : environ
  25 recherches par jour et par clé.

## Écoute téléphone verrouillé (version web)

Sur mobile : commandes sur l'écran verrouillé quand le téléphone les propose, tentative
de relance si le téléphone coupe la prod, reprise au retour sur l'appli et prod suivante
de la liste à la fin. Le lecteur YouTube intégré est souvent coupé par le téléphone quand
l'écran se verrouille (YouTube réserve l'écoute en arrière-plan à son abonnement).

## Rec : rapper sur la prod (version web)

Bouton **Rec** dans la barre de lecture (ou « Rec dessus » dans la fiche d'une prod) :
la prod repart du début (décompte 3 s en option) et le micro enregistre ta voix, comme
un dictaphone. Chaque prise retient où elle commence dans la prod : à la réécoute, la voix
repart calée sur la prod (réglage fin du calage si besoin). Les prises restent dans le
navigateur (onglet **Recs**) et se téléchargent. Conseil : mets des écouteurs.

Qualité : la voix est enregistrée **brute et sans perte** (échantillons PCM copiés tels
quels par un AudioWorklet, stockés en WAV 24 bits), micro sans anti-écho, sans réduction
de bruit et sans gain automatique. L'anti-écho reste en option pour enregistrer sans
écouteurs, mais il abîme la voix. Le volume de la voix (jusqu'à 300 %) passe par un
limiteur qui ne touche que les crêtes au-dessus de -1 dB : pas de compression, pas de
souffle remonté. La réécoute et le .wav téléchargé sont calculés de la même façon.

## Télécharger les prods sur ton PC (même loin de chez toi)

Installateur Windows : **MelofindsSetup.exe**
(https://github.com/kimany91/Melofinds/releases/latest/download/MelofindsSetup.exe),
un installateur standard (Inno Setup, `pc/installer.iss`) : il demande où installer le
programme, où arrivent les prods et (facultatif) le code du téléphone, copie le programme
et ses outils (yt-dlp, ffmpeg, Deno — inclus, rien n'est téléchargé après coup), crée les
raccourcis bureau + menu Démarrer, propose le lancement avec Windows et s'inscrit dans
« Applications installées » avec un désinstalleur standard.

Antivirus : pour éviter les fausses alertes, le programme est construit en dossier (pas
d'exe qui s'auto-extrait), avec un lanceur PyInstaller recompilé, sans UPX, avec icône et
informations de version ; il n'utilise ni script caché, ni PowerShell, ni `taskkill`. La
construction analyse l'installateur avec Windows Defender avant de le publier.

Le raccourci ouvre le **panneau de gestion** (avec un bouton « Ouvrir Melofinds Web » qui
ouvre le site dans Chrome) :
- **Accueil** : « Mettre en ligne » / « Mettre hors ligne », dernières prods reçues ;
- **Appareils** : téléphones appairés (nom, type, dernière activité), ajouter avec le
  code d'appairage, renommer, retirer ;
- **Dossier & réglages** : dossier des projets, emplacement du programme, journal,
  mises à jour, désinstallation (les prods restent dans leur dossier).

- Nom du fichier : `Titre [Clé, BPM] [Licence].wav`, avec la licence lue par l'app :
  `[FFP]` (free for profit), `[F]` (free) ou `[FFP, UPTO 5000]` ; le titre YouTube est
  nettoyé de ses « FREE », « free for profit », « FFP »…
- Clé ou BPM manquants : le PC les cherche sur Tunebat et les range à part dans le nom :
  `Titre [C# min] [TB 150 BPM] [FFP].wav`, `Titre [TB C# min, 150 BPM].wav`. Ce que tu as
  précisé ou ce que dit la description passe toujours avant Tunebat. FLmake utilise aussi
  ces valeurs (BPM du projet, clé de Graillon) et le panneau les affiche en bleu.
- Sécurité : envois signés (HMAC-SHA256, clé qui ne passe jamais par ntfy) ; un envoi ne
  contient qu'un identifiant de vidéo ; seul un vrai .wav entre dans l'unique dossier
  choisi sur le PC ; 15 min max par vidéo, 40 par heure, envois de plus de 48 h refusés.
- **Reconnexion automatique** : le PC reste en ligne quand tu fermes le panneau, quand tu
  redémarres l'ordinateur (lancement avec Windows, toujours inscrit), après une mise à jour
  et après un souci réseau ou une coupure de veille (il se réannonce au téléphone). Il ne
  reste hors ligne que si tu appuies sur « Mettre hors ligne » dans le panneau (retenu,
  même après un redémarrage). Une erreur sur une prod ne l'arrête jamais.
- Mises à jour : bouton « Mettre à jour le PC » dans l'app, « Vérifier maintenant » dans le
  panneau (et vérification quotidienne). L'installateur arrête le programme le temps de
  remplacer ses fichiers puis le remet en ligne, même si l'installation échoue ; lancée
  depuis le panneau, celui-ci se rouvre tout seul. Journal : `updates/installation.log`.
  Le programme n'accepte que les versions publiées sur ce dépôt
  (`releases/latest/download/version.json`, empreinte SHA-256 vérifiée).
- Construction : `.github/workflows/pc-build.yml` (Windows) teste, construit le programme
  et l'installateur, fait une vraie installation + désinstallation, une vraie **mise à jour**
  depuis la dernière version publiée (panneau ouvert, puis fermeture du panneau, plantage,
  redémarrage, « Mettre hors ligne »), l'analyse avec Windows
  Defender et publie la version `pc-v<VERSION>`. Pour publier une mise à jour : changer `VERSION` dans
  `pc/mf_core.py` et pousser.
- Code : `pc/` (`melofinds_pc.py` point d'entrée, `mf_core.py`, `mf_worker.py`,
  `mf_install.py`, `mf_gui.py`, `installer.iss`) · tests : `npm run test:pc`.

## Le panneau Melofinds PC

Même style que Melofinds Web, avec un menu à gauche :

- **Accueil** : en ligne / hors ligne, et la **barre de téléchargement** de la prod qui
  arrive (recherche, téléchargement en %, conversion en WAV, projet FL, prods en attente),
  puis les dernières prods reçues.
- **Mes projets FL** : tous les projets du **dossier des projets** (un seul dossier : il
  n'y a plus de dossier des prods à part). Chaque prod reçue y arrive dans son propre
  dossier, avec son projet FL :
  `Titre [C# min, 150 BPM] [FFP]/Titre [C# min, 150 BPM] [FFP].wav` et `….flp`.
  Les projets sont des **cartes encadrées** dans leur couleur, avec leur icône : chaque
  projet a une couleur automatique, et **« Icône et couleur… »** (clic droit) en choisit
  une parmi 12 couleurs et 18 icônes (le style suit le projet quand on le renomme).
  Clé, BPM, instru, date ; recherche, **favoris ★**, **ouvrir dans FL** (crée le projet
  FLmake s'il n'y a encore que la prod), écouter l'instru, ouvrir le dossier, et
  **renommer** : le dossier du projet et tous les fichiers qui portent son nom (prod,
  projet, sauvegardes, exports) prennent le nouveau nom, et les chemins enregistrés dans
  les projets FL suivent (tout ou rien : en cas de problème, tout est remis comme avant).
- **FLmake**, **Appareils**, **Réglages**.

Une prod déjà reçue n'est « déjà sur ton PC » que si son fichier y est encore : supprimée
ou déplacée, elle est retéléchargée quand tu la renvoies.

## FLmake : un projet FL Studio prêt pour chaque prod (Melofinds PC)

Onglet **FLmake** du panneau Melofinds PC. Une fois activé, pour chaque prod reçue :

1. Melofinds PC copie **ton preset de voix** : un projet modèle FL que tu fais une
   fois (insert 2 : ton preset de voix avec Graillon et ton micro en entrée ; piste du
   haut « INSTRU » reliée à l'insert 1, piste « VOICE » à l'insert 2).
2. Il met le **BPM** de la prod, pose **l'instru au début de la piste « INSTRU »**
   (sinon la piste du haut ; clip à la bonne longueur, canal « clip audio » créé
   s'il n'y a pas déjà un son sur cette piste) et **enregistre le projet dans le
   dossier de la prod**, à côté du .wav, comme une sauvegarde FL
   (`Titre [C# min, 150 BPM] [FFP]/Titre [C# min, 150 BPM] [FFP].flp`). Une prod venue
   d'ailleurs (bouton « Tester ») est copiée dans son nouveau dossier de projet.
3. Il **ouvre FL Studio** sur le projet (une seule fois si plusieurs prods arrivent
   d'un coup). Le script **Melofinds FLmake** règle alors **Graillon sur la clé de la
   prod** et sauvegarde.

Le projet est modifié directement dans le fichier `.flp` (`pc/mf_flmake.py`) : seuls
le tempo, le titre, le canal de l'instru et son clip changent, le reste du modèle est
recopié octet pour octet. Formats vérifiés sur de vrais projets FL 20, FL 25 et FL 2026
(relus avec PyFLP et flpkit) : clips de 32 / 60 / 80 octets selon la version, événement
172 sur 1 octet depuis FL 25, tempo absent quand il vaut la valeur par défaut. Le script FL a besoin d'un port MIDI
(FL Studio ne lance ses scripts que sur un port MIDI) : loopMIDI (gratuit) + « Controller
type : Melofinds FLmake » dans les réglages MIDI de FL, une seule fois. Sans lui, tout le
reste marche ; seule la clé de Graillon est à régler à la main (elle est dans le nom).

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
src/core/tunebat.js    clé / BPM manquants via Tunebat (choix strict du bon morceau)
src/core/filter.js     filtres, tris, recherche dans les descriptions
src/search.js          orchestration de la recherche
src/youtube/           sources : API officielle, pages YouTube, démo
public/                interface (HTML/CSS/JS, sans framework)
```
