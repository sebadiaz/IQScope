# AO-40 FEC : première charge utile AO-73

La voie AO-40 FEC est automatique sur l’audio de récepteur et les IQ complexes directs entre 1 et 96 kéch/s. Elle traite le format standard DBPSK à 5200 symboles, sur les six premières secondes seulement. Les formats courts et Manchester, la recherche multicanal large bande et la poursuite interfenêtres ne sont pas implémentés.

## Résultat radio

Sur le WAV AO-73 du [corpus épinglé](https://github.com/daniestevez/satellite-recordings/blob/952ddfe53f62a150c53559249c83370630254cab/ao73.wav), la chaîne récupère **256 octets** : SHA-256 `220bb05857d4220084ca46bcb7e48759226935627a25767144d588dc4a43b112`. La synchronisation distribuée correspond aux 65 bits attendus sans erreur ; les deux chemins Reed-Solomon passent sans correction de symbole après Viterbi. Le débit estimé est d’environ 1202,10 bauds.

L’empreinte est une référence de régression issue du premier décodage FEC valide pendant le développement, pas des octets attendus fournis indépendamment par l’auteur. Le matériel de réception et l’identité de l’émetteur ne sont pas établis par ce résultat. La source est de l’audio mono, sans reconstruction de la fréquence ou phase RF d’origine. La télémétrie n’est pas interprétée.

## Acquisition et validation

Le plus haut pic de la puissance seconde était ici une raie liée à l’horloge, autour de 1202 Hz. La composante de porteuse au carré était étalée autour de 2200 Hz et moins haute dans une seule case FFT. L’acquisition du suivi BPSK recherche désormais une bande concentrant l’énergie, avec une largeur de 80 % du taux de suivi et un contraste d’au moins cinq fois la moyenne spectrale. Le suivi reste limité sous l’horloge symbole. Les seuils d’acceptation des candidats PSK génériques restent inchangés.

La nouvelle voie de protocole peut examiner des symboles souples rejetés par ces seuils, **sans les promouvoir en candidat PSK générique**. L’EVM reste enregistrée comme diagnostic (environ 36 % sur cet essai AO-73). Une charge utile est acceptée uniquement après la chaîne suivante :

1. Décisions DBPSK souples par produit différentiel des symboles complexes.
2. Synchronisation répartie : 65 bits espacés de 80 symboles, au plus huit désaccords.
3. Désentrelacement matriciel du bloc de 5200 symboles ; retrait des 65 symboles de synchronisation, conservation de 5132 symboles codés.
4. Viterbi souple, code convolutionnel K=7, taux 1/2, polynômes 79 et −109, état initial/final zéro et six bits terminaux.
5. Dérandomisation CCSDS, séquence initiale `ff480ec09a0d70bc`.
6. Deux chemins entrelacés RS raccourcis (160,128), issus de RS(255,223), GF(256) avec polynôme `0x187`, première racine 112 et générateur α^11. La bibliothèque `reedsolo==1.7.0` corrige les blocs. Chaque bloc corrigé doit aussi correspondre exactement au réencodage de ses 128 octets.

Les paramètres sont documentés dans le [déframeur gr-satellites](https://github.com/daniestevez/gr-satellites/blob/b9fee473d616b1b3ab3ebff1958c2fcb09d264be/python/components/deframers/ao40_fec_deframer.py). Les opérations mathématiques sont implémentées dans IQScope ; aucun code gr-satellites n’est incorporé. La dépendance Reed-Solomon est distribuée sous choix [Unlicense ou MIT-0](https://github.com/tomerfiliba-org/reedsolomon/blob/v1.7.0/LICENSE).

Les limites sont quatre essais synchronisation/FEC sur l’ensemble des filtres RRC et un paquet accepté par analyse. Le champ `duration_limited` signale un fichier plus long que la fenêtre de six secondes. Les fenêtres trop courtes pour contenir 5200 symboles ne permettent pas de conclure à l’absence du protocole.

## Interface et intégrité

Le format AO-73/AO-40 traité ici ne fournit pas de CRC supplémentaire dans cette chaîne. Le rapport utilise `crc_valid: null` et `crc_check: not_present`. L’interface affiche **« deux blocs Reed-Solomon vérifiés »**, propose le fichier binaire de 256 octets et un rapport JSON, et laisse le compteur des trames à CRC inchangé. La correction d’erreurs et la vérification de parité ne constituent pas une authentification.

Les fichiers sont `ao40-payload-N.bin` et `ao40-frames.json`. Les rapports séparent nombre d’erreurs de synchronisation, corrections RS et EVM des symboles amont. Le décodeur Viterbi et la bibliothèque Reed-Solomon ne sont pas présentés comme une preuve d’identité ou de sémantique de télémétrie.

## Vérifications

Les tests emploient un émetteur de référence indépendant : registre convolutionnel série, PN sous forme de file de bits et entrelaceur inverse. Ils vérifient un préfixe CCSDS connu, les octets récupérés, des erreurs de canal, huit erreurs RS, l’ambiguïté de polarité, le bruit, les trames tronquées et une synchronisation forcée suivie de données invalides. Un bon mot de synchronisation seul ne doit pas produire de charge utile.

`python scripts/psk_radio_reference.py` vérifie désormais AO-73 en plus de PicSat et PW-Sat2. Chromium importe le vrai WAV, télécharge les 256 octets et vérifie que le compteur CRC reste à zéro. Les références sont des données de développement, pas un corpus indépendant tenu à l’écart. Les autres trames radio et les candidats génériques gardent leurs validations respectives.
