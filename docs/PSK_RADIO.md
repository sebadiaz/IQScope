# Référence radio BPSK : audio PW-Sat2 et trames AX.25

IQScope importe désormais les enregistrements audio de récepteur en mode PSK, recherche automatiquement des salves et suit une porteuse BPSK variable. Des trames AX.25 UI peuvent être extraites après désembrouillage G3RUH, avec vérification du CRC-16/X-25 par IQScope et téléchargement de la charge utile binaire.

## Référence indépendante de la génération synthétique

Les sources sont les WAV mono à 48 kHz de la [collection satellite-recordings](https://github.com/daniestevez/satellite-recordings/tree/952ddfe53f62a150c53559249c83370630254cab). Le dépôt les fournit comme enregistrements de satellites amateurs pour tester les décodeurs, sous [Unlicense](https://github.com/daniestevez/satellite-recordings/blob/952ddfe53f62a150c53559249c83370630254cab/LICENSE). Le matériel et les conditions de réception n’ont pas été établis indépendamment.

| Source épinglée | Taille | SHA-256 |
| --- | ---: | --- |
| `pwsat2.wav` | 1 284 374 octets | `017910fff961278abb9b0ea97c9302e5740940bb5226008e3de8c2353fb8180a` |
| `ao73.wav` | 535 530 octets | `d8758c1a860309185dc2b863a431b2266e050fb0e7c8e8d6d1f67a5b206ace9c` |

La [description PW-Sat2 de gr-satellites](https://github.com/daniestevez/gr-satellites/blob/b9fee473d616b1b3ab3ebff1958c2fcb09d264be/python/satyaml/PW-Sat2.yml) annonce notamment BPSK 1200 bauds avec AX.25 G3RUH. Ces indications servent à comparer les résultats ; ni débit, ni fréquence RF, ni indicatif ne sont fournis à la chaîne DSP. La [description AO-73](https://github.com/daniestevez/gr-satellites/blob/b9fee473d616b1b3ab3ebff1958c2fcb09d264be/python/satyaml/AO-73.yml) annonce DBPSK 1200 et AO-40 FEC : cette couche FEC n’est pas implémentée ici.

Ces fichiers sont de l’**audio mono de récepteur, pas des IQ RF originaux**. L’import produit de l’audio à 8 kHz via ffmpeg, puis un signal analytique par Hilbert et une interpolation ×2 pour la résolution numérique de synchronisation. L’interpolation ne crée aucune bande passante. Les fréquences restent audio, le centre RF reste absent et aucune phase RF originale n’est reconstruite.

## Recherche et suivi automatiques

L’énergie est mesurée par blocs de 10 ms. Les intervalles dépassant de 20 dB le 30e percentile d’énergie sont retenus, avec au moins 150 ms utiles et un retrait de 20 ms au début. Jusqu’à quatre salves de trois secondes au plus sont examinées, dans l’ordre du fichier. Sans salve, la recherche porte sur les trois premières secondes. L’import audio reste limité aux 1–20 premières secondes demandées. Les salves faibles et les collisions peuvent échapper à cette règle.

Après les essais RRC à fréquence constante, une voie BPSK supplémentaire suit la phase de la puissance seconde : mélange autour d’une raie estimée, filtrage/décimation sous l’horloge symbole, puis dépliage de phase et correction. Le suivi reste local à chaque fenêtre. Un garde final de 30 ms écarte les erreurs de bord du suivi. Les seuils EVM précédents restent inchangés : 16 % globalement et 18 % dans chaque moitié. Cette nouvelle voie de suivi vise **BPSK**, pas la poursuite de porteuse QPSK variable.

La fréquence indiquée après suivi résume l’estimation par sa médiane ; l’intervalle p10–p90 est également enregistré. Le filtre RRC affiché reste un essai accepté, sans certification du filtre émetteur. Des sauts de branche et des erreurs de bits restent possibles sans contrôle de trame.

## Résultats actuels

Sur PW-Sat2, la recherche trouve trois salves. Deux donnent des candidats BPSK, vers **1196,26 bauds**, puis deux trames AX.25 UI à FCS valide. La troisième salve reste sans candidat accepté. Les adresses décodées contiennent `PWSAT2` ; cela ne prouve pas l’identité de l’émetteur.

| Charge utile | Taille | SHA-256 de régression |
| --- | ---: | --- |
| première trame | 180 octets | `4171091c943892f60041564c49e595dc1888a0c19fcc19914b904cf31d92b86c` |
| seconde trame | 230 octets | `6565ab6859ecad80f3415ff1cd000238e44c64df9e63aaf13274ae22b3156137` |

Ces empreintes sont des références de régression issues du premier décodage à CRC valide pendant le développement ; elles ne sont pas des octets attendus fournis indépendamment par l’auteur de l’enregistrement. Le contrôle d’intégrité repose sur le FCS et la structure AX.25 UI. Les octets sont exportés sans interprétation de télémétrie, reconstruction d’image ou authentification.

AO-73 est conservé dans le même contrôle : actuellement aucun candidat ni aucune trame acceptés sur la fenêtre examinée. Ce résultat ne prouve pas l’absence de BPSK dans le fichier. Le contrôle ne transforme pas ce cas en test exigeant une abstention permanente : une amélioration future peut produire davantage de résultats.

## AX.25 et exports

Pour au plus huit candidats BPSK de 50 000 bits, le désembrouilleur autosynchronisant utilise `sortie[i] = entrée[i] XOR entrée[i−12] XOR entrée[i−17]`. Les 17 premiers états sont omis et les temps/indices de bits sont corrigés. Le décodeur existant essaie NRZI/NRZ, retire le bit stuffing HDLC, puis exige le CRC-16/X-25 et les champs d’une trame UI. Les limites existantes de 128 trames et 2000 paires de fanions restent actives.

Le rapport distingue les symboles PSK candidats des trames validées. Seules ces dernières augmentent le compteur CRC. Les artefacts `psk-ax25-frames.json` et `psk-ax25-payload-N.bin` conservent la structure et les octets de la charge utile. L’interface propose leurs téléchargements.

## Vérification reproductible

`python scripts/psk_radio_reference.py` télécharge les deux fichiers avec bornes de taille et SHA-256, utilise l’import audio réel, vérifie les deux trames PW-Sat2 et leurs exports, et enregistre les résultats AO-73, les fenêtres examinées et la provenance. Les WAV restent dans `corpus-cache/`, sans inclusion dans le paquet ni dans les artefacts CI.

Chromium importe PW-Sat2 par l’interface en mode audio, vérifie les deux trames, l’absence de fréquence RF et le téléchargement exact de 180 octets. Les tests synthétiques vérifient séparément le suivi BPSK variable, la détection de salve, le désembrouillage par un émetteur à registre indépendant et le rejet d’une trame corrompue. Ce corpus sert au développement : une évaluation indépendante plus large reste à constituer.
