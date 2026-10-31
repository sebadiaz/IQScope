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

- Source entre 125 kéch/s et 2,4 Méch/s ; jusqu’à huit fenêtres d’une seconde sélectionnées automatiquement.
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
normalisée au carré du quart doit atteindre 0,8 dans la voie principale, après
compensation du bin fréquentiel mesuré sur un chirp opposé. Une voie complémentaire
compare aussi les préfixes des deux chirps précédents ; ses critères sont décrits
en fin de document. Sans correspondance, aucun symbole de données n’est extrait.

La fenêtre qui suit fournit au plus 64 symboles CSS consécutifs. Chaque bloc
est déchirpé ; au moins 65 % de son énergie FFT doit rester dans trois bins
voisins. Après un raffinement temporel fiable, le pic d’une FFT suréchantillonnée
par huit est interpolé ; sinon, la médiane des phases adjacentes affine le bin
grossier. Le résidu doit rester à moins de 1,5 bin du pic FFT initial. La référence est un chirp du
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
fréquentiels. Dans la voie initiale, un quart absent interdit la sortie de symboles ; un test impose
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


## Raffinement temporel par le préambule

Après la correction fractionnaire de porteuse, les candidats SF7–SF10 disposant
d’au moins deux échantillons par chip peuvent rechercher huit phases de lecture,
espacées de 1/8 chip. La sélection n’utilise que les huit premiers chirps stables
au maximum : pour chaque phase, le score est la médiane de la fraction d’énergie
contenue dans le bin FFT dominant après compensation de porteuse. Le maximum
doit atteindre 0,65 dans **un seul bin**. Un préambule initialement rejeté n’est
pas récupéré par cette étape.

Une seule phase est choisie avant la lecture du sync word et des données. Ni
l’en-tête, ni le CRC, ni une charge utile attendue ne servent à sélectionner
une phase ou à en essayer une autre après un échec. Les cas non applicables ou
insuffisamment concentrés conservent le chemin précédent.

L’interpolation conserve un filtre de canal de coupure BW/2 pour éviter de replier
les autres fréquences. Le cas où le débit d’entrée vaut déjà huit fois BW filtre
explicitement le signal, car `resample_poly` saute le filtrage au rapport 1:1.
Les filtres restent limités à 65 537 coefficients et les données interpolées à
3 000 000 échantillons. Seul le préfixe nécessaire à la fin du préambule plus
72 symboles et un chip de marge est interpolé, dans la limite de la première
seconde déjà retenue. Le budget des symboles utiles reste de 64.

Après ce raffinement, la mesure fréquentielle utilise une FFT complétée par des
zéros jusqu’à 8N, puis une interpolation parabolique du pic et de ses deux voisins.
Le pic doit rester à moins de 1,5 bin du maximum FFT grossier. L’ancienne médiane
des phases adjacentes reste utilisée lorsque le raffinement n’est pas appliqué.
Le nouveau champ `timing_tracking` expose les huit scores, la phase choisie,
le décalage de grille en chips, les budgets et l’éventuelle abstention.
Les temps des chirps inversés, du sync word et du début des données incluent
le décalage de grille ; les indices entiers de chip se rapportent à cette grille.

Cette étape améliore un décalage temporel local ; elle ne suit pas la dérive
d’horloge sur une longue transmission et ne constitue pas un synchroniseur LoRa
universel. Elle reste bornée aux mêmes BW, SF et modes déjà pris en charge.

### Validation du raffinement

Les cinq tests de `tests/test_lora_timing.py` vérifient la mesure fréquentielle
près d’un repli FFT, la sélection identique pour deux charges utiles dont une
corrompue, le filtrage d’un fort signal hors canal au rapport 1:1, l’abstention
sur budget de filtre et les octets exacts sur SF7–SF10, les deux polarités et
différents décalages fractionnaires. La suite complète comprend 180 tests.

Sur les six mêmes IQ LoRaIQ, vérifiés contre les mêmes empreintes, la validation
locale passe de 2 à **3 contenus exacts sur 6**. Le cas à 10,2641 dB restitue
`0000000`, CRC `0xE654`. Les trois exports binaires du moteur principal sont
vérifiés contre les octets annotés. Sur les 16 variantes temporelles du fichier
à 19,7319 dB, les 16 contenus sont exacts, contre 10/16 avant cette étape.
Ces variantes d’un seul enregistrement ne sont pas 16 captures indépendantes.
Voir [la validation radio et ses limites](LORA_REAL_VALIDATION.md).


## Découverte cohérente de préambules faibles

Si aucun groupe ne satisfait la voie initiale à six chirps individuellement
concentrés, une voie de secours examine des fenêtres de six pics FFT stables,
tous à au plus un bin du premier, sur le même intervalle déjà borné. La cohérence
de répétition normalisée au retard N doit atteindre 0,3. Sa phase fournit un
CFO fractionnaire ; les six chirps sont corrigés en phase puis moyennés avant
la FFT de déchirpage. Au moins 65 % de l’énergie de cette moyenne doit être
concentrée dans trois bins voisins. C’est une mesure sur un signal combiné,
pas un abaissement du critère de concentration des chirps individuels.

Le budget est de 32 combinaisons admissibles par BW/SF/polarité. Le rapport
`coherent_searches` conserve les compteurs et les budgets atteints. La sortie
`evidence.discovery` distingue la voie individuelle de la moyenne cohérente,
avec le début de fenêtre, la cohérence et les concentrations brute et combinée.
Le score reste une heuristique, pas une probabilité ni une validation de paquet.

Cette voie autorise aussi l’estimation de porteuse sur une cohérence brute de
0,3, uniquement après validation de la moyenne cohérente. La voie initiale
conserve son seuil de 0,8. Le rapport expose `required_coherence` afin de rendre
cette distinction visible. Aucune annotation de SF, BW, CFO, temps ou contenu
n’est fournie au détecteur.

Pour ces seuls candidats faibles, une seconde voie peut proposer une paire de
chirps inversés si les pics des deux chirps sont voisins, chaque concentration
individuelle atteint 0,65, leur cohérence atteint 0,5 et leur moyenne contient
au moins 0,8 de l’énergie dans trois bins. La paire individuelle au seuil de
0,8 reste prioritaire. Les deux chirps sont nécessaires ; un seul ne suffit pas.
Le quart de chirp et les vérifications d’en-tête, FEC et CRC restent inchangés.

### Résultats et limites

Sur les mêmes sources LoRaIQ, les membres annotés à −1,0897 et 7,1515 dB donnent
maintenant des préambules SF7/BW125 kHz candidats. Leurs concentrations combinées
atteignent respectivement environ 0,737 et 0,876, contre environ 0,417 et 0,407
sur les chirps bruts des fenêtres retenues. À 7,1515 dB, une paire inversée et
le sync word candidat `0x96` sont proposés, mais le quart de chirp n’est pas
suffisant : aucun contenu n’est validé. À −1,0897 dB, la paire n’est pas retenue.

Le nombre de contenus exacts reste donc **3/6**. Le membre annoté à 3,7885 dB
contient sa trame de référence à 1,019092 s, hors de l’intervalle SF7 examiné
(0,262144 s dans la première seconde). Un candidat plus tôt dans ce fichier
ne valide pas cette trame annotée. Voir [le rapport indépendant](LORA_REAL_VALIDATION.md).

Les six tests de `tests/test_lora_coherent.py` couvrent les préambules faibles
synthétiques SF7/SF8/SF10, les deux polarités, une phase incohérente, le budget,
la nécessité des deux chirps inversés, les abstentions sur bruit et forme d’onde
périodique large bande, et l’export de candidats sans charge utile binaire.
La suite locale contient 186 tests. Ces observations limitées ne mesurent pas
un taux de détection ou de fausse alarme sur une population radio.


## Quart de chirp bruité : comparaison à deux références précédentes

La voie principale de corrélation normalisée au carré ≥ 0,8 garde la priorité.
Si aucune des cinq frontières entières examinées ne la satisfait, une voie
complémentaire peut retenir une corrélation ≥ 0,65, uniquement avec un accord
d’amplitude et de phase avec les deux chirps inversés précédents.

Pour le modèle de quart `t` de longueur Q, les deux chirps précédents `r0`, `r1`
de longueur N et le quart observé `q`, le récepteur calcule :

- `a_ref = (vdot(t, r0[:Q]) + vdot(t, r1[:Q])) / (2*Q)` ;
- `a_q = vdot(t, q) / Q` ;
- `noise = mean(abs(r0-r1)**2) / 2` ;
- `S = Q * abs(a_q)**2 / noise` ;
- `D = abs(a_q-a_ref)**2 / abs(a_ref)**2`.

Les divisions sont protégées contre une énergie nulle. La cohérence normalisée
entre `r0` et `r1` doit atteindre 0,5 ; `S` doit atteindre 16 et `D` rester au
plus à 0,25. Le dernier critère impose simultanément un accord d’amplitude et
de phase complexe. L’estimation du bruit à partir de la différence suppose que
les deux chirps sont répétables ; ces critères restent des heuristiques, sans
probabilité de fausse alarme calibrée sur un bruit radio quelconque.

La meilleure corrélation parmi les frontières admissibles est choisie avant
la lecture de l’en-tête et des données. Aucun CRC ou contenu attendu ne guide
ce choix, et aucune autre frontière n’est essayée après un échec de décodage.
Les seuils des symboles de données, l’en-tête, la FEC et le CRC ne changent pas.
Les sorties exposent `quarter_chirp_method` et `quarter_reference_evidence`.
Un rejet conserve la corrélation maximale et au plus cinq essais de référence.

### Résultats et validation du quart

Le membre LoRaIQ à 7,1515 dB passe maintenant avec une corrélation de quart
d’environ 0,741, une cohérence de référence de 0,763, `S` d’environ 69,17 et
`D` d’environ 0,0724. Il restitue `0000000`, avec en-tête et CRC `0xE654` valides,
sans correction FEC des octets. Son export binaire est vérifié contre les
annotations. Le bilan local sur les mêmes sources passe ainsi à **4/6**.
Les 16 variantes temporelles du membre à 19,7319 dB restent exactes.

Les six tests de `tests/test_lora_quarter.py` vérifient les octets exacts malgré
un quart bruité sous 0,8, un CRC faux avec la même frontière choisie, la priorité
de la voie initiale, l’absence de quart avec diagnostic borné, les incohérences
de phase et d’amplitude du contrôle complémentaire, et 128 réalisations de bruit
avec des références cohérentes ou incohérentes. Les 192 tests Python passent
localement. Les tests négatifs de la voie complémentaire ne changent pas le
périmètre de la voie principale. Voir [la validation radio](LORA_REAL_VALIDATION.md).


### Recherche temporelle bornée

Le détecteur examine le début du fichier, des remontées d’énergie et des sondes
réparties. Le profil d’énergie utilise au plus 262144 échantillons répartis dans
la source ; aucune annotation ni valeur de charge utile ne guide la sélection.
Chaque fenêtre conserve la limite de 256 symboles par configuration BW/SF.
`temporal_search` décrit les fenêtres ; `search_coverage` donne leur union par
configuration, les intervalles non examinés et la fraction couverte. Cette
recherche peut manquer des paquets, notamment sous un signal plus puissant.
L’interface signale une couverture partielle lorsqu’un intervalle non examiné
peut contenir six symboles de préambule.

Les temps des candidats et des trames sont relatifs au début du fichier. Les
indices de chips restent relatifs à la fenêtre indiquée par
`analysis_window_index` et `analysis_window_start_sample`. Les observations
redondantes sont fusionnées ; deux émissions du même contenu à des instants
distincts restent deux trames. Le CRC demeure obligatoire pour exporter les
octets. Le score historique des six références LoRaIQ reste 4/6 ; les paquets
supplémentaires trouvés ailleurs ne constituent pas de nouvelles références
indépendantes.


### Voie de lecture à faible concentration spectrale

Les seuils d’énergie totale pénalisent les symboles bruités même si leur pic
de déchirpage reste identifiable. Une voie supplémentaire est réservée aux
préambules découverts par combinaison cohérente. La phase reste choisie parmi
les huit grilles par le score du préambule, avant toute lecture de l’en-tête.
Si le score individuel est inférieur à 0,65, la moyenne des blocs corrigés
doit passer le contrôle de pic décrit ci-dessous. Sa fraction d’énergie dans
le bin dominant est rapportée ; elle ne constitue plus un seuil supplémentaire. Cette voie exige toujours une correction de
porteuse cohérente et les budgets existants.

Pour un spectre de puissance déchirpé, les bins distants de plus de deux bins
du maximum servent de fond. L’estimation du bruit est leur médiane divisée
par `ln(2)` (modèle de bruit gaussien complexe). Le pic doit dépasser ce fond
d’un facteur 32 et le plus fort pic concurrent d’un facteur 4. Ce sont des
critères heuristiques : le bruit coloré, les interférences et les essais
multiples empêchent d’en déduire une probabilité de fausse alarme.

Après validation de ce préambule, les trois chirps du sync word peuvent
satisfaire ces critères au lieu du seuil individuel de concentration 0,65.
Les contraintes de nibbles et le refus d’un sync word ambigu restent actifs.
La paire de chirps opposés utilise les contrôles décrits ci-dessous. Pour le quart de
chirp final, une corrélation inférieure à 0,65 exige un pic fiable du downchirp
de référence et les contrôles de projection existants : cohérence des deux
références au moins 0,5, projection/bruit au moins 16, écart complexe relatif
au plus 0,25. Les symboles de données peuvent ensuite utiliser le même
contrôle de pic ; l’en-tête, la correction de code et le CRC ne changent pas.
Les mesures sont conservées dans `matched_peak_evidence`,
`matched_peak_symbol_evidence` et `timing_tracking`.

Les tests incluent quatre réalisations synthétiques avec bruit variable
selon les parties du paquet, un mauvais CRC avec sélection temporelle
identique, un quart manquant, des pics concurrents et du bruit blanc. Ils ne
constituent pas une mesure de sensibilité sur une population radio.


### Paire bruitée et limite de données inférée

La voie de préambule cohérent peut aussi chercher deux chirps opposés dont
les pics individuels et le pic moyen passent les critères 32/4 ci-dessus.
Les bins doivent être distants d’au plus un bin et la cohérence temporelle
des deux chirps d’au moins 0,3. Les voies précédentes gardent leur priorité.
Cette sélection est indépendante des octets, de l’en-tête et du CRC.

Si les contrôles du quart final échouent, cette voie peut inférer **une seule**
limite à 2,25 symboles après la frontière du sync word unique. Elle exige un
sync word issu de pics fiables, un préambule raffiné, une référence de fréquence
fiable, un premier symbole de données fiable et au moins huit symboles
disponibles. Elle ne décode pas les cinq positions du quart pour retenir celle
dont le CRC passe. L’en-tête et le CRC vérifient ensuite les octets à cette
position unique. Un CRC faux ne provoque aucune autre tentative de position.

Dans ce cas, `quarter_chirp_method` / `boundary_method` valent
`inferred_from_sync_word`, `quarter_chirp_validated` vaut `false` et
`inferred_boundary_evidence.boundary_hypotheses_decoded` vaut 1. Ce drapeau
accompagne la trame exportée et le JSON ; l’interface affiche « quart de chirp
non confirmé ». Le quart n’est pas présenté comme détecté, même si les données
sont conformes au CRC. Cette distinction permet aussi de restituer un paquet
synthétique dont le quart a été remplacé par du bruit, sans prétendre que sa
synchronisation physique est entièrement validée.


### Acquisition conjointe lorsque les pics individuels changent

Si les deux voies précédentes échouent, SF7–SF10 disposent d’une recherche
conjointe sur six chirps. Les fenêtres sont présélectionnées par la moyenne
non cohérente des spectres : pic/fond au moins 4 et pic/concurrent au moins
1,5. Au plus 32 fenêtres classées par pic/fond sont examinées par configuration
et polarité. Une FFT sur l’axe des six chirps, complétée à 48 points, propose
une progression de phase. Après correction de cette hypothèse, le spectre
moyen doit passer les critères de fiabilité 32/4 existants.

La concentration des amplitudes complexes déchirpées dans cette progression,
`abs(sum(a))**2 / (6*sum(abs(a)**2))`, doit atteindre 0,65. Ce contrôle rejette
notamment les symboles CSS changeants qui peuvent produire un maximum après
la recherche de phase. Le bin retenu après correction doit rester à au plus
un bin de celui du maximum conjoint. La méthode rapportée est
`phase_grid_matched_preamble`, avec les budgets et mesures.

Cette voie constitue une preuve de préambule uniquement. Son hypothèse de
fréquence n’est pas utilisée pour contourner le contrôle de cohérence du
suivi de porteuse. Aucun seuil d’en-tête, de CRC ou de synchronisation n’est
abaissé. Les fenêtres, phases ou paramètres ne sont pas choisis selon un CRC
ou des octets attendus. Les budgets s’ajoutent à ceux des voies précédentes ;
ils ne garantissent pas une recherche exhaustive du fichier.


### Porteuse estimée sur les amplitudes déchirpées

Après acquisition par grille de phase, un rejet du suivi brut peut déclencher
une estimation sur le bin commun dominant de six à huit chirps. Une FFT des
amplitudes complexes, complétée à 384 points, choisit une progression de
phase modulo un bin. Sa concentration `max(abs(FFT(a))**2)/(K*sum(abs(a)**2))`
doit atteindre 0,65. Après correction, le spectre moyen doit passer les
critères 32/4 et son bin rester à au plus un bin du bin commun initial.

La méthode est `matched_preamble_phase`. La cohérence brute reste exposée
sous `raw_lag_coherence` ; elle n’est pas rebaptisée en forte cohérence. Cette
voie utilise les amplitudes du pic pour moins intégrer le bruit hors pic.
Elle ne donne ni fréquence RF ni CFO entier, et les 384 points n’impliquent
pas une précision statistique de l’estimation. Le raffinement temporel
réestime la porteuse avec la même méthode sur la grille sélectionnée.

Aucun bit ni CRC n’intervient dans cette sélection. Les contrôles des chirps
opposés, du sync word, de l’en-tête et du CRC ne sont pas abaissés. Les tests
contrôlent notamment les offsets proches du repliement modulo un bin, les
chirps inversés, le bruit, les phases incohérentes et l’indépendance vis-à-vis
des données qui suivent le préambule.
