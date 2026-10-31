# Première validation sur des IQ radio indépendants

Source : Joachim Tapparel et Andreas Burg, EPFL,
[LoRaIQ, Zenodo 20341802](https://zenodo.org/records/20341802),
DOI `10.5281/zenodo.20341802`, licence **CC BY 4.0**.

Validation locale actuelle : **6 contenus exacts sur les mêmes 6 captures**,
et **16/16 variantes temporelles** du membre testé, après correction de porteuse
et raffinement temporel. Les détails et limites figurent en fin de document.

## Résultat observé

Le [contrôle 40748859994](https://github.com/sebadiaz/IQScope/actions/runs/40748859994)
a décodé une trame du fichier `sigmfs/25_01_17-13_40/rrh4/2.sigmf-data` :

- Contenu décodé : `0000001`, soit `30 30 30 30 30 30 31` en hexadécimal.
- Somme d'en-tête cohérente, longueur annoncée : 7 octets, codage 4/5.
- CRC de données reçu et calculé : `0xE655`.
- Octets décodés identiques au `payload_base64` publié dans l'annotation.
- Paramètres détectés SF7 et BW125 kHz, conformes aux annotations.

Ce sont des IQ de mesures radio publiées par une autre équipe, pas une forme
d'onde produite par le générateur de tests IQScope.

## Indépendance de la comparaison

La référence est la première ligne SF7/BW125 kHz/CR1 dont le SNR annoté dépasse
20 dB dans les 128 Kio initiaux du CSV, sinon la ligne de plus haut SNR de ce
préfixe. Cette règle est déterminée avant décodage. La ligne retenue annonce
20,3859 dB, un débit de 250 000 échantillons/s et un contenu de 7 octets.

Le premier essai donne au détecteur les **19 426 échantillons du fichier entier**
et leur débit, soit 77,704 ms. Le SF, la largeur de bande, le CFO annoté et le
contenu attendu ne sont pas passés au détecteur. Le contenu de référence sert
uniquement à comparer les résultats après décodage et CRC.

Un second essai utilise la fenêtre temporelle annotée, avec une durée symbole
de marge de chaque côté. Il est explicitement marqué comme guidé par cette
fenêtre et ne constitue pas la preuve d'automaticité. Il retrouve aussi les
mêmes octets. Aucun CFO annoté n'est appliqué dans ces deux essais.

## Acquisition bornée et intégrité

Le script `scripts/loraiq_reference.py` interroge la licence et l'inventaire
publics, lit un document de chargement de moins de 16 Kio (sans l'exécuter),
puis 128 Kio du CSV. Il utilise des requêtes HTTP Range strictes sur l'archive
ZIP de 71 Go pour lire son index et un seul couple SigMF.

Le premier passage a transféré 25 483 105 octets depuis le ZIP, principalement
pour l'index de ses 207 715 membres. Le budget est de 48 Mio, avec au plus
64 Kio de métadonnées SigMF et 8 Mio de données par membre. L'archive entière
n'est ni téléchargée ni vérifiée par son MD5 global. Les CRC ZIP des deux
membres complets ont été vérifiés.

Les SHA-256 de référence sont figés pour éviter une modification silencieuse :

| Élément | SHA-256 |
| --- | --- |
| Préfixe CSV de 128 Kio | `96122f6ae2f1ff6b3ea8601a4d1e3336abab94e35cb6313a01fe5a16d6d135cf` |
| Membre IQ | `954c295af3fa3e129eef981915401428bf22b401d5a9d414f4a316554f1f4bc4` |
| Métadonnées SigMF | `92c4ca429c73e128f07de282a963eede7c1534f90ba7227c228bbe861ea5034d` |

La CI échoue si la source change, si le décodage automatique ne retrouve plus
les octets indépendamment annotés ou si l'export du moteur principal diffère.
Les artefacts ne contiennent pas les IQ bruts : observation JSON, rapport,
spectre et charge utile binaire uniquement.

## Portée et limites

C'est **une trame courte à bon SNR**, en SF7, BW125 kHz et codage 4/5. Ce résultat
ne mesure pas un taux de réussite, ne valide pas les codages 4/6–4/8 sur radio,
ni les faibles SNR, les collisions ou les longues captures. Le fichier source
est déjà un extrait court fourni par les auteurs. Aucun seuil ni algorithme du
décodeur n'a été ajusté sur ce résultat.

Le champ de fréquence SigMF vaut numériquement `862.5`, alors que le format
attend des hertz ; la description du dataset annonce une porteuse de 862,5 MHz.
Le rapport n'en déduit pas une fréquence RF vérifiée et utilise la bande de base.
Le CRC physique ne prouve pas l'identité de l'émetteur ; aucun parsing,
authentification ou déchiffrement LoRaWAN n'est effectué.

## Régression intégrée et export vérifié

Le [contrôle 40750399589](https://github.com/sebadiaz/IQScope/actions/runs/40750399589)
a répété le résultat avec les empreintes figées, vérifié aussi le SHA-512 publié
dans les métadonnées SigMF, puis exécuté le moteur principal et comparé son
export binaire aux sept octets indépendamment annotés. Le
[rapport conservé](../corpus/loraiq-reference-observation.json) distingue les
champs comparés des limites de validation. Le sync word reste un candidat non
comparé à une valeur de référence publiée.

L'artefact `independent-loraiq-reference` de ce contrôle contient le rapport
complet avec spectre/waterfall, le CSV spectral et la charge utile binaire.
Il ne contient pas les IQ source. L'attribution et la licence sont conservées
dans le rapport. Les 170 tests Python et le contrôle Chromium passent au même
état de code ; aucun changement d'algorithme n'a été nécessaire pour cette
référence radio.


## Validation sur plusieurs captures

`scripts/loraiq_batch.py` sélectionne le premier membre distinct de chacune des
six tranches SNR : moins de 0, 0–5, 5–10, 10–15, 15–20 et au moins 20 dB.
La sélection utilise uniquement le préfixe CSV de 128 Kio déjà épinglé, SF7,
125 kHz et le codage 4/5. Les tranches absentes restent absentes ; aucun fichier
n’est remplacé après un échec de décodage.

Chaque membre complet est présenté au détecteur avec sa seule fréquence
d’échantillonnage. Les octets attendus sont comparés après le décodage. Le
rapport conserve les échecs, les éventuelles autres trames à CRC valide, les
empreintes des sources et les résultats détaillés. Les erreurs de transport ou
d’intégrité échouent en CI ; un échec de décodage reste un résultat du benchmark.
Le budget réseau de l’archive, index compris, est de 224 Mio, avec au plus 32 Mio par membre IQ. Seul le rapport JSON
est publié en artifact par `loraiq-batch.yml`, sans les fichiers IQ.

Cet échantillon réduit ne constitue ni une courbe de sensibilité, ni une mesure
de performance représentative du jeu de données complet.


### Premier résultat par tranche SNR

Le [contrôle 40757758266](https://github.com/sebadiaz/IQScope/actions/runs/40757758266)
a traité les six membres sélectionnés, sans modification du décodeur :

| SNR annoté | Résultat du décodage automatique |
| --- | --- |
| −1,0897 dB | Aucun préambule retenu |
| 3,7885 dB | Aucun préambule retenu |
| 7,1515 dB | Aucun préambule retenu |
| 10,2641 dB | Préambule et deux chirps inversés ; sync word non retenu |
| 19,7319 dB | En-tête valide ; extraction arrêtée à 14 symboles, 23 nécessaires |
| 20,3859 dB | `0000001`, CRC valide, octets identiques à l’annotation |

Bilan : **1 correspondance exacte sur 6 membres**, 5 échecs de décodage, aucune
autre charge utile à CRC valide. Les SHA-512 publiés et CRC ZIP des six membres
sont vérifiés ; 51 690 080 octets ont été transférés depuis l’archive.
Le [rapport conservé](../corpus/loraiq-batch-observation.json) contient aussi les
empreintes SHA-256, chemins et résultats détaillés.

Les enregistrements proviennent de la même session ; certains récepteurs peuvent
observer une même émission. Ces six membres ne sont donc pas six essais radio
statistiquement indépendants. Le résultat révèle notamment une limite de
synchronisation et une extraction incomplète même à bon SNR ; il ne permet pas
de fixer un seuil de sensibilité. Le détecteur conserve ses limites temporelles
internes sur les fichiers longs. Aucun seuil n’a été assoupli pour ce benchmark.
Les 171 tests Python et Chromium passent au même état de code.


## Correction fractionnaire de porteuse : comparaison sur les mêmes IQ

La rotation de phase entre chirps répétés estime une correction fractionnaire
modulo un bin FFT, sans annotation CFO, fenêtre guidée, contenu attendu ou
recherche pilotée par le CRC. La méthode et ses limites sont décrites dans
[la spécification LoRa](LORA_PREAMBLE.md#correction-fractionnaire-de-porteuse-après-détection).

Le 29 octobre 2026, l’exécution locale sur **les six mêmes membres**, avec
annotations et empreintes SHA-256 identiques à la référence précédente, donne
**2 correspondances exactes sur 6**, contre 1/6 avant correction :

- Le membre `rrh2/2`, SNR annoté 19,7319 dB, restitue maintenant ses 23 symboles
  et le contenu `0000002`, CRC reçu et calculé `0xE656`. La correction estimée
  vaut −0,280899 bin, soit −274,315 Hz modulo un bin ; ce n’est pas une mesure
  du CFO entier ni de la fréquence RF. Son export binaire via le moteur
  principal a aussi été comparé aux sept octets attendus.
- Le membre `rrh4/2`, SNR annoté 20,3859 dB, conserve `0000001`, CRC `0xE655`.
- À 10,2641 dB, le sync word est désormais candidat, mais le quart de chirp ne
  permet pas d’extraire des symboles. Les trois cas de SNR inférieur restent
  sans préambule retenu. Aucune autre charge utile à CRC valide n’est produite.

Le [rapport détaillé](../corpus/loraiq-carrier-observation.json) conserve les
résultats complets, la comparaison des sources et l’empreinte du décodeur local.
Les SHA-512 publiés et CRC ZIP sont vérifiés. Le budget réseau et la sélection
restent ceux du benchmark précédent. Ce petit ensemble corrélé reste insuffisant
pour estimer un taux d’erreur ou une sensibilité. La correction n’abaisse aucun
seuil de concentration, quart de chirp, en-tête ou CRC. Les 175 tests Python
passent localement, avec 32/32 variantes synthétiques contre 25/32 auparavant.


Le diagnostic temporel séparé décale ce même fichier court sur 16 phases
espacées de 1/16 chip. Dix variantes conservent le contenu exact avec CRC ;
six s’abstiennent. Ce résultat confirme que la compensation de fréquence
fractionnaire ne résout pas tous les décalages temporels fractionnaires.
Il ne compte pas comme 16 nouvelles captures radio.


La [CI du benchmark 40922387931](https://github.com/sebadiaz/IQScope/actions/runs/40922387931)
a reproduit les **2/6 correspondances exactes** sur les mêmes annotations et
empreintes sources, ainsi que les 10/16 variantes de phase du fichier court.
Les [175 tests sur Python 3.10, 3.12 et 3.13, Chromium et autres corpus](https://github.com/sebadiaz/IQScope/actions/runs/40922388023)
passent, de même que la [régression indépendante avec export](https://github.com/sebadiaz/IQScope/actions/runs/40922387924).
Ces contrôles portent sur le commit `6be3acfffc4809af4deec4ab34e1fee7b2a27c04`.


## Raffinement temporel : trois contenus exacts sur les mêmes six captures

L’alignement utilise huit phases au pas de 1/8 chip, sélectionnées d’après les
chirps du préambule, avec filtrage du canal et interpolation fréquentielle du
pic FFT. La sélection est terminée avant de décoder l’en-tête ou les données ;
elle n’est pas pilotée par un CRC ou par les annotations de contenu.

Le 29 octobre 2026, l’analyse locale des **six mêmes sources et annotations**,
avec empreintes SHA-256 identiques et SHA-512 publiés vérifiés, donne :

| SNR annoté | Contenu exact avec CRC |
| --- | --- |
| −1,0897 / 3,7885 / 7,1515 dB | Aucun préambule retenu |
| 10,2641 dB | `0000000`, CRC `0xE654` |
| 19,7319 dB | `0000002`, CRC `0xE656` |
| 20,3859 dB | `0000001`, CRC `0xE655` |

Bilan : **3/6**, contre 2/6 avec la seule correction fractionnaire de porteuse.
Aucune autre charge utile à CRC valide n’est produite. Les trois exports binaires
via le moteur principal sont comparés aux octets annotés. Le
[rapport détaillé](../corpus/loraiq-timing-observation.json) conserve les résultats,
les scores de sélection, les empreintes sources et celle du décodeur.

Le diagnostic sur 16 décalages au pas de 1/16 chip du membre `rrh2/2` retrouve
16 fois les octets exacts, contre 10/16 précédemment. Ce sont des transformations
d’un seul signal, pas des captures supplémentaires. La sélection du corpus et
les seuils de quart de chirp, d’en-tête et de CRC restent inchangés.
Ce petit jeu corrélé ne mesure pas une sensibilité et ne valide ni les collisions,
ni la dérive d’horloge, ni d’autres SF ou codages sur radio.


La [CI 40936242866](https://github.com/sebadiaz/IQScope/actions/runs/40936242866)
a reproduit **3/6 contenus exacts** sur les mêmes sources et **16/16 variantes
temporelles exactes**. Les [180 tests Python sur trois versions, Chromium et
les autres corpus](https://github.com/sebadiaz/IQScope/actions/runs/40936242897)
passent, ainsi que la [référence indépendante avec export](https://github.com/sebadiaz/IQScope/actions/runs/40936242905).
Ces contrôles portent sur le commit `714fd90286a586e7f10a565f73aa64564bf114ca`.


## Préambules faibles : indices supplémentaires, toujours trois contenus validés

La [découverte par moyenne cohérente](LORA_PREAMBLE.md#découverte-cohérente-de-préambules-faibles)
combine six chirps répétés après estimation de leur rotation de phase, avec un
budget explicite. Sur les mêmes fichiers et empreintes, le 30 octobre 2026 :

- À −1,0897 dB, un préambule SF7/BW125 kHz candidat apparaît ; la paire inversée
  n’est pas retenue et aucun contenu n’est décodé.
- À 7,1515 dB, un préambule, une paire inversée et le sync word candidat `0x96`
  apparaissent ; le quart de chirp reste insuffisant. Le sync word n’est toujours
  pas comparé à une référence publiée et aucun contenu n’est validé.
- Les trois contenus déjà validés restent exacts, et leurs exports binaires
  sont de nouveau comparés aux annotations. **Le bilan de contenu reste 3/6.**

Le [rapport détaillé](../corpus/loraiq-coherent-observation.json) conserve les
mesures brutes et combinées, les critères des deux voies, les budgets et les
résultats. Les SHA-256 des sources restent identiques ; leurs SHA-512 publiés
sont vérifiés. Les 186 tests Python passent localement.

Le cas à 3,7885 dB nécessite une distinction de couverture : la référence
annotée commence à **1,019092 s**, alors que SF7/BW125 kHz n’examine ici que
0,262144 s au début de la première seconde. Le fichier produit maintenant un
candidat antérieur ; il ne prouve pas la reconnaissance de cette trame annotée.
Ce cas ne peut pas être attribué uniquement au SNR. Aucune fenêtre temporelle
annotée n’a été donnée au détecteur pour le récupérer.


La [CI 41119145706](https://github.com/sebadiaz/IQScope/actions/runs/41119145706)
a reproduit les nouveaux indices de préambule et de synchronisation, les mêmes
**3/6 contenus exacts**, et les **16/16 variantes temporelles exactes**.
Les [186 tests sur trois versions Python, Chromium et les autres corpus](https://github.com/sebadiaz/IQScope/actions/runs/41119145606)
passent, de même que la [référence indépendante avec export](https://github.com/sebadiaz/IQScope/actions/runs/41119145598).
Ces contrôles portent sur le commit `fb17b16a9900b11fbc26455e8e628a384e3db3cb`.


## Quart de chirp comparé aux références : quatre contenus exacts

La [voie complémentaire de contrôle du quart](LORA_PREAMBLE.md#quart-de-chirp-bruité--comparaison-à-deux-références-précédentes)
compare sa projection complexe aux préfixes des deux chirps inversés précédents.
Elle ne remplace pas la voie principale à corrélation ≥ 0,8. Pour une corrélation
≥ 0,65, elle exige aussi une cohérence de référence ≥ 0,5, une statistique de
projection sur bruit ≥ 16 et un écart complexe relatif au carré ≤ 0,25.
Ces valeurs ne sont pas une probabilité de confiance ou de fausse alarme.

Le 30 octobre 2026, les mêmes sources, annotations et empreintes donnent **4/6
contenus exacts**, contre 3/6 précédemment. Le membre `rrh3/1`, à 7,1515 dB,
restitue maintenant `0000000`, CRC reçu et calculé `0xE654`, sans correction FEC.
Son quart a une corrélation de 0,7413 ; l’accord aux références permet de le
retenir. Le [rapport détaillé](../corpus/loraiq-quarter-observation.json) conserve
les mesures, critères, empreintes et résultats de chaque membre.

Les quatre exports du moteur principal sont comparés aux octets annotés, avec
attribution et bande de base explicites. Les 192 tests passent localement ; les
16 variantes temporelles restent exactes. Le cas à −1,0897 dB reste sans contenu
validé, et la trame annotée à 3,7885 dB reste hors de la fenêtre examinée.
Aucune fenêtre ou donnée attendue n’est fournie au décodeur ; la comparaison
aux annotations intervient après décodage. Les frontières ne sont pas choisies
selon le résultat du CRC.

Ces six enregistrements ont servi au diagnostic et à la mise au point des
corrections. Ils constituent un petit corpus de développement corrélé, pas un
jeu de test réservé ni une mesure de généralisation à l’ensemble des signaux.


## Paquets tardifs et comparaison temporelle

La recherche temporelle du commit `152e51a` produit **9 trames dont les octets
sont exactement conformes aux annotations**, dans les mêmes six fichiers.
Le score des six paquets sélectionnés initialement reste **4/6**. Les cinq
autres trames ne sont pas cinq captures indépendantes.

Exemples : `0000007` vers 7,043293 s dans le premier fichier ; `0000004`,
`0000005`, `0000006` vers 3,032516, 4,026978 et 5,023500 s dans le second.
Le [rapport reproductible](../corpus/loraiq-temporal-observation.json) conserve
les annotations, temps, fenêtres et empreintes des sources. Le préfixe CSV
vérifié reste limité à 128 Kio.

Après le décodage aveugle, une trame doit appartenir à un intervalle annoté
unique du même membre SigMF, avec les mêmes fréquence d’échantillonnage, SF,
largeur et taux de codage. Les octets sont comparés seulement ensuite. Une
absence d’annotation dans ce préfixe ou un chevauchement ambigu reste non
vérifié ; un contenu différent est un échec explicite. Le score des six
références exige désormais également cette correspondance temporelle.
Aucune annotation ne sert à sélectionner une fenêtre ou régler le décodeur.

La CI du commit `152e51a` est verte :
[tests Python et Chromium](https://github.com/sebadiaz/IQScope/actions/runs/41133736684),
[benchmark LoRaIQ](https://github.com/sebadiaz/IQScope/actions/runs/41133736646).
Ces contrôles précèdent l’ajout de cette comparaison temporelle au benchmark.


## Diagnostic des deux références encore manquées

Les deux préambules sont détectés, mais aucun en-tête n’est lu : il ne s’agit
pas encore d’un échec de CRC des données. Le
[rapport de diagnostic](../corpus/loraiq-miss-diagnostic.json) conserve les
mesures et les expériences locales.

| Référence (SNR annoté) | Premier blocage après le préambule | Mesure |
| --- | --- | --- |
| rrh1/1, −1,0897 dB, vers 0,03092 s | Paire de chirps opposés | Meilleure concentration minimale compatible : 0,410920 ; minimum 0,65 pour la voie cohérente |
| rrh3/2, 3,7885 dB, vers 1,019092 s | Sync word | Meilleure concentration minimale des trois chirps : 0,634411 ; seuil 0,65 ; aucune limite candidate acceptée |

Le raffinement temporel est également refusé : ses meilleurs scores valent
0,362146 et 0,597860, sous le seuil de 0,65. Une expérience isolée acceptant
la phase choisie par le préambule malgré ce rejet conserve les mêmes blocages
suivants. Pour rrh3/2, accepter expérimentalement le sync word à partir de 0,60
donne un candidat `96`, puis un rejet du quart de chirp final (corrélation
maximale 0,632823). Aucune de ces expériences ne récupère les données.

Les seuils de production sont conservés. Les rapports du détecteur exposent
désormais les mesures des rejets de paire et de sync word. La suite du travail
est une synchronisation adaptée au bruit, avec mesure de fiabilité et tests
de faux positifs ; baisser isolément un seuil ne suffit pas. Ces observations
ne prouvent pas que les IQ sont impossibles à décoder.


## Récupération du paquet à 3,7885 dB

La voie de fiabilité des pics récupère désormais la référence rrh3/2 à
1,031647 s (début des données), soit `0000002`, CRC reçu et calculé `0xE656`.
Le contenu est conforme à l’annotation d’un intervalle unique. Aucun temps,
CFO, SF, largeur, taux de codage ni octet annoté n’a été fourni au détecteur.
La phase 7/8 est choisie sur le préambule ; le score individuel est 0,597860
mais celui du bin de la moyenne cohérente atteint 0,861291.

Le nouveau [rapport local](../corpus/loraiq-matched-observation.json) compte
**5/6 références initiales**, et 12 émissions à CRC valide dans les six
fichiers : **11 comparaisons exactes**, aucune différence, et **une émission
sans annotation correspondante dans le préfixe CSV disponible** (`0000005`
vers 5,045544 s du premier fichier). Cette dernière reste vérifiée par CRC
uniquement ; ses octets ne sont pas présentés comme validés indépendamment.
Les captures et les émissions supplémentaires restent corrélées.

Lors de cette validation à 5/6, la cible à −1,0897 dB n’était pas récupérée. Son meilleur bin de préambule
moyenné atteint 0,678190, sous le minimum 0,8 de la nouvelle voie, et sa paire
de chirps opposés demeure rejetée. Le résultat 5/6 concerne ces données de
développement et ne mesure pas une performance sur des captures inédites.
Les rapports précédents et leurs scores restent des résultats historiques.


## Sixième contenu : limite inférée, quart non confirmé

Le [rapport local actuel](../corpus/loraiq-inferred-observation.json) récupère
**6/6 références initiales**, dont `0000000` du membre rrh1/1 à SNR annoté
−1,0897 dB. Les données commencent vers 0,043476 s, avec en-tête valide,
CRC reçu et calculé `0xE654`, et octets identiques à l’annotation d’un intervalle
unique. Les temps et octets annotés ne sont consultés qu’après détection.

Le préambule moyenné présente un pic/bruit de 515,47 et un pic/concurrent de
49,995, malgré une fraction d’énergie de 0,678190. Deux chirps opposés sont
retenus par leurs pics et leur cohérence. Le sync word candidat donne une
frontière unique ; le quart final reste insuffisamment confirmé. Une lecture
unique à l’offset physique nominal de 2,25 symboles restitue les octets et leur
CRC. Le rapport et l’UI signalent donc **quart de chirp non confirmé**. Les
contrôles du quart n’ont pas été artificiellement marqués comme réussis.

Au total : **14 émissions à CRC valide**, **13 comparaisons exactes**, aucune
différence d’octets, aucune association ambiguë, et une émission sans annotation
dans le préfixe CSV (`0000005` vers 5,045544 s de rrh1/1). Le CRC seul ne
valide pas indépendamment cette dernière. Ces résultats restent six fichiers
corrélés d’une session, utilisés pour développer le décodeur : ni données
inédites de validation, ni garantie générale à −1 dB.


## Première évaluation hors session de développement

Le décodeur `793e04f` a été conservé sans modification pour sélectionner puis
examiner quatre références d’autres sessions : **3/4 exactes**, dont deux
charges utiles binaires SF10/BW250 avec exports de 19 octets vérifiés. La
cible SF7 à −8,8 dB reste manquée. Ce score est distinct des six références
de développement. Voir la [méthode et les résultats complets](LORA_UNUSED_SESSIONS.md).
