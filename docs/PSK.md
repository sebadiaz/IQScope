# Première chaîne automatique BPSK / QPSK

IQScope essaie automatiquement une récupération BPSK/QPSK dans les analyses IQ de fichiers et d’instantanés SDR. Cette étape produit des **symboles et bits candidats**, pas un protocole reconnu ni des trames vérifiées. Aucun décodeur externe n’est nécessaire.

## Algorithme et preuves

Pour un signal rectangulaire M-PSK, élever les échantillons normalisés à la puissance M supprime les changements de symbole. La chaîne cherche une raie dans le spectre de cette puissance, affine sa fréquence dans un intervalle de deux cases FFT, puis utilise sa phase pour corriger la porteuse. BPSK (M=2) est essayé avant QPSK (M=4). La concentration spectrale, la cohérence de phase, l’occupation des états et l’erreur de phase limitent les candidats.

Les changements d’état de phase donnent des instants de transition. Les passages brefs par des états intermédiaires sont regroupés, puis le récupérateur d’horloge ajuste un débit et une origine temporelle. Les centres des symboles sont échantillonnés après correction ; les rangs de phase deviennent des bits selon une convention binaire explicite. L’horloge la plus lente compatible avec les transitions observées est retenue ; des alias de débit restent possibles.

Les preuves enregistrées sont la cohérence de puissance, l’erreur RMS de phase, le résidu d’horloge et le nombre de transitions. Ces scores sont des mesures structurelles, pas une probabilité de classification.

## Domaine initial et limites

- BPSK/QPSK rectangulaires, stationnaires, à une porteuse, avec amplitude relativement stable. Les formes d’impulsion RRC, OQPSK, QAM, PSK différentielles et 8-PSK ne sont pas prises en charge par cette première version.
- Analyse directe entre 1 et 96 kéch/s ; débit symbole entre 20 bauds et min(9600, débit d’échantillonnage/8). Au moins 64 centres de symboles et suffisamment de transitions sont nécessaires.
- La levée d’ambiguïté de fréquence impose un décalage inférieur, en valeur absolue, au débit d’échantillonnage/(2M). Les sauts, dérives, fades et collisions peuvent faire échouer la récupération.
- Sans candidat direct, recherche entre 1 kéch/s et 2,4 Méch/s sur au plus quatre bandes spectrales de largeur inférieure ou égale à 48 kHz. Mélange vers zéro et décimation antirepliement vers au plus 96 kéch/s. Le détecteur stationnaire peut fusionner des bandes ou manquer des salves faibles.
- Analyse directe limitée aux trois premières secondes et à 288 000 échantillons. La recherche multicanal limite également l’entrée à 2 400 000 échantillons. Sortie limitée à 50 000 bits par candidat ; points de constellation limités à 512 symboles échantillonnés. Les limites atteintes sont signalées dans le rapport.

La rotation absolue, la conjugaison I/Q, la correspondance bits/symboles et l’alignement des octets restent inconnus. La convention est l’ordre des phases dans le sens trigonométrique et le binaire naturel, pas une correspondance Gray établie. Aucun préambule, encodage de ligne, brouillage, FEC ou CRC de protocole n’est recherché ici. Un paquet binaire exporté est un rangement des bits candidats, complété par des zéros au dernier octet, et non une charge utile identifiée.

## Interface et artefacts

La carte BPSK/QPSK montre le débit estimé, la correction de porteuse, l’offset du canal, une constellation normalisée et les 256 premiers bits. Le rapport JSON contient les symboles, les bits, la constellation et les mesures complètes. Les liens permettent de télécharger les bits texte, les bits empaquetés, les rangs de symbole et `psk-candidates.json`.

Les candidats PSK n’augmentent pas le compteur des trames à CRC valide. Le centre RF absolu reste absent si aucune fréquence de capture n’a été fournie. Les fenêtres SDR sont analysées indépendamment, sans boucle de synchronisation persistante entre fenêtres.

## Validation actuelle

Les références sont **synthétiques**, avec données aléatoires connues, bruit, fréquence et phase décalées, origine temporelle fractionnaire et plusieurs débits non entiers. Les symboles récupérés sont comparés aux symboles émis en tenant compte des rotations et conjugaisons possibles. Un mélange numérique BPSK/QPSK vérifie la recherche de deux canaux sans fournir leurs centres au décodeur. Les contrôles bruit, silence, porteuse, AM et FSK doivent s’abstenir. Les limites de durée/bits et la conservation des exports sont également vérifiées.

Chromium importe les deux références synthétiques par les vrais chemins de l’interface, affiche les constellations et vérifie le rapport téléchargé. Cela ne constitue pas une validation sur des enregistrements radio réels.

Les prochaines étapes sont les captures PSK indépendantes, la récupération des impulsions filtrées (filtre adapté et synchronisation temporelle), les boucles de suivi de fréquence/phase, puis des protocoles précis avec préambule, FEC et CRC documentés.
