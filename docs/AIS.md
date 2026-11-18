# Première réception AIS automatique

La voie `ais_gmsk` traite les IQ complexes à 24 kéch/s–2,4 Méch/s. Elle choisit
jusqu'à quatre hypothèses de canal : fréquences AIS A/B si elles entrent dans
la bande RF déclarée, bandes spectrales de 6–24 kHz, puis baseband pour une
entrée au plus à 96 kéch/s. L'utilisateur n'a pas à choisir une décimation,
un filtre ou une phase d'échantillonnage.

Le mélange complexe et les rééchantillonnages ramènent chaque canal vers
48 kéch/s. Après filtrage et discrimination FM, vingt phases sont essayées
à 9 600 bauds. L'extraction exige une séquence d'entraînement suffisamment
alternée, des fanions HDLC exacts, un débourrage cohérent, l'alignement octet
et le CRC-16/X-25. Aucune réparation de bit n'est appliquée. Les octets sont
reconstitués dans l'ordre LSB de la liaison, puis les champs AIS sont lus
MSB d'abord dans les octets logiques.

## Messages et sorties

| Types | Interprétation actuelle |
| --- | --- |
| 1, 2, 3 | Position classe A, vitesse/route fond, cap, statut, codes temporels |
| 4, 11 | Position de station de base et champs UTC bruts |
| 18, 19 | Position classe B ; nom et type de navire pour le type 19 |
| 27 | Position longue portée, avec ses unités distinctes |
| 5 | Nom, indicatif, IMO, type et destination déclarés |
| 24 | Parties A/B du rapport statique, conservées séparément |
| Autres identifiants pris en charge | En-tête type/répétition/MMSI et octets bruts |

Les codes « indisponible », réservés et hors plage restent distincts des
valeurs réelles, dont zéro. Le code de vitesse 1022 est une borne inférieure,
pas une vitesse exacte. Les codes UTC particuliers ne deviennent pas des
secondes normales. Aucun lien entre messages, piste de navire, calendrier
de slots ou message applicatif binaire n'est reconstruit.

L'interface affiche les données numériques et les exports de chaque fenêtre :
`ais-frames.json`, `ais-frame-NNN.bin` avec FCS reçu, et
`ais-message-NNN.bin` sans FCS. Le JSON garde les temps, canaux et l'origine
source. Le parcours automatique indexe aussi AIS dans le catalogue de trames,
avec FCS recalculé et regroupement heuristique des chevauchements.

Ces positions, noms, vitesses et identifiants sont des **déclarations**.
Le CRC ne vérifie ni leur véracité ni l'identité de l'émetteur. L'attribution
A/B utilise le centre RF déclaré ; un canal spectral sans correspondance
reste non attribué. Une même trame peut être observée sur une bande secondaire
ou une image de réception : le compteur décrit des observations.

## Budgets et limites

Par fenêtre : dix secondes et huit millions d'échantillons au plus, quatre
canaux, vingt phases par canal, 6 000 paires de fanions admissibles et
128 trames. Les budgets sont exposés. Le débit reste nominal, sans poursuite
adaptative ; les émetteurs faibles, les collisions, des horloges dégradées
et des canaux absents du détecteur peuvent être manqués. Les filtres centrés
compensent leur délai et utilisent un bourrage nul aux extrémités.

Le profil exige au moins 20 des 24 bits alternés d'entraînement. Les fanions,
le débourrage et le CRC restent stricts. Les longueurs des messages interprétés
sont contrôlées ; le type 24A accepte aussi un octet final de bourrage nul.
Les autres restent à l'état d'en-tête et octets. Il ne s'agit
pas d'un récepteur conforme ou certifié pour la navigation, ni d'un décodeur
VDES ou de tous les messages applicatifs AIS.

## Validation et références

Le préfixe original SDRangel est épinglé par SHA-256 dans
[`corpus/ais-reference.json`](../corpus/ais-reference.json). Il contient
8,388592 s à 250 kéch/s, avec un centre RF déclaré de 162 MHz. Le relevé de
développement retrouve **43 observations sur A et 38 sur B**, plus trois
observations sur une bande secondaire non attribuée. Les octets des canaux
A/B servent de régression ; l'auteur du fichier ne fournit pas un total
indépendant de paquets. Seul un préfixe est téléchargé, sans vérification
d'intégrité de l'archive ZIP complète. L'IQ n'est pas redistribué.

`scripts/ais_reference.py --oracle` compare les champs des messages à
**pyais 3.3.1**, installé seulement dans le banc de validation. L'adaptateur
génère des phrases NMEA depuis nos octets décodés : cette comparaison est
indépendante pour l'interprétation des champs, pas pour la récupération RF.
Les nombres d'observations ne deviennent pas des nombres de paquets uniques.

Les tests utilisent aussi des exemples de messages publiés par GPSD et un
émetteur GMSK synthétique indépendant : signes, unités, valeurs indisponibles,
polarité, phases fractionnaires, débits d'entrée, écart d'horloge, CFO,
retransmissions, corruption, troncature, budgets, API et binaires. Chromium
vérifie l'import synthétique, le catalogue AIS et le fichier IQ original.

Sources techniques : [UIT-R M.1371-6](https://www.itu.int/rec/R-REC-M.1371),
[référence AIVDM de GPSD](https://gpsd.gitlab.io/gpsd/AIVDM.html),
[capture IQ de SDRangel](https://www.sdrangel.org/iq-files/),
[pyais](https://github.com/M0r13n/pyais). Le décodeur IQScope est une
implémentation propre ; aucun code de récepteur GPL n'est intégré.
