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
  et le sync word restent des hypothèses. L'en-tête, le codage, le CRC et la
  charge utile ne sont pas décodés. Aucune identification LoRaWAN n'est effectuée.

## Validation

Références synthétiques à deux échantillons par chip, différents BW/SF,
inversion, bruit, décalages temporel et fréquentiel. Contre-exemples : bruit
blanc/coloré, porteuse et symboles CSS changeants. Tests de pipeline, export et
propagation d'une hypothèse d'encodage non vérifiée. Ces tests ne remplacent pas
une validation avec un émetteur indépendant et un paquet connu.

Les prochaines étapes sont la synchronisation fine du paquet,
puis l'en-tête et la chaîne de décodage jusqu'au CRC. Cette version constitue
uniquement le premier étage de cette chaîne.

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
le quart de chirp, l'horloge, l'en-tête et le CRC restent à traiter.

Validation synthétique : plusieurs valeurs (dont 0x34, 0x12, 0x00 et 0xAB),
SF7/SF8/SF9/SF12, inversion, bruit, délais différents et décalages fréquentiels
de quelques bins. Des symboles hors convention sont rejetés. Aucun paquet réel
connu n'est encore validé ; le résultat n'est pas compté comme une trame.
