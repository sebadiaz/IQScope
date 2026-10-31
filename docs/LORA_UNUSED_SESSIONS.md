# Premier passage sur quatre sessions supplémentaires LoRaIQ

Le décodeur du commit `793e04f` est conservé sans modification pour cette
évaluation. Résultat local : **3 références exactes sur 4**, dont les deux
charges utiles binaires SF10/BW250. Les trois exports binaires du pipeline
principal sont conformes aux annotations (7, 19 et 19 octets).

| Configuration | Session / membre | SNR annoté | Résultat |
| --- | --- | --- | --- |
| SF7 / BW125 / CR4/5 | 25_01_17-14_39 / rrh2/1 | −8,8366 dB | Aucun candidat cohérent ; référence manquée |
| SF7 / BW125 / CR4/5 | 25_01_15-10_17 / rrh1/3 | 33,144 dB | 7 octets exacts, en-tête et CRC valides |
| SF10 / BW250 / CR4/5 | 25_09_12-14_15 / rrh1/43 | 29,1384 dB | 19 octets binaires exacts, en-tête et CRC valides |
| SF10 / BW250 / CR4/5 | 25_09_12-15_46 / rrh1/30 | 36,5986 dB | 19 octets binaires exacts, en-tête et CRC valides |

## Sélection fixée avant décodage

L’inventaire complet contient 114147 lignes et 22 sessions : 60272 lignes en
SF7/BW125/CR1 et 53875 en SF10/BW250/CR1. La taille du CSV (28253049 octets),
son SHA256 et son MD5 éditeur sont vérifiés. Aucun SF8/SF9 ou autre taux de
codage ne figure dans cet inventaire ; cette source ne les valide donc pas.

Le [manifeste](../corpus/loraiq-extension-manifest.json) retient, dans l’ordre
du CSV, la première ligne des deux premières sessions distinctes de chaque
configuration, hors session de développement `25_01_17-13_40`. Le SNR et les
octets ne servent pas à sélectionner les références. Les quatre choix ont été
fixés avant de télécharger et décoder les membres. Aucun remplacement n’est
effectué si une référence échoue.

Les empreintes des quatre modules LoRa figent l’identité du décodeur. Le
benchmark indique `frozen_first_pass_reproduction` si elles concordent ; des
changements ultérieurs produisent `follow_up_on_exposed_captures`. Les nouvelles
références ne pourront plus être considérées comme inédites après cette étude.
Les versions de NumPy et SciPy sont conservées dans le rapport.

## Vérifications et limites

Le [rapport local](../corpus/loraiq-extension-observation.json) conserve tous
les résultats, y compris l’échec à −8,8 dB, les annotations et les essais du
décodeur. Les membres sont vérifiés par CRC ZIP et SHA512 SigMF éditeur, avec
empreintes SHA256 des données et métadonnées. Le hash global des 71 Go de
l’archive n’est pas vérifié. Aucun script du dataset n’est exécuté.

Le décodeur reçoit uniquement les échantillons complets et leur fréquence
d’échantillonnage. La correspondance à un intervalle annoté unique, puis la
comparaison des octets, intervient après décodage. Le pipeline principal est
ensuite exécuté avec centre RF nul ; les fichiers binaires exportés sont
comparés octet par octet. Aucune fréquence RF n’est présentée comme vérifiée.

Le téléchargement est borné à 32 Mio pour le CSV et 192 Mio pour l’archive
partielle ; chaque membre IQ est limité à 32 Mio et sa métadonnée à 64 Kio.
Le premier passage a transféré 29068952 octets de l’archive, en plus du CSV
préalablement vérifié et réutilisé localement. La CI télécharge et vérifie le
CSV si ce cache n’existe pas. Seul le rapport JSON est publié en artefact.

Ces quatre premières références viennent d’autres sessions du même dataset.
Elles ne constituent ni une estimation représentative de sensibilité, ni une
validation de toutes les modulations ou de tous les paramètres LoRa. Les SNR
sont ceux de l’éditeur. Les deux références SF10 sont fortes ; aucune
performance SF10 à faible SNR n’est établie ici.

Source : Joachim Tapparel et Andreas Burg, EPFL,
[LoRaIQ](https://zenodo.org/records/20341802), DOI 10.5281/zenodo.20341802,
licence CC BY 4.0. Reproduction : `python scripts/loraiq_extension.py` depuis
la racine du dépôt après installation des dépendances.


## Suivi après exposition : acquisition du signal faible

La CI du premier passage est verte :
[210 tests et Chromium](https://github.com/sebadiaz/IQScope/actions/runs/41184294436),
[benchmark des autres sessions](https://github.com/sebadiaz/IQScope/actions/runs/41184294465).

Après ce premier passage, une recherche conjointe bornée de phase sur six
chirps trouve un candidat près de 0,022528 s dans le fichier à −8,8366 dB.
Le [rapport de suivi](../corpus/loraiq-acquisition-observation.json) est marqué
`follow_up_on_exposed_captures` ; le résultat historique n’est pas remplacé.
Le pic combiné présente un rapport pic/fond de 119 et pic/concurrent de 16,25,
avec concentration des amplitudes dans la progression de phase de 0,92645.
Le suivi de porteuse reste rejeté : cohérence 0,15327, minimum 0,3. Aucun
en-tête ni contenu n’est validé pour cette cible.

Le score des références reste **3/4** et les trois exports binaires existants
restent exacts. Il s’agit d’un progrès de détection, pas d’un nouveau paquet
décodé. La recherche a été testée contre bruit blanc, tonalité, forme large
bande périodique, phases de chirps incohérentes et symboles CSS changeants.
Ces cas négatifs ne constituent pas une mesure générale du taux de fausses
alarmes en conditions radio.
