# Première chaîne automatique BPSK / QPSK

IQScope essaie automatiquement une récupération BPSK/QPSK dans les analyses IQ de fichiers et d’instantanés SDR. Cette étape produit des **symboles et bits candidats**, pas un protocole reconnu ni des trames vérifiées. Aucun décodeur externe n’est nécessaire.

## Algorithme et preuves

Pour un signal rectangulaire M-PSK, élever les échantillons normalisés à la puissance M supprime les changements de symbole. La chaîne cherche une raie dans le spectre de cette puissance, affine sa fréquence dans un intervalle de deux cases FFT, puis utilise sa phase pour corriger la porteuse. BPSK (M=2) est essayé avant QPSK (M=4). La concentration spectrale, la cohérence de phase, l’occupation des états et l’erreur de phase limitent les candidats.

Les changements d’état de phase donnent des instants de transition. Les passages brefs par des états intermédiaires sont regroupés, puis le récupérateur d’horloge ajuste un débit et une origine temporelle. Les centres des symboles sont échantillonnés après correction ; les rangs de phase deviennent des bits selon une convention binaire explicite. L’horloge la plus lente compatible avec les transitions observées est retenue ; des alias de débit restent possibles.

Si cette voie ne produit pas de candidat, une seconde voie cherche une raie cyclique dans l’énergie de l’enveloppe afin d’estimer le débit symbole. Une raie de puissance M fournit une correction de fréquence. Après une décimation éventuelle vers environ 16 échantillons par symbole, trois filtres adaptés racine de cosinus surélevé (RRC) sont essayés, avec des roll-off de 0,2, 0,35 et 0,5 et une longueur de dix symboles.

Un ajustement borné affine conjointement le débit et la phase d’échantillonnage en minimisant l’erreur vectorielle des symboles (EVM). Il examine 24 phases initiales, puis au plus 160 évaluations par filtre sur un maximum de 2048 centres répartis sur la fenêtre. Le candidat final doit avoir une EVM RMS inférieure ou égale à 16 %, des états suffisamment occupés et une erreur inférieure ou égale à 18 % dans chacune des deux moitiés. Les amplitudes relatives des symboles sont conservées après normalisation RMS commune. La voie rectangulaire conserve sa normalisation par échantillon.

Le premier filtre qui passe ces contrôles est conservé. Le roll-off affiché est celui d’un **filtre essayé**, pas une estimation validée du filtre de l’émetteur. La recherche n’examine que la raie d’horloge la plus forte ; elle peut manquer le bon débit si une harmonique ou un autre signal domine. Il s’agit d’une synchronisation calculée sur une fenêtre finie, sans boucle persistante de poursuite.

Les preuves enregistrées sont la cohérence de puissance, l’erreur RMS de phase, le résidu d’horloge et le nombre de transitions. Ces scores sont des mesures structurelles, pas une probabilité de classification. Pour la voie RRC, le rapport distingue la fraction d’énergie de la raie FFT de la cohérence utilisée par la voie rectangulaire, et ajoute l’EVM et la fraction d’énergie de la raie d’horloge.

## Domaine initial et limites

- BPSK/QPSK rectangulaires ou essais RRC bornés, stationnaires et à une porteuse. OQPSK, QAM, PSK différentielles et 8-PSK ne sont pas pris en charge. Les signaux RRC exigent une raie d’horloge suffisamment visible et une EVM faible.
- Analyse directe entre 1 et 96 kéch/s ; débit symbole entre 20 bauds et min(9600, débit d’échantillonnage/8). Au moins 64 centres de symboles et suffisamment de transitions sont nécessaires pour la voie rectangulaire. La voie RRC cherche entre 30 bauds et la même borne haute, exige au moins 100 symboles dans la fenêtre et retire les bords du filtre. La durée maximale limite donc aussi les bas débits réellement récupérables.
- La levée d’ambiguïté de fréquence impose un décalage inférieur, en valeur absolue, au débit d’échantillonnage/(2M). Les sauts, dérives, fades et collisions peuvent faire échouer la récupération.
- Sans candidat direct, recherche entre 1 kéch/s et 2,4 Méch/s sur au plus quatre bandes spectrales de largeur inférieure ou égale à 48 kHz. Mélange vers zéro et décimation antirepliement vers au plus 96 kéch/s. Le détecteur stationnaire peut fusionner des bandes ou manquer des salves faibles.
- Analyse directe limitée aux trois premières secondes et à 288 000 échantillons. La recherche multicanal limite également l’entrée à 2 400 000 échantillons. Sortie limitée à 50 000 bits par candidat ; points de constellation limités à 512 symboles échantillonnés. Les limites atteintes sont signalées dans le rapport.

La rotation absolue, la conjugaison I/Q, la correspondance bits/symboles et l’alignement des octets restent inconnus. La convention est l’ordre des phases dans le sens trigonométrique et le binaire naturel, pas une correspondance Gray établie. Aucun préambule, encodage de ligne, brouillage, FEC ou CRC de protocole n’est recherché ici. Un paquet binaire exporté est un rangement des bits candidats, complété par des zéros au dernier octet, et non une charge utile identifiée.

## Interface et artefacts

La carte BPSK/QPSK montre le débit estimé, la correction de porteuse, l’offset du canal, une constellation normalisée et les 256 premiers bits. La carte précise la voie rectangulaire ou le filtre RRC essayé et son EVM. Le rapport JSON contient les symboles, les bits, la constellation et les mesures complètes. Les liens permettent de télécharger les bits texte, les bits empaquetés, les rangs de symbole et `psk-candidates.json`.

Les candidats PSK n’augmentent pas le compteur des trames à CRC valide. Le centre RF absolu reste absent si aucune fréquence de capture n’a été fournie. Les fenêtres SDR sont analysées indépendamment, sans boucle de synchronisation persistante entre fenêtres.

## Validation actuelle

Les références sont **synthétiques**, avec données aléatoires connues, bruit, fréquence et phase décalées, origine temporelle fractionnaire et plusieurs débits non entiers. Les symboles récupérés sont comparés aux symboles émis en tenant compte des rotations et conjugaisons possibles. Un mélange numérique BPSK/QPSK vérifie la recherche de deux canaux sans fournir leurs centres au décodeur. Des références RRC sont produites par un générateur indépendant dans le domaine fréquentiel, sans appeler le filtre du décodeur. Elles couvrent trois roll-off, plusieurs débits, des erreurs constantes d’horloge de +175 et −250 ppm, un décalage temporel fractionnaire et des fréquences porteuses positives/négatives. Un mélange de deux canaux RRC vérifie aussi la séparation automatique. Les contrôles bruit, silence, porteuse, AM, FSK, 8-PSK filtrée et 16-QAM doivent s’abstenir dans les cas testés. Les limites de durée/bits et la conservation des exports sont également vérifiées.

Chromium importe les quatre références synthétiques (BPSK/QPSK rectangulaires et RRC) par les vrais chemins de l’interface, affiche les constellations et vérifie le rapport téléchargé. Cela ne constitue pas une validation sur des enregistrements radio réels.

Les prochaines étapes sont les captures PSK indépendantes, une couverture plus large des filtres et débits, les dérives d’horloge variables, les boucles de suivi de fréquence/phase, puis des protocoles précis avec préambule, FEC et CRC documentés.
