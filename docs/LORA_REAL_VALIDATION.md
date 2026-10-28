# Première validation sur des IQ radio indépendants

Source : Joachim Tapparel et Andreas Burg, EPFL,
[LoRaIQ, Zenodo 20341802](https://zenodo.org/records/20341802),
DOI `10.5281/zenodo.20341802`, licence **CC BY 4.0**.

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
Le budget réseau de l’archive, index compris, est de 64 Mio. Seul le rapport JSON
est publié en artifact par `loraiq-batch.yml`, sans les fichiers IQ.

Cet échantillon réduit ne constitue ni une courbe de sensibilité, ni une mesure
de performance représentative du jeu de données complet.
