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
   La lecture se fait phrase par phrase : « A license must be purchased to use for
   profit (Spotify, Apple Music…) », « free for profit for YouTube or SoundCloud
   placement », « youtube monetization only », « only applies to YouTube », « usage
   non lucratif », « this beat is not free »… Une pub pour la lease (fichier sans tag,
   exclu, « je conseille d'acheter ») ne retire pas une prod de Free for profit.
   Si seul le titre dit « free for profit » et que YouTube n'a donné que le début de
   la description, la prod est marquée **« FFP ? à vérifier »** et rangée dans « À vérifier » (plus dans Free for profit). La date de version est affichée en bas de la page de recherche.
   Testé sur ~60 vraies descriptions YouTube / SoundCloud (`test/fixtures/real-licenses.json`).
   **Descriptions cachées par YouTube** (mode sans clé, chaîne d'un beatmaker…) : si
   Melofinds PC 3.18+ est connecté, l'app les lui demande ; il lit la page YouTube depuis
   ta connexion et les renvoie, et le verdict se met à jour tout seul.
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
- **Licence revérifiée par le PC** (3.17) : il lit la description complète avec yt-dlp.
  Si elle limite à YouTube / SoundCloud, exige une licence pour Spotify & co ou parle
  d'usage non lucratif, la prod est rangée en `[F]` même si l'app disait free for profit
  (titre « FREE FOR PROFIT », description que YouTube lui avait cachée). Une prod que l'app
  n'avait pas pu lire passe en `[FFP]` si la description le dit clairement.
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

## Bouton « BPM » : BPM et clé à l'écoute (version web)

Chaque prod a un petit bouton **BPM**. Il ouvre « BPM et clé » :
- **Sans son, sans PC** — **noTube** : « 1. Télécharger le MP3 » ouvre noTube
  (notube.lol, gratuit, sans compte ni installation) sur la prod, avec son astuce officielle
  (lien `notube.lol/watch?v=…`) ; de retour dans Melofinds, « 2. Analyser le MP3 » : tu choisis
  le fichier, il est analysé sur le téléphone, puis tu peux le supprimer (le BPM et la clé
  restent). Un site n'a pas le droit d'en piloter un autre : ces deux appuis sont nécessaires ;
- **Sans son** — **Analyser la copie du PC** : pour une prod envoyée sur le PC, la copie
  d'écoute gardée sur le téléphone est analysée sans rien jouer, même PC éteint. Chaque
  copie qui arrive du PC est d'ailleurs analysée toute seule (une à la fois) ;
- **Sans son** — **Choisir un fichier audio** : MP3, WAV, M4A… (souvent en téléchargement
  gratuit dans la description ; 45 s analysées au milieu du morceau) ;
- **Avec le son** — **Écouter la prod** : l'app fait jouer la prod 15 secondes (au cœur du
  morceau) et l'écoute au micro (son monté, sans écouteurs). Téléphone muet : l'app le dit
  et propose les deux façons sans son.

Le son du lecteur YouTube, lui, n'est pas lisible par un site (YouTube l'interdit) : sans
son ni fichier ni copie, il faut passer par le micro.

L'analyse se fait **sur le téléphone**, sans service extérieur ni PC
(`src/core/audiokey.js`), et marche pour toutes les prods, sorties ou non sur Spotify :
- **BPM** : force des attaques (kick, snare, hi-hats), puis la période qui revient le plus,
  vérifiée sur les subdivisions (croches, doubles croches). Moitié / double ne se distinguent
  pas au son (une trap à 150 en demi-temps = un son à 75) : la valeur « prod » (85-175) est
  donnée, l'autre en « ou … ».
- **Clé** : batterie écartée (séparation harmonique / percussive), notes des pics du
  spectre, accordage détecté (samples pitchés), gamme puis tonique (profils de
  Krumhansl-Kessler et Temperley, basses / 808, préférence mineur). La relative est donnée
  (« mêmes notes que … ») ; « clé à confirmer » si le son est peu net.

Testé sur des prods de synthèse au BPM et à la clé connus (808, kick, snare, hi-hats,
accords, mélodie), en son propre et en « haut-parleur de téléphone capté au micro », avec
accordage décalé et bruit : BPM juste (ou en alternative) 80 fois sur 80, clé 78 fois sur
80 (les 2 erreurs marquées « à confirmer »). Sur de vraies prods, c'est une estimation :
la description du beatmaker reste prioritaire. Les résultats s'affichent **en bleu**
(« 150 BPM · ≈ ») et restent gardés dans ce navigateur. La fiche garde aussi un lien
« Vérifier sur Tunebat ».

## Mini-jeu pendant la recherche

Pendant qu'une recherche charge (web et APK), un petit jeu façon dinosaure de Chrome :
tu es une note 🎵 qui saute (toucher, espace ou flèche du haut) par-dessus des barres
d'égaliseur ; plus loin, des bémols ♭ volent (reste au sol dessous). La vitesse monte, le
record est gardé. Le jeu se ferme dès que la recherche est finie (partie en cours ou
non ; le record est gardé). ✕ pour le fermer avant.

## App Android (APK)

La même app que la version web, plus ce que seul Android permet. Lien :
**https://github.com/kimany91/Melofinds/releases/download/apk/Melofinds.apk** (aussi en
bas de la page de recherche). Elle affiche l'app web de GitHub Pages : les nouveautés
arrivent **sans réinstaller** ; hors connexion, un écran « Pas de connexion ».

- **BPM et clé tout seuls, en quelques secondes** : toucher « BPM » sur une prod (ou
  ouvrir sa fiche) suffit. Le téléphone récupère lui-même le son de la vidéo YouTube avec
  **NewPipe Extractor** (la bibliothèque libre et gratuite de l'appli NewPipe), le
  télécharge en 4 morceaux à la fois, le décode avec le décodeur d'Android, garde 45 s au
  milieu (mono, petit WAV dans le cache de l'app), l'analyse et l'efface. Rien à
  télécharger soi-même, rien dans les fichiers du téléphone, pas de site intermédiaire.
  Si YouTube refuse (vidéo privée, trop de demandes…), la fenêtre BPM s'ouvre avec noTube.
  Code : `YtAudio.java` (sans Android, testé sur ordinateur par `YtAudioTest`),
  `AudioPcm.java` (décodage), `ytAudio` dans le module natif.
- **Avec noTube (secours)** : dans la fenêtre BPM, « Autoriser l'accès aux sons
  téléchargés » (une seule fois : autorisation « Musique et audio » d'Android — le
  sélecteur de dossiers d'Android interdit de choisir Téléchargements depuis Android 11),
  puis « 1. Télécharger le MP3 (noTube) ». De retour dans Melofinds, l'app trouve le MP3
  dans Téléchargements, le relie à la prod (titre, puis durée), l'analyse et **le
  supprime** (interrupteur, activé par défaut). Android demande de confirmer chaque
  suppression, sauf si « Gestion des fichiers multimédias » est autorisée pour Melofinds
  (lien direct dans la fenêtre BPM).
- **Partager → Melofinds** : un son partagé depuis noTube, Fichiers… est relié à la prod
  (sinon l'app demande laquelle) et analysé ; la copie est effacée ensuite.
- **Retour haptique** léger sur chaque action (selon le réglage « vibrations » du
  téléphone), plus marqué quand le BPM est trouvé. La version web Android vibre aussi.
- **Sécurité** : le son YouTube direct ne va que dans le cache de l'app (effacé après
  analyse, restes effacés au bout de 10 min) ; identifiant de vidéo vérifié ; 25 Mo max.
  Permissions Internet, micro et « Musique et audio » (jamais photos,
  vidéos ni accès à tous les fichiers) ; l'app ne lit que des sons rangés dans
  Téléchargements, et ne supprime qu'un son de Téléchargements qu'elle vient d'analyser et
  qui correspond à la prod, par la demande officielle d'Android.
- Code : `android/` (Capacitor 8, module natif `MelofindsNativePlugin.java`),
  `capacitor.config.json`, `apk/www` (écran hors connexion), construction
  `.github/workflows/apk-build.yml` (version GitHub « apk », jamais « dernière »).
  Signature : clé jamais dans le dépôt ; avec les secrets `APK_KEYSTORE_B64` et
  `APK_KEYSTORE_PASSWORD`, les mises à jour de l'APK s'installent sans désinstaller.

## Chaîne du beatmaker (version web)

Chaque prod affiche le **logo de la chaîne** qui l'a postée. Un appui dessus lance le
**mode chaîne** : **toutes** les vidéos de ce beatmaker, sans les filtres de la recherche
(titres sans « type beat » compris, toutes licences cochées, pas de filtre BPM / durée /
vérifiées). Licences toujours vérifiées ; filtre texte, cases de licences (propres à la
chaîne) et tris restent dispo, dont **« Plus récentes »**. « Plus de résultats » charge la suite ; le bandeau en haut donne le lien de la
chaîne YouTube et ✕ ramène à ta recherche. Avec une clé YouTube : liste des mises en ligne
de la chaîne (quelques unités de quota seulement) ; sans clé : la page de la chaîne sur Piped.

## Onglet « File d'attente » (version web)

- **En cours** : la prod que le PC télécharge en ce moment ; **En attente** : celles qui
  attendent leur tour (ou que le PC recevra en se rallumant) ; **Dernières arrivées**.
  Un appui sur une prod ouvre **sa fiche** (licence, description, lien de la vidéo YouTube
  d'origine). **✕ annule** une prod en attente : le PC la saute (PC 3.17 ou plus), même si
  l'annulation arrive pendant qu'il télécharge la précédente. « Annuler » dans le message
  la remet dans la file.
- **Sur ton PC** : tous les projets du dossier des projets, en cartes à leur couleur et
  avec leur icône. Clé / BPM (en bleu si trouvés avec Tunebat), licence, favori ★.
  **Renommer** (tout le projet, comme dans le panneau du PC), **Icône et couleur**.
- **Écouter** l'instru et tous les sons du projet. Les noms avec une version (`0.1`,
  `v2`, `1.3.3`…) sont triés par version, la plus récente est marquée « dernière ».
  Le PC envoie une copie d'écoute légère (AAC 96 kb/s, ~2 Mo pour 3 min), découpée en
  pièces jointes ntfy.sh de 1,9 Mo.
- **Toujours à jour** : le PC envoie la liste de ses projets dès qu'il se met en ligne,
  à chaque changement (nouveau projet, renommage, nouvelle version… pas les sauvegardes
  auto de FL), et une dernière fois quand il s'arrête. Chaque nouveau son exporté dans
  un projet (« Haze 1.4.wav ») part tout seul en copie d'écoute. Quand Windows s'éteint,
  le téléphone est prévenu tout de suite (« PC éteint »).
- Versions reconnues : `0.1`, `1.3.3`, `v2`, `version 3`, `Haze_2` (nouvelle version de
  FL), dans le dossier du projet et ses sous-dossiers (.wav, .mp3, .flac, .m4a…).
- **Sons gardés sur le téléphone** : la **dernière version** de chaque projet (sinon son
  instru) arrive toute seule sur le téléphone, sans rien demander : le téléphone dit au
  PC ce qui lui manque, le PC l'envoie petit à petit (copie d'écoute AAC 64 à 96 kb/s,
  une seule pièce jointe pour une prod de 3 min). Une barre « 12 / 30 sons sur ce
  téléphone » suit l'avancement ; chaque carte dit « ✓ Écoutable hors ligne ». Les
  autres versions s'écoutent à la demande quand le PC est allumé.
- **« Vider et retélécharger »** (PC allumé et en ligne seulement, avec confirmation) :
  efface tous les sons gardés sur le téléphone (toutes les versions), puis le PC renvoie
  seulement la dernière version de chaque projet. Rien n'est effacé sur le PC.
- **PC éteint** : la liste des projets et les sons gardés (200 au plus) restent sur le
  téléphone : tout se voit et s'écoute. Un renommage, un style ou un favori fait PC
  éteint part dès qu'il se rallume.
- PC trop ancien (avant 3.11) : l'onglet le dit, avec un bouton « Mettre à jour le PC ».
- Limites de ntfy.sh (gratuit) : pièces jointes gardées 3 h, 20 Mo par 3 h et ~250
  envois par jour pour le PC ; le PC envoie donc au plus 25 copies d'écoute par heure
  (17 Mo par 3 h), la liste seulement quand elle change (toutes les 3 min au plus) ou
  quand l'app la demande, et se signale toutes les 50 min.
- À désactiver dans Melofinds PC → Réglages → « Écouter et gérer depuis l'app web ».

## Le panneau Melofinds PC

Même style que Melofinds Web, avec un menu à gauche :

- **File d'attente** : en ligne / hors ligne, la **barre de téléchargement** de la prod
  qui arrive (recherche, téléchargement en %, conversion en WAV, projet FL), la liste des
  prods **en attente**, puis les dernières prods reçues.
- **Mes projets FL** : tous les projets du **dossier des projets** (un seul dossier : il
  n'y a plus de dossier des prods à part). Chaque prod reçue y arrive dans son propre
  dossier, avec son projet FL :
  `Titre [C# min, 150 BPM] [FFP]/Titre [C# min, 150 BPM] [FFP].wav` et `….flp`.
  Les projets sont des **cartes encadrées** dans leur couleur, avec leur icône : chaque
  projet a une couleur automatique ; **clic sur l'icône** (ou « Icône et couleur… ») pour
  en choisir une parmi 12 couleurs et 50 icônes (le style suit le projet renommé).
  **Double-clic** : ouvrir dans FL. **Glisser une carte**, comme une icône du bureau de
  Windows : elle suit la souris et les autres se poussent pour lui faire de la place
  (ordre gardé, aussi dans l'app web ; les nouveaux projets arrivent en haut).
  **Lecteur dans chaque carte** : le son principal (dernière version, sinon l'instru,
  sinon ton dernier export) avec ▶ / pause, barre de lecture cliquable et durée ; **▾**
  affiche les autres versions et exports (lecteur de Windows : .wav, .mp3…).
  **Sons créés par FL** mis à part, jamais pris pour l'instru, une version ou le son
  principal : enregistrements au nom automatique (`Projet_2026-09-20 14-12-20_Piste`),
  dossiers Recorded / Rendered / Sliced beats, samples du projet (sons de moins de 3 s ou
  utilisés par le .flp, comme « Basic 808 Clap »). Dans l'app web : « Créés par FL ».
  Chaque carte montre la **durée** de la prod et, pour une prod envoyée depuis l'app,
  **« ▶ Voir la vidéo YouTube »**, qui ouvre la vidéo dans Chrome. Le lien est gardé à
  la réception : écrit dans le .wav lui-même (commentaire, sans réencoder : il suit la
  prod même renommée ou déplacée à la main) et dans les réglages. Pour les prods reçues
  avant, le téléphone envoie au PC les liens qu'il connaît.
  Clé, BPM, instru, date ; **♪ Sons** : l'instru et tous les sons du projet, versions
  (`0.1`, `1.3.3`…) dans l'ordre, à écouter ici ; recherche, **favoris ★**, **ouvrir dans FL** (crée le projet
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
