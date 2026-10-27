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
- Une autre forme d'onde CSS répétitive peut correspondre. Le sync word, les
  downchirps de synchronisation, l'en-tête, le codage, le CRC et la charge utile
  ne sont pas décodés. Aucune identification LoRaWAN n'est effectuée.

## Validation

Références synthétiques à deux échantillons par chip, différents BW/SF,
inversion, bruit, décalages temporel et fréquentiel. Contre-exemples : bruit
blanc/coloré, porteuse et symboles CSS changeants. Tests de pipeline, export et
propagation d'une hypothèse d'encodage non vérifiée. Ces tests ne remplacent pas
une validation avec un émetteur indépendant et un paquet connu.

Les prochaines étapes sont la synchronisation du paquet et du sync word,
puis l'en-tête et la chaîne de décodage jusqu'au CRC. Cette version constitue
uniquement le premier étage de cette chaîne.
