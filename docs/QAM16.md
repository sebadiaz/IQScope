# Première récupération automatique de 16-QAM

IQScope essaie maintenant une chaîne **16-QAM carrée monoporteuse** dans les analyses IQ par fichier et les instantanés SDR. Les paramètres sont estimés à partir des échantillons : aucun débit symbole, décalage de porteuse ou filtre n’est fourni au décodeur. Les résultats sont des symboles et bits candidats, sans protocole ni CRC identifiés.

## Méthode

Une raie cyclique de l’énergie de l’enveloppe fournit un débit symbole candidat. Une raie de la puissance quatrième fournit le décalage de fréquence, avec raffinement dans un intervalle de deux cases FFT. Trois filtres RRC sont essayés (roll-off 0,2 / 0,35 / 0,5, longueur dix symboles), après une décimation éventuelle. Une recherche initiale sur 24 phases puis un ajustement borné du débit et de la phase d’échantillonnage minimisent l’erreur vectorielle des symboles.

Le gain RMS commun conserve les amplitudes relatives : les symboles ne sont pas normalisés individuellement. La rotation est estimée par le moment d’ordre quatre d’une constellation QAM carrée. Les décisions utilisent les quatre niveaux de chaque axe, proportionnels à −3, −1, +1 et +3. L’acceptation exige une EVM RMS d’au plus 12 %, au plus 14 % dans chaque moitié, et au moins 1,5 % d’occupation pour chacun des seize états. Ces seuils sont structurels, pas une probabilité de classification.

Un candidat direct est recherché avant les canaux du détecteur spectral commun. En l’absence de candidat direct, jusqu’à quatre bandes de largeur au plus 48 kHz sont mélangées vers zéro et décimées avec filtrage antirepliement. Les offsets, débits de canal et intervalles source examinés sont enregistrés. Ce détecteur stationnaire peut fusionner ou manquer des émissions.

## Budgets et limites

- Entrée directe entre 1 et 96 kéch/s, recherche d’horloge de 30 à min(9600, débit d’échantillonnage/8) bauds.
- Au moins 280 symboles dans la durée examinée et 256 symboles de sortie. La limite de trois secondes empêche donc certains bas débits d’aboutir.
- Trois premières secondes et 288 000 échantillons au plus par essai direct. Recherche spectrale jusqu’à 2,4 Méch/s, limitée également à 2 400 000 échantillons d’entrée et quatre canaux.
- 24 phases initiales et au plus 160 évaluations par filtre, ajustées sur au plus 2048 centres répartis dans la fenêtre.
- Au plus 40 000 bits (10 000 symboles) et 512 points de constellation par candidat. Les limites de durée et de sortie sont signalées.

La puissance quatrième laisse une ambiguïté de fréquence modulo le débit d’échantillonnage/4 ; la plage directe non ambiguë est donc ±débit/8. La rotation par quart de tour, la conjugaison I/Q, la correspondance des bits et l’alignement des octets restent inconnus. Le débit peut également présenter des alias si la raie d’horloge sélectionnée est une harmonique.

Cette voie ne traite pas les autres tailles de QAM, le QAM croisé, l’OFDM/QAM de standards cellulaires ou Wi-Fi, les canaux à trajets multiples nécessitant un égaliseur, les sauts de fréquence ou les dérives suivies par une boucle persistante. Les impulsions rectangulaires ne sont pas revendiquées. Des salves faibles ou incomplètes, une faible ouverture de filtre ou des états peu présents peuvent provoquer une abstention.

## Convention de sortie et interface

Les rangs I et Q croissent de −3 à +3. Le label est `4*rang_I + rang_Q` (0 à 15), rangé en binaire naturel sur quatre bits. C’est une convention explicite, sans affirmation de correspondance Gray ni de correspondance avec les bits émis par un protocole réel. Les décisions restent compatibles avec plusieurs rotations/conjugaisons.

L’interface montre constellation, EVM, débit estimé, correction de porteuse, filtre essayé et premiers bits candidats. Le compteur des trames CRC n’augmente pas. Les liens proposent :

- texte des bits ;
- binaire empaqueté MSB-first, dernier octet complété par des zéros si nécessaire ;
- labels de symboles dans un tableau JSON ;
- rapport `qam16-candidates.json`, avec paramètres, ambiguïtés et points de constellation.

Les échantillons source ne sont pas modifiés par le décodeur. Les essais SDR restent indépendants entre fenêtres : aucune continuité d’horloge ou de phase n’est revendiquée.

## Validation actuelle

La validation est **synthétique uniquement**. Le générateur de test applique un filtrage RRC dans le domaine fréquentiel, indépendant des coefficients temporels employés par le récepteur. Les comparaisons vérifient les symboles émis en tenant compte des huit rotations/conjugaisons possibles, plusieurs débits et graines, erreurs d’horloge constantes, fréquences positives/négatives et gains différents.

Un mélange de deux canaux 16-QAM et d’une porteuse parasite vérifie la séparation automatique. Les cas BPSK, QPSK, 8-PSK, 64-QAM, FSK, porteuse, silence et bruit testés ne doivent pas produire de candidat. Les exports doivent restituer exactement les bits et labels décidés. Chromium importe une référence synthétique par les vrais chemins de l’application, affiche la constellation et télécharge le rapport.

Ces contrôles ne prouvent pas une couverture de signaux radio réels ni de protocoles utilisant la QAM. Des captures indépendantes, des tests de faux positifs plus larges, l’égalisation, la poursuite de phase et des déframeurs de protocoles restent nécessaires.
