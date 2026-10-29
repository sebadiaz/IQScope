# Détection initiale de préambule LoRa compatible

La capacité `lora_preamble` cherche automatiquement des répétitions de chirps
CSS dans un canal centré. Une chaîne PHY partielle décode aussi les en-têtes
explicites et les charges utiles CR4/5–4/8, SF7–SF10, avec contrôle du CRC.
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
  contrôlé ; une charge utile est décodée uniquement dans le périmètre
  explicite CR4/5–4/8, SF7–SF10 décrit plus bas. Aucune identification LoRaWAN n'est effectuée.

## Validation

Références synthétiques à deux échantillons par chip, différents BW/SF,
inversion, bruit, décalages temporel et fréquentiel. Contre-exemples : bruit
blanc/coloré, porteuse et symboles CSS changeants. Tests de pipeline, export et
propagation d'une hypothèse d'encodage non vérifiée. Ces tests ne remplacent pas
une validation avec un émetteur indépendant et un paquet connu.

Les prochaines étapes sont la synchronisation fine du paquet,
l'élargissement des taux de codage et la validation sur un émetteur indépendant.
L'en-tête seul ne valide pas le paquet complet.

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
le suivi fin de l'horloge reste à améliorer. Le CRC de données est vérifié
uniquement par l'étage de charge utile pris en charge.

Validation synthétique : plusieurs valeurs (dont 0x34, 0x12, 0x00 et 0xAB),
SF7/SF8/SF9/SF12, inversion, bruit, délais différents et décalages fréquentiels
de quelques bins. Des symboles hors convention sont rejetés. Ce champ seul ne valide aucun paquet réel et n'est pas compté comme une trame.

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
plus bas ; le déblanchiment, la charge utile et son CRC sont pris en charge
dans le périmètre CR4/5–4/8, SF7–SF10 décrit en fin de document. La synchronisation fractionnaire et
le suivi de l'horloge restent à améliorer ; aucun contenu LoRaWAN n'est extrait.

Les tests comparent les symboles récupérés aux symboles transmis par le
générateur synthétique, avec SF7/SF8/SF10, inversion, bruit, délais et décalages
fréquentiels. Un quart absent interdit la sortie de symboles ; un test impose
la limite de 64 symboles. L'interface distingue ces symboles candidats des octets dont le CRC de données
a été vérifié ; seuls ces derniers contribuent au compteur de trames validées. Une référence radio indépendante est maintenant comparée au niveau de la
charge utile et de son CRC ; voir [la validation indépendante](LORA_REAL_VALIDATION.md).

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
**Ce statut seul valide la cohérence de l'en-tête candidat, pas le paquet.**
Le CRC et les octets de charge utile exigent l'étage séparé décrit ci-dessous ;
l'identité de l'émetteur n'est jamais authentifiée par ces sommes. Un en-tête seul ne contribue pas au compteur de trames validées.

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


## Charge utile CR4/5 à CR4/8 avec CRC de données

Le module `iqscope_lora_payload` traite l'en-tête explicite, les codages **4/5, 4/6, 4/7 et 4/8**
et les **SF7 à SF10**, sans optimisation bas débit. Les nibbles de charge utile
qui débordent dans le premier bloc à codage 4/8 sont récupérés après les cinq
nibbles d'en-tête. Les blocs suivants regroupent 5, 6, 7 ou 8 symboles selon le taux annoncé dans
l'en-tête et utilisent le désentrelacement diagonal à largeur SF. Les codes
4/6 et 4/7 sont obtenus par poncturation du code linéaire (8,4) ; le 4/5 utilise
une parité paire. Le décodeur n'accepte qu'un mot unique à distance zéro ou un.
Une égalité entre plusieurs mots est rejetée, sans utiliser le CRC pour choisir.
Les 4/7 et 4/8 corrigent une erreur simple par codeword ; le 4/8 rejette deux
erreurs. Le 4/6 a des erreurs simples ambiguës et ne garantit pas leur correction.
Des erreurs plus nombreuses peuvent être mal corrigées ; le CRC reste nécessaire. Les nibbles sont assemblés poids faible d'abord.

Le déblanchiment est généré par un LFSR de huit bits, initialisé à 0xFF, avec
retour des bits 7,5,4,3. Une étape par octet produit notamment
`FF FE FC F8 F0 E1 C2 85`. Les deux octets de CRC ne sont pas déblanchis.
La convention CRC utilisée applique CRC-16/XMODEM (poly 0x1021, init 0) aux
len−2 premiers octets, puis XOR avec les deux derniers octets de données dans
l'ordre fort/faible. Le CRC reçu est assemblé poids faible d'abord. Pour
`HELLO`, il vaut 0x8332, transmis `32 83`. Les longueurs avec CRC inférieures
à deux octets sont explicitement non prises en charge.

Seul `payload_crc_valid`, après en-tête cohérent et CRC de données égal,
produit une trame dans `frames`, incrémente le compteur et autorise un export
`lora-payload-N.bin`. Le JSON conserve les octets en hexadécimal, les deux CRC,
les paramètres et la portée de validation. Le texte UTF-8 n'est affiché que
s'il est lisible ; les autres octets restent en hexadécimal. Une hypothèse
SigMF non vérifiée reste attachée au rapport et aux trames exportées.

Une charge utile sans CRC reste `payload_without_crc`, avec octets candidats
uniquement dans le rapport, sans trame validée ni export binaire validé.
`insufficient_symbols`, `payload_parity_mismatch`, `payload_crc_mismatch` et les
modes non pris en charge ne donnent aucune trame valide. Aucune ambiguïté de
symboles n'est résolue par recherche combinatoire du CRC.

### Validation et limites

Les vecteurs figés d'émission couvrent `HELLO` en SF7/SF8/SF9/SF10 et des octets
binaires non textuels. Les tests vérifient la troncature, l'absence de CRC, les
corruptions de symboles, et un CRC faux malgré une parité de codage cohérente.
La chaîne complète depuis les IQ synthétiques restitue les octets attendus et
le test navigateur télécharge exactement `HELLO`. Ces vecteurs sont calculés côté émission. Une trame radio indépendante
SF7/CR4/5 est également vérifiée ; voir [les résultats et limites](LORA_REAL_VALIDATION.md). La convention est confrontée aux blocs de référence
[gr-lora_sdr](https://github.com/tapparelj/gr-lora_sdr), sans les embarquer.

Les limites de synchronisation et les 64 symboles bruts restent applicables.
Avec CRC présent et codage 4/5, ce budget permet au plus 36/42/48/54 octets annoncés en
SF7/8/9/10 respectivement. Les SF11/SF12 pour la charge utile, l'en-tête implicite et les paquets plus longs restent non pris en charge.
Un CRC PHY valide prouve une cohérence, pas l'identité ni la confidentialité.
Aucun parsing, déchiffrement ou authentification LoRaWAN n'est effectué.


### Extension aux quatre taux de codage

Les vecteurs figés `tests/lora_coding_vectors.json` couvrent les trois taux
supplémentaires avec SF7/SF8/SF9/SF10, ainsi qu'une erreur corrigible, deux erreurs
non corrigibles en 4/8 et un paquet sans CRC. Ils sont construits côté émission,
sans appeler les fonctions du décodeur. Les tests IQ couvrent les trois nouveaux
taux et l'inversion ; Chromium vérifie qu'une séquence 4/8 contenant une erreur
de codeword retrouve `HELLO`, affiche une correction et exporte les octets exacts.
Ces nouveaux taux restent à valider sur radio : la référence indépendante
décrite séparément concerne uniquement le 4/5.

Le rapport conserve `corrected_payload_codeword_bits` et
`corrected_spillover_bits`. L'interface affiche les corrections dans les données
si elles sont non nulles ; ce nombre n'est pas une mesure du taux d'erreur radio.
Les trames sans CRC ou à CRC invalide ne sont pas comptées comme validées.

Le nombre de symboles requis est 8 + (4+CR) * ceil((2*(L+2)−(SF−7))/SF)
avec CRC présent, CR l'indice de codage (1 à 4) et L octets de charge utile. La limite de 64 symboles reste
inchangée ; elle impose ces longueurs maximales théoriques :

| Codage | SF7 | SF8 | SF9 | SF10 |
| --- | ---: | ---: | ---: | ---: |
| 4/5 | 36 | 42 | 48 | 54 |
| 4/6 | 29 | 34 | 39 | 44 |
| 4/7 | 26 | 30 | 35 | 39 |
| 4/8 | 22 | 26 | 30 | 34 |

Les contraintes de synchronisation, de centrage et de durée peuvent réduire
ces limites pratiques. Aucun seuil n'est abaissé pour forcer un CRC valide.


## Référence radio indépendante

Une trame LoRaIQ SF7/BW125 kHz/CR4/5 a été décodée automatiquement avec CRC
et octets identiques à l'annotation publiée. Voir [méthode, intégrité et
limites de cette validation](LORA_REAL_VALIDATION.md). Ce premier résultat
positif ne valide pas l'ensemble des paramètres ou des conditions radio.


## Correction fractionnaire de porteuse après détection

Après les six chirps stables, le récepteur estime la rotation de phase entre
répétitions du préambule, séparées de `N = 2**SF` échantillons au débit de chips.
Pour les paires de blocs adjacents, il calcule :

`C = sum(y[n+N] * conj(y[n]))`

`offset_bins = arg(C) / (2*pi)`

`offset_hz = offset_bins * BW / N`

Cette estimation est modulo un bin FFT ; elle ne fournit ni le décalage entier,
ni une fréquence RF vérifiée. Elle utilise au plus huit blocs du préambule,
indépendamment de la polarité des chirps. La cohérence normalisée doit atteindre
0,8. Sinon, aucune compensation n’est appliquée. Une exponentielle complexe
retire la rotation fractionnaire avant la recherche des chirps inversés, du
sync word, du quart de chirp et des symboles. Le bin de référence est recalculé
après compensation. L’étape garde au plus la fin du préambule plus 72 symboles,
suffisants pour le délimiteur et les 64 symboles de données autorisés.

Le champ JSON `carrier_tracking` conserve la cohérence, le nombre de blocs,
la correction appliquée en bins et en hertz, ou l’abstention. L’estimation ne
consulte ni les octets attendus, ni un CRC pour choisir la correction. Les
seuils de concentration spectrale, de quart de chirp, d’en-tête et de CRC
restent identiques. La détection initiale du préambule reste inchangée : cette
correction ne récupère donc pas un préambule déjà rejeté et ne règle pas le
suivi de l’horloge ou la synchronisation temporelle fractionnaire.

### Validation locale de la correction

`tests/test_lora_carrier.py` compare un vecteur TX figé `HELLO` aux octets
récupérés sur 32 variantes SF7 : deux polarités, CFO de 0 / 0,45 / 3,3 / 7,1
bins, quatre phases d’échantillonnage espacées de 1/8 chip et bruit complexe
fixé par une graine. L’ancien code récupérait 25/32 cas ; la compensation en
récupère 32/32, avec les octets exacts et le CRC valide. Ce petit ensemble
synthétique sert à la régression, pas à mesurer un taux d’erreur radio.

Les tests vérifient séparément l’estimation du CFO modulo un bin sur les deux
polarités, l’abstention sur bruit incohérent et zéros, ainsi que le rejet d’un
CRC faux malgré la compensation. Les 175 tests Python passent localement.
La validation locale sur les six mêmes membres LoRaIQ retrouve 2/6 contenus
exacts, contre 1/6 avant correction. Le nouveau paquet à 19,7319 dB donne
`0000002`, CRC 0xE656, et son export binaire par le moteur principal est vérifié.
Voir [le rapport de validation radio](LORA_REAL_VALIDATION.md). Le diagnostic
`scripts/loraiq_timing_probe.py` balaie aussi 16 phases sur ce membre court ;
ces variantes d’un même enregistrement ne sont pas de nouvelles captures.
