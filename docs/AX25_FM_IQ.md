# IQ original → FM → AFSK1200 → AX.25

L'analyse IQ automatique essaie désormais une chaîne FM étroite / AFSK1200.
Elle utilise les bandes détectées, sans fréquence, décimation ou cadence
AFSK à fournir manuellement. Les trames acceptées ont un FCS CRC-16/X-25
correct et des adresses/champs de contrôle conformes au profil pris en charge.
Les modes de contrôle ambigus restent des hypothèses.

## Référence IQ publique

La [page du fichier](https://www.sigidwiki.com/wiki/File:APRS_IQ_145070kHz_IQ.zip)
de Signal Identification Wiki référence un enregistrement publié par
Cartoonman le 20 août 2015, sous l'étiquette APRS. La source ne fournit pas de
paquets de référence ni de nombre attendu. Les cinq trames actuellement
validées sont trois trames I et deux RR ; aucune position APRS n'en est déduite.
Cette observation ne décrit pas tous les paquets éventuellement présents.

| Élément | Valeur vérifiée |
|---|---|
| ZIP source | `APRS_IQ_145070kHz_IQ.zip`, 622 860 octets |
| SHA-256 ZIP | `72342eb27b8b8bd1df53f3eda6f4d159a5c279596f2641f192bcdc2bda7cd034` |
| Membre | `SDRSharp_20150819_190253Z_145070kHz_IQ.wav` |
| WAV | 2 937 356 octets, PCM signé 16 bits, deux canaux interprétés I puis Q |
| SHA-256 WAV | `0df449836168ab3d6e3f470910e6401b5ad8a14a9310871239a0ad220d36cc50` |
| Échantillonnage déclaré | 39 062 éch/s ; 734 328 échantillons complexes |
| Durée lue | 18,799037427679075 s |
| Centre RF dans l'en-tête | Absent : fréquences relatives à la capture |

Les indications de date et de fréquence du nom ne sont pas appliquées comme
métadonnées mesurées. L'origine IQ est celle annoncée par le déposant ; le
matériel de réception, la calibration d'horloge et l'identité des stations
ne sont pas vérifiés indépendamment.

Le ZIP emploie Deflate64, méthode 9, absente du décompresseur ZIP standard
de Python. Le script de référence utilise 7-Zip, ou Info-ZIP compilé avec
`USE_DEFLATE64`. La taille et le SHA-256 du ZIP sont contrôlés avant d'appeler
l'outil ; le CRC du membre, sa taille et son SHA-256 sont contrôlés ensuite.
Les budgets restent de 2 Mio téléchargés et 4 Mio pour le membre choisi.
Aucune extraction de chemins contenus dans le ZIP n'est effectuée : les
octets du seul WAV sont écrits dans un fichier de travail au nom fixe.

`python scripts/aprs_iq_reference.py` télécharge cette source épinglée et
appelle le même import `analyze(..., seconds=20)` que le produit. `--offline`
réutilise le ZIP après les mêmes contrôles ; `--cache-root` choisit le cache.
Le ZIP et le WAV source ne sont ni incorporés au dépôt ni inclus dans
l'artefact de référence. La licence spécifique du fichier n'est pas établie
par ce contrôle.

Les octets complets et le nombre de cinq trames servent de régression de
développement, issus des réceptions à FCS valide. Ils ne sont pas des données
de référence publiées indépendamment par l'auteur. Les stations décodées
incluent `N2RQ-9`, `K2YYD-10` et `W2KPQ`, avec les SSID et relais conservés.

## Frontal FM automatique

`iqscope_afsk_fm.search_afsk_fm` traite les IQ complexes de 20 kéch/s à
2,4 Méch/s, sur au plus 20 secondes et huit millions d'échantillons.
Au plus huit cibles sont essayées : bandes de 2 à 24 kHz, par SNR décroissant,
avec une cible de bande de base si l'entrée ne dépasse pas 96 kéch/s et si
aucune cible proche n'existe. Les bandes trop larges ou différées sont comptées.

Pour chaque cible :

1. Translation complexe vers zéro puis décimation entière vers au plus
   48 kéch/s, avec filtrage anti-repliement.
2. Filtre FIR de canal, coupure au plus 8 kHz, puis discriminateur quadrature
   `f[k] = Fs/(2π) * arg(z[k+1] * conj(z[k]))`.
3. Retrait de la médiane du discriminateur sur les échantillons retenus.
   Une porte d'énergie, à 1 % du percentile 99 du canal, supprime les niveaux
   trop faibles. Cette médiane donne une estimation de décalage, pas une
   mesure indépendante de fréquence RF.
4. Filtre audio au plus 3,4 kHz et rééchantillonnage proche de 12 kéch/s.
   Le débit effectif obtenu par le rapport rationnel est conservé pour
   l'estimation AFSK, au lieu de supposer un débit exactement nominal.
5. Récupération AFSK existante : fits de transitions autour de 1200 bauds,
   phases nominales, NRZI/NRZ, débourrage HDLC puis FCS et contrôle de structure.

Les FIR et rééchantillonnages compensent leur retard linéaire, avec extension
par zéros aux limites. Le discriminateur se rapporte au milieu de deux
échantillons : son origine temporelle ajoute `0,5/Fs_canal`. Les temps de
trame restent relatifs au premier IQ. Les diagnostics d'horloge internes se
rapportent à l'audio démodulé, avec cette origine explicitement exportée.

Les huit canaux partagent un budget de 6000 couples de fanions et 128 trames.
Une part du budget est réservée à chaque canal restant. Les doublons proches
en temps et en fréquence sont éliminés ; les répétitions séparées restent
présentes. Le contrôle de cette capture atteint le budget de fanions :
**cinq trames acceptées ne constituent pas un décompte exhaustif du fichier**.
Les essais peuvent manquer des salves faibles, adjacentes, chevauchées ou
incomplètes. Ni poursuite continue, ni désenchevêtrement, ni correction de bits
ne sont ajoutés. Le frontal ne dépend pas du sélecteur heuristique d'audio FM.

## UI, I, S et U : portée de l'interprétation

Référence primaire : [AX.25 v2.2, TAPR, juillet 1998](https://files.tapr.org/tech_docs/AX25/AX25.2.2.pdf),
sections 3.3–3.5 et 4.2–4.3. Les contrôles I/S ont un ou deux octets selon
le mode ; un PID concerne uniquement I et UI. Un enregistrement débutant au
milieu d'une connexion ne fournit pas nécessairement le mode négocié.

Le chemin RF active une inspection bornée I/S/U. Le décodeur UI historique
reste strict par défaut ; `allow_link_frames=True` active explicitement ce
profil sur des bits et `accept_link_frames=True` dans le récepteur audio interne.

- **UI** : les champs PID et information restent sélectionnés comme auparavant.
  L'interprétation APRS demeure limitée à UI de PID `0xf0`.
- **I** : les deux découpages possibles, modulo 8 et modulo 128, sont conservés
  s'ils respectent les longueurs. Les numéros N(S)/N(R), bit P/F, PID, octets
  et texte éventuel sont des candidats. Aucun PID ni contenu applicatif n'est
  sélectionné au niveau de la trame. Les PID échappés restent non interprétés.
- **S** : RR/RNR/REJ/SREJ simples, contrôles d'un ou deux octets sans liste
  d'information. La longueur établit le découpage de cette trame, sans établir
  l'état de la connexion ni modifier l'interprétation d'autres trames.
- **U** : noms des contrôles SABM/SABME/DISC/UA/DM/FRMR/XID/TEST, longueurs
  bornées et information de liaison brute lorsque permise. Aucun échange de
  négociation n'est reconstruit. Les listes SREJ et détails XID/FRMR sont hors profil.

Le profil accepte aussi les courtes trames S/U de 17 octets, FCS inclus,
qui n'ont pas de PID. Il conserve les règles d'adresses, au plus dix adresses,
les limites d'information et les contrôles CRC existants. Il ne transforme
pas un mauvais CRC en contenu candidat. Les copies I ne sont ni réordonnées
en session, ni concaténées en message ou en fichier.

## Interface et sorties

La bande détectée porte le résultat FM/AFSK et le nombre de trames à FCS valide.
La liste montre adresses, types de liaison, hypothèses I et limites de recherche.
Les fréquences sans centre RF connu sont explicitement relatives. Les cinq
trames de cette capture ne produisent ni position APRS ni télémétrie.

- `fm-afsk-frames.json` : résultat, provenance des canaux et diagnostics.
- `fm-ax25-frame-N.bin` : octets complets reçus, adresses/contrôle/FCS inclus,
  après débourrage HDLC ; les fanions ne sont pas inclus.
- `fm-ax25-payload-N.bin` : uniquement les informations des trames UI dont
  le découpage est établi. Aucun tel fichier n'est fabriqué pour une trame I ambiguë.
- `report.json` : rapport global, références des trames associées à leur bande.

La CI vérifie le WAV original, ses cinq trames, les FCS recalculés, le JSON et
les binaires. Chromium vérifie l'import IQ sans métadonnées saisies, le choix
de la bande, les hypothèses visibles, l'absence de faux contenu APRS et les
téléchargements. Les tests synthétiques couvrent également des positions UI
sur FM, les canaux multiples, les temps source, les cadences décalées, les
négatifs et les budgets. Les preuves sont publiées dans `browser-checks`.
