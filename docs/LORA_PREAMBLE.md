# Détection initiale de préambule LoRa compatible

La capacité `lora_preamble` cherche automatiquement des répétitions de chirps
CSS dans un canal centré. Ce n'est pas encore un décodeur de paquets LoRa.
La relation nominale utilisée est T_sym = 2^SF / BW ; voir la note fabricant
[Semtech AN1200.22](https://www.mouser.com/pdfdocs/an120022.pdf).

Le détecteur essaie BW 125, 250 et 500 kHz, SF7 à SF12 et les deux directions
de chirp. Après rééchantillonnage à un échantillon par chip, il déchirpe les
blocs et cherche au moins six pics FFT successifs, stables à un bin près.
L'énergie de trois bins voisins doit représenter au moins 65 % de l'énergie
FFT de chaque bloc. Les bins voisins tolèrent la fuite spectrale due aux
décalages fractionnaires ; le score reste une heuristique, pas une probabilité.

L'analyse automatique, le rapport JSON et l'interface affichent les paramètres
candidats et la preuve de répétition. `lora-preamble-candidates.json` conserve
ces indices ; ils ne sont jamais comptés comme des trames CRC valides. Une
incertitude d'encodage SigMF est propagée dans cet artefact.

## Limites

- Source entre 125 kéch/s et 2,4 Méch/s ; première seconde seulement.
- Canal supposé centré ; pas de balayage des fréquences ni d'estimation fiable
  de porteuse. Une capture large bande avec LoRa décentré peut être manquée.
- Au plus 256 blocs par couple BW/SF ; `search_windows` donne la durée réellement
  examinée et si cette limite est atteinte. Un préambule tardif peut être manqué.
- SF5/SF6, autres largeurs, dérive d'horloge, faibles signaux, collisions et
  préambules très courts ne sont pas couverts par cette première version.
- Une autre forme d'onde CSS répétitive peut correspondre. Les chirps opposés
  et le sync word restent des hypothèses. Un en-tête explicite peut être
  contrôlé ; le codage de charge utile, le CRC de données et le contenu ne
  sont pas décodés. Aucune identification LoRaWAN n'est effectuée.

## Validation

Références synthétiques à deux échantillons par chip, différents BW/SF,
inversion, bruit, décalages temporel et fréquentiel. Contre-exemples : bruit
blanc/coloré, porteuse et symboles CSS changeants. Tests de pipeline, export et
propagation d'une hypothèse d'encodage non vérifiée. Ces tests ne remplacent pas
une validation avec un émetteur indépendant et un paquet connu.

Les prochaines étapes sont la synchronisation fine du paquet,
puis la chaîne de décodage de charge utile jusqu'au CRC. L'en-tête explicite
candidat est décrit plus bas ; il ne valide pas le paquet complet.

## Première preuve de synchronisation

Chaque préambule candidat est désormais suivi d'une recherche locale de deux
chirps consécutifs de sens opposé. La recherche couvre de −1 à +4 durées symbole
par rapport à la fin du train répété, par pas de 1/32 de symbole (au moins un
chip). Chaque bloc doit concentrer au moins 80 % de son énergie dans trois bins
FFT voisins, avec des pics séparés d'au plus un bin. Le minimum des deux
concentrations sert à choisir la meilleure fenêtre.

Le champ `synchronization` distingue `opposite_chirp_pair_candidate` de
`no_consistent_opposite_pair`. L'interface montre cette preuve séparément.
L'horodatage est celui d'une fenêtre candidate, pas une frontière exacte du
paquet : plusieurs fenêtres peuvent satisfaire la condition dans les chirps de
synchronisation. Cette preuve seule ne valide ni le quart de chirp final ni
les deux symboles de sync word ; le champ séparé `sync_word` décrit leur
interprétation candidate. Une autre forme d'onde CSS peut encore correspondre.

Les tests incluent un préambule suivi de symboles CSS décalés puis de deux
chirps opposés et d'un quart de chirp, avec inversion I/Q et faible décalage
fréquentiel. Les contrôles négatifs comportent le préambule seul et un unique
chirp opposé. Cela reste une validation synthétique ; aucun paquet réel connu
ni CRC n'est revendiqué par cette étape.


## Sync word candidat

Après la paire de chirps opposés, une estimation d'alignement utilise la
différence des bins de déchirpage montant/descendant. Les deux solutions
modulo une demi-durée symbole et leurs voisins d'un chip sont évalués près de
la fenêtre candidate. Trois blocs montants (référence de préambule puis deux
symboles de synchronisation) doivent concentrer chacun au moins 65 % de leur
énergie dans trois bins voisins, comme pour le préambule.

Les différences de bins par rapport à la référence sont normalisées selon la
polarité. Chaque symbole doit être à au plus un bin d'une valeur 8*n, avec n
entre 0 et 15. Les deux nibbles donnent le sync word candidat. Cette convention
est documentée par le modulateur de référence
[gr-lora_sdr](https://github.com/tapparelj/gr-lora_sdr/blob/master/lib/modulate_impl.cc).
Le code de synchronisation IQScope est une implémentation indépendante et
n'embarque pas cette bibliothèque.

Le champ `sync_word` indique `sync_word_candidate`, `no_consistent_sync_word`,
`not_available_without_opposite_pair` ou `ambiguous_sync_word`. Si plusieurs
valeurs restent compatibles, aucune n'est sélectionnée. L'interface affiche
l'hexadécimal candidat sans inférer un réseau, LoRaWAN ou l'identité d'un
émetteur. La frontière estimée n'est pas une synchronisation fine validée :
le quart de chirp et l'en-tête sont examinés par les étages suivants ;
le suivi fin de l'horloge et le CRC de données restent à traiter.

Validation synthétique : plusieurs valeurs (dont 0x34, 0x12, 0x00 et 0xAB),
SF7/SF8/SF9/SF12, inversion, bruit, délais différents et décalages fréquentiels
de quelques bins. Des symboles hors convention sont rejetés. Aucun paquet réel
connu n'est encore validé ; le résultat n'est pas compté comme une trame.

## Quart de chirp final et symboles bruts

Après un sync word candidat, le détecteur vérifie le quart de chirp descendant
attendu après les deux chirps opposés. Il essaie cinq alignements entiers dans
un voisinage de deux chips autour de la frontière estimée. La corrélation
normalisée au carré du quart doit atteindre 0,8, après compensation du bin
fréquentiel mesuré sur un chirp opposé. Sans correspondance, aucun symbole de
données n'est extrait.

La fenêtre qui suit fournit au plus 64 symboles CSS consécutifs. Chaque bloc
est déchirpé ; au moins 65 % de son énergie FFT doit rester dans trois bins
voisins. Une estimation locale par la médiane des phases adjacentes affine le
bin grossier, avec un résidu limité à 1,5 bin. La référence est un chirp du
préambule, et la polarité est normalisée. Les bins relatifs arrondis sont
exportés dans `data_symbols.symbol_bins` ; les valeurs issues du seul pic FFT
restent disponibles dans `fft_peak_symbol_bins`. L'extraction s'arrête au premier
bloc insuffisant ou instable. Les sorties indiquent une incertitude d'un bin ;
elle ne constitue pas une garantie statistique sur une capture réelle.

L'interface affiche le nombre de symboles et un aperçu. Ces nombres ne sont
pas directement des octets ou des caractères. Un étage séparé peut interpréter
leurs huit premiers éléments comme un en-tête explicite candidat. Les
transformations Gray, désentrelacement et Hamming de cet en-tête sont décrites
plus bas ; le déblanchiment, le décodage de charge utile et son CRC restent
à implémenter. La synchronisation fractionnaire et
le suivi de l'horloge restent à améliorer ; aucun contenu LoRaWAN n'est extrait.

Les tests comparent les symboles récupérés aux symboles transmis par le
générateur synthétique, avec SF7/SF8/SF10, inversion, bruit, délais et décalages
fréquentiels. Un quart absent interdit la sortie de symboles ; un test impose
la limite de 64 symboles. Chromium vérifie le téléchargement d'une séquence
connue en conservant le compteur de trames validées à zéro. Aucun paquet radio
réel connu n'est encore validé par cette chaîne.

Le champ `stop_reason` distingue fin de source, budget atteint, concentration
spectrale insuffisante et phase instable. Les cas de bruit et de décalage les
plus exigeants peuvent ne restituer qu'un préfixe de la séquence transmise ;
les tests comparent ce préfixe à la référence sans inventer les symboles rejetés.
Ce comportement n'est pas un décodage complet du paquet.


## Premier décodage d'en-tête explicite

Le champ `explicit_header` traite les huit premiers symboles bruts candidats,
avec SF7 à SF12 et en-tête explicite seulement. Il retire le décalage de bin
nominal +1, applique la réduction de débit par quatre et la transformation Gray,
puis inverse l'entrelacement diagonal. Les cinq premiers codewords sont décodés
par recherche de distance dans le code linéaire Hamming (8,4). Seul un codeword
unique à distance zéro ou un est accepté ; deux erreurs par codeword sont
rejetées. Des erreurs plus nombreuses ne sont pas toutes détectables.

La longueur annoncée (1 à 255), le taux de codage 4/5 à 4/8, le drapeau CRC et
les bits réservés sont contrôlés. Une somme linéaire de cinq bits porte sur les
trois premiers nibbles. Seul son succès donne `header_checksum_valid`.
**Ce statut valide la cohérence de l'en-tête candidat, pas le paquet : le CRC
de données, les octets de charge utile et l'identité de l'émetteur ne sont pas
vérifiés.** Les trames validées restent à zéro pour cette chaîne.

Les vecteurs numériques figés décrivent une longueur 17, un codage 4/5 et un
CRC de données annoncé, avec somme d'en-tête 0x1B et nibbles 1,1,3,1,B :
SF7 [85,49,1,13,109,29,89,73] ; SF8 [85,49,1,13,221,61,73,233].
Ils ont été construits côté émission à partir des équations de code et
d'entrelacement ; ce ne sont pas des captures d'un émetteur indépendant.
Les tests vérifient également une somme incorrecte, une erreur corrigée, toutes
les erreurs simples et doubles des 16 codewords, et la chaîne IQ synthétique.
La convention est confrontée à la
[référence gr-lora_sdr](https://github.com/tapparelj/gr-lora_sdr), sans embarquer
cette bibliothèque.

L'en-tête implicite, les paquets de longueur nulle, les SF5/SF6 et la correction
d'horloge ne sont pas pris en charge. Une erreur de synchronisation ou de symbole
peut empêcher la lecture. Il n'y a pas de recherche combinatoire destinée à
forcer une somme valide. La somme de cinq bits est courte : elle ne constitue
ni une authentification ni une preuve suffisante de contenu radio.
