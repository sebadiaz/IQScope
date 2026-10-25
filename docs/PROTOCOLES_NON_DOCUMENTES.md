# Protocoles propriétaires, documentation partielle et rétro-ingénierie

Version 0.1 — 25 octobre 2026. Complément aux spécifications techniques IQScope.

## 1. Objectif

Étendre la couverture aux protocoles sans spécification officielle publique, aux extensions constructeur, aux variantes anciennes et aux signaux encore inconnus. Une documentation officielle n'est pas une condition d'entrée au catalogue. En revanche, annoncer un décodage exige des observations reproductibles et une validation correspondant exactement à ce qui est compris.

Deux axes de travail : intégrer les connaissances communautaires existantes et développer un moteur d'inférence de structures inconnues. Le premier peut fournir des résultats rapidement ; le second est un programme de recherche avec incertitudes explicites.

Aucune capacité décrite ici n'est encore implémentée dans IQScope. La recherche de sources réalisée pour cette note est une première sélection, pas un audit exhaustif ni une validation sur captures.

## 2. État des connaissances : ne pas mélanger les catégories

| Catégorie | Situation | Traitement |
|---|---|---|
| Public officiel | Standard ou documentation constructeur accessibles | Référence versionnée et tests indépendants |
| Public communautaire | Format reconstitué, code ouvert, captures et notes | Conserver provenance et limites expérimentales |
| Officiel partiel | PHY documentée mais application privée, ou inversement | Supporter chaque couche indépendamment |
| Propriétaire ouvert dans les faits | Format diffusé dans SDK, pilotes ou brevets publics | Vérifier ce qui est réellement décrit et testé |
| Inconnu observable | Captures disponibles sans parseur | Inférence de structure, hypothèses et corpus |
| Protection cryptographique | Trames accessibles mais charge protégée | Afficher les métadonnées et données chiffrées ; clés si fournies |

Les catégories peuvent coexister. Nordic Enhanced ShockBurst possède une documentation fabricant ; des usages applicatifs construits au-dessus peuvent rester propriétaires. Il serait incorrect de présenter l'ensemble de la couche radio Nordic comme non documenté.

## 3. Sources effectivement examinées

Consultation via GitHub le 25 octobre 2026. Les SHA ci-dessous identifient les blobs lus ; les liens de branche peuvent évoluer. Lors de l'intégration, enregistrer aussi le commit, la licence du fichier et une copie référencée du document utilisé.

### 3.1 Capteurs météo Oregon Scientific

Source : [rtl_433/src/devices/oregon_scientific.c](https://github.com/merbanan/rtl_433/blob/master/src/devices/oregon_scientific.c).

Blob examiné : `e2733940792acb8e2d5418f8721b48ed775e9c7a`.

Le code référence une description communautaire et distingue plusieurs identifiants et variantes. Certains identifiants sont explicitement non confirmés, et un même identifiant peut correspondre à des longueurs différentes. On y trouve des conversions de température, humidité, pluie et autres mesures.

Travail IQScope : importer les modes effectivement décodés par la version choisie de rtl_433, conserver le modèle et les preuves, tester les variantes et ne pas transformer les identifiants non confirmés en modèles certains.

### 3.2 Delta Dore X3D

Source : [rtl_433/src/devices/deltadore_x3d.c](https://github.com/merbanan/rtl_433/blob/master/src/devices/deltadore_x3d.c).

Blob : `c102cec6b98917319ea433a476aee5663748f61d`.

Les commentaires annoncent un travail en cours. Ils décrivent une couche FSK/PCM, une structure de paquet, des contrôles et certains champs. Plusieurs significations restent marquées inconnues ou hypothétiques.

Travail : récupération de trames et champs établis, préservation des inconnus, séparation entre observation de code source et confirmation par capture. Ne pas annoncer le support de toute la gamme X3D à partir de ce seul décodeur.

### 3.3 Honeywell CM921 et sous-ensemble Evohome

Source : [rtl_433/src/devices/honeywell_cm921.c](https://github.com/merbanan/rtl_433/blob/master/src/devices/honeywell_cm921.c).

Blob : `e2c3361c367e8e8292bee4c18157acac06341c89`.

Le décodeur se présente comme un sous-ensemble Evohome. Il décrit les transformations de bits, des identifiants et une structure de messages. Certaines associations d'équipements sont incertaines dans les commentaires.

Travail : intégrer le sous-ensemble exact, puis étudier les autres messages à partir de corpus. Évaluer séparément les projets communautaires de la famille RAMSES-II ; leur compatibilité et leur état actuel restent à vérifier.

### 3.4 Somfy RTS

Source : [rtl_433/src/devices/somfy_rts.c](https://github.com/merbanan/rtl_433/blob/master/src/devices/somfy_rts.c).

Blob : `ff3d4a6c5338598cb91603189e60042aa9592f38`.

Le fichier cite une description communautaire et un brevet public. Il décrit framing, codage, champs et particularités de certains clones. Il distingue aussi une valeur seulement rapportée depuis un firmware d'une valeur confirmée sur une capture radio.

Travail : reconnaissance et lecture des trames ; rattachement explicite des particularités à leurs modèles testés. RTS, io-homecontrol et clones ne sont pas interchangeables. Un compteur observé n'implique pas que le système sache prédire les futurs messages ou agir sur un équipement.

### 3.5 Neptune R900

Source : [rtl_433/src/devices/neptune_r900.c](https://github.com/merbanan/rtl_433/blob/master/src/devices/neptune_r900.c).

Blob : `a4c2c85865a252384a316e15e3b618f11f518b75`.

Le fichier cite les travaux de rtlamr et décrit les champs tout en signalant des incertitudes. Point critique : deux familles peuvent partager le même format de trame avec une interprétation binaire ou BCD d'un champ, sans indicateur permettant de choisir dans la trame seule.

Travail : maintenir deux interprétations, demander le contexte de modèle uniquement lorsque nécessaire et ne pas annoncer une valeur physique unique faute de preuve. Les unités et facteurs d'échelle doivent être confirmés par modèle.

### 3.6 TPMS Schrader moto

Source : [rtl_433/src/devices/tpms_schrader_motorcycle.c](https://github.com/merbanan/rtl_433/blob/master/src/devices/tpms_schrader_motorcycle.c).

Blob : `bd709f8f4db9270ca8c54739ee3b1d26c4f9d61f`.

Le commentaire associe références de capteurs, exemples de messages et disposition des champs. L'implémentation calcule pression, température et contrôle d'intégrité.

Travail : valider ces transformations sur vecteurs et captures indépendants ; intégrer chaque variante TPMS séparément. Un capteur d'une autre marque ou génération peut employer une autre PHY ou une autre disposition.

### 3.7 Nordic et usages propriétaires 2,4 GHz

Source : [BastilleResearch/gr-nordic](https://github.com/BastilleResearch/gr-nordic), README consulté.

Le projet fournit un récepteur de paquets Enhanced ShockBurst à partir d'un flux GFSK démodulé et un dissector Wireshark. Il illustre aussi des récepteurs à canal unique ou canalisés. Sa compatibilité avec la version GNU Radio cible doit être testée.

Travail : distinguer la couche ESB de ses payloads applicatifs. Utiliser d'abord des données de laboratoire et des appareils de référence pour étudier les formats applicatifs. Les applications de saisie, commandes et autres contenus privés ne constituent pas un corpus public par défaut.

## 4. Autres familles à explorer, sans prétendre les avoir vérifiées

La présence de fichiers correspondants dans le répertoire `src/devices` de rtl_433 a été constatée pour plusieurs entrées ci-dessous. Cela prouve l'existence d'une implémentation candidate, pas son exhaustivité ni sa réussite dans IQScope.

| Famille | Pistes | Travail nécessaire |
|---|---|---|
| Météo et environnement | Acurite, Fine Offset/Ecowitt, La Crosse, Bresser, Alecto, Hideki | Modèles, générations, checksums et unités |
| Chauffage et domotique | Honeywell, Delta Dore, Danfoss, Vaillant, FS20, Intertechno, LightwaveRF | Messages connus, échanges et extensions |
| Mesure d'énergie | CurrentCost, Efergy, IKEA Sparsnäs, EcoEye, emonTx | Échelles, compteurs, identifiants et variantes |
| Comptage | Neptune, ERT SCM/SCM+/IDM, Badger Orion, Gridstream et autres | Modes, encodages, paramètres de contexte et contenu accessible |
| TPMS | Schrader, Toyota, Ford, Renault, Hyundai et autres profils | Une fiche par variante réellement testée |
| Détecteurs et alertes | Cavius, Kidde, Visonic, systèmes documentés par la communauté | Télémétrie accessible et limites d'interprétation |
| Objets et télécommandes | Somfy RTS/io-homecontrol, X10 RF, prises et stores | Séparer reconnaissance, champs et protection |
| Liaisons intégrées | RFM69 et paquets de bibliothèques embarquées ; CC1101/SiLabs selon profil | Le composant seul ne définit pas le protocole |
| 2,4 GHz propriétaire | ESB, XN297 et variantes de périphériques/jouets | Recherche supplémentaire, corpus et formats applicatifs |
| RC et télémétrie de modèles | Protocoles documentés par communautés, variantes de fabricants | État réel de la documentation et contraintes de hopping |
| Industriel propriétaire | Capteurs et télémétrie avec captures partageables | Corpus par équipement ; ne pas inventer un standard commun |

Les notices réglementaires, brevets, manuels de maintenance, SDK publics, pilotes libres, articles et issues de projets peuvent compléter les captures. Un dossier réglementaire donne souvent la bande et la modulation, rarement toute la sémantique.

## 5. Outils de recherche et leur rôle

### URH

Le [README d'URH](https://github.com/jopohl/urh) décrit démodulation, estimation de paramètres, décodages personnalisés et inférence de champs par règles. C'est une piste pour comprendre et réutiliser des méthodes ; ce n'est pas une preuve de décodage universel automatique.

Lors de la consultation, le dépôt GitHub `jopohl/urh` était marqué archivé. Une adoption doit donc vérifier maintenance, forks éventuels et pérennité. La licence indiquée par GitHub est GPL-3.0 ; examiner les fichiers et obligations avant réutilisation.

### rtl_433

[rtl_433](https://github.com/merbanan/rtl_433) offre de nombreuses implémentations orientées objets ISM et des sources utiles pour les structures de messages. Candidat majeur pour la couverture rapide, mais chaque décodeur a sa propre validation et ses limites.

Privilégier un adaptateur de sortie structurée et un inventaire par version. Le nom rtl_433 n'implique pas une limitation à une seule fréquence, ni la prise en charge de tout ce qui émet dans les bandes ISM.

### WHAD

Le [README WHAD](https://github.com/whad-team/whad-client) présente une bibliothèque et des outils liés à des matériels compatibles pour explorer les protocoles radio. Vérifier chaque domaine et adaptateur avant d'en déduire une capacité d'import IQ générique. Le seul README consulté ne suffit pas à confirmer la couverture détaillée des protocoles.

### Outils complémentaires à évaluer

Inspectrum et SigDigger pour inspection ; outils de recherche de CRC comme CRC RevEng ; dissectors Wireshark pour analyse de trames ; outils de clustering/inférence tels que Netzob selon formats et maintenance. Ces dernières propositions ne sont pas encore auditées dans cette note.

L'utilisation passive et hors ligne est suffisante pour les premiers lots. Les fonctions d'émission, d'injection ou de fuzzing présentes dans certains outils ne sont pas nécessaires au pipeline IQScope et ne sont pas activées par l'adaptateur d'analyse.

## 6. Moteur d'inférence pour protocoles inconnus

### 6.1 Séparer les problèmes

Le moteur travaille successivement sur les frontières de bursts, la modulation, les symboles, le codage de ligne, la structure de trame et les champs. Chaque étape garde plusieurs hypothèses et ses dépendances. Une jolie structure de bits après un mauvais choix de débit ne prouve pas un protocole.

### 6.2 Organisation du corpus

Regrouper des captures par appareil, modèle, firmware et contexte mesuré. Annoter les actions et grandeurs connues sur des équipements de référence : température mesurée, état de capteur ou événement horodaté. Réserver des sessions et appareils entièrement distincts à la validation.

Les observations doivent couvrir des variations réelles. Cent trames identiques ne permettent pas de distinguer un identifiant fixe d'un champ de mesure constant.

### 6.3 Inférence de la structure

- Regrouper les bursts par durée, largeur, débit et similarité de symboles.
- Chercher préambules, mots de synchronisation, répétitions et frontières candidates.
- Comparer les longueurs et aligner les messages en autorisant plusieurs types de trame.
- Calculer variabilité et entropie par position, dépendances entre champs et cohérence entre répétitions.
- Tester des codages de ligne et transformations réversibles connus dans un budget explicite.
- Rechercher longueurs, compteurs, identifiants et contrôles d'intégrité plausibles.
- Conserver les alternatives expliquant les mêmes observations.

La recherche de CRC/checksum doit utiliser des trames de validation non utilisées pour ajuster les paramètres. Documenter l'espace de recherche : une bonne concordance sur quelques messages peut être fortuite.

### 6.4 Inférence des valeurs

Comparer les champs aux mesures de référence, tester entier signé/non signé, endianness, BCD, offsets et facteurs d'échelle plausibles. Vérifier ensuite sur de nouvelles valeurs et de nouveaux appareils.

Une corrélation n'est pas une preuve de signification : deux champs peuvent évoluer avec le temps. Publier une hypothèse « champ corrélé à la température » avant de la promouvoir en « température en °C ».

### 6.5 Chronologie et états

Décrire passivement périodicité, répétitions, acquittements probables et transitions. Un graphe de séquences observées peut être construit, mais il ne prouve pas la totalité de la machine d'états. Les trames absentes peuvent être hors bande ou hors couverture temporelle.

### 6.6 Entropie et protection

Une forte entropie peut provenir de chiffrement, compression, whitening, données variables ou erreur de démodulation. Ne pas conclure « chiffré » sur cette seule mesure. Utiliser les couches reconnues et les observations disponibles ; à défaut, indiquer « payload non interprété ».

Le moteur n'invente ni clés ni signification. Les formats protégés peuvent être reconnus et structurés tout en gardant leur contenu inaccessible.

### 6.7 Automatisation avec abstention

L'extraction de structures peut être automatique ; la sémantique universelle ne peut pas être garantie sans contexte. Le résultat normal peut être : débit et framing établis, checksum cohérent, trois types de message, champs variables sans unité connue.

La saisie de contexte reste facultative pour l'analyse radio, mais nécessaire pour départager certaines interprétations applicatives. L'utilisateur n'a toujours pas à régler manuellement les filtres ou la décimation.

## 7. Représentation d'une connaissance rétroconçue

Pour chaque règle conserver : couche concernée, valeur ou transformation, provenance, blob/commit/document, captures justificatives, contre-exemples, domaine de validité, date et statut.

Statuts proposés : `reported`, `observed`, `reproduced`, `independently_validated`, `disputed`, `superseded`. Ils s'appliquent à chaque assertion, pas seulement au protocole entier. Un checksum peut être validé alors qu'une unité demeure hypothétique.

Un décodeur expérimental peut afficher des champs bruts et hypothèses. Sa sortie ne rejoint le catalogue validé qu'après tests indépendants. La promotion de statut doit être justifiée par les références de corpus correspondantes.

## 8. Critères d'acceptation spécifiques

1. Les octets reconstruits correspondent à une référence indépendante ou à des captures annotées suffisamment vérifiées.
2. La règle de framing fonctionne sur des sessions réservées à la validation.
3. Une recherche de checksum n'est pas évaluée sur son seul jeu d'ajustement.
4. Les champs et unités sont confirmés par variations contrôlées ou source indépendante.
5. Les appareils et firmwares couverts sont identifiés ; les autres restent non testés.
6. Les cas ambigus restent visibles, notamment plusieurs interprétations valides d'une même trame.
7. Les sorties incluent la provenance de la connaissance communautaire et les obligations de licence.
8. Aucun résultat d'inférence seul n'est présenté comme une spécification constructeur.

## 9. Backlog de recherche

| ID | Travail | Livrable |
|---|---|---|
| REV-01 | Inventaire versionné des décodeurs communautaires | Modes, source, licence, statut et corpus |
| REV-02 | Adaptateur rtl_433 | Résultats structurés, signaux source et version |
| REV-03 | Six études de cas de cette note | Captures, hypothèses et limites par modèle |
| REV-04 | Regroupement et alignement des bursts | Familles de messages et frontières candidates |
| REV-05 | Recherche de codages et contrôles | Hypothèses classées et validation séparée |
| REV-06 | Inférence de champs numériques | Valeurs candidates et preuves expérimentales |
| REV-07 | Registre de provenance par assertion | Statuts et références exploitables par l'interface |
| REV-08 | Export de dissector expérimental | Code généré isolé, revu et testé sur fixtures |
| REV-09 | Analyse des ambiguïtés | Alternatives conservées et contexte discriminant |
| REV-10 | Benchmark de protocoles absents de l'apprentissage | Mesures de généralisation et bonne abstention |

La priorité est la couverture réelle apportée par les travaux communautaires, suivie d'une inférence reproductible sur les cas absents. Ajouter des noms au catalogue sans sources ni corpus ne constitue pas une nouvelle capacité.
