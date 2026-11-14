# Position APRS : enregistrement matériel Pico

Le contrôle `python scripts/aprs_pico_reference.py` importe un enregistrement
matériel indépendant et exige trois paquets à CRC valide, contenant la
position compressée et l'altitude attendues. Les échantillons décodés du WAV
ont permis de reproduire localement l'échec du récepteur initial, puis de
récupérer les trois paquets avec l'estimation automatique d'horloge.

## Source et provenance

Le [projet de Thomas Glau, DL3TG](https://github.com/eleccoder/raspi-pico-aprs-tnc/blob/d78e42f10dc11d6a8e983e90927b0ecc6cd9fedd/README.md)
décrit un Raspberry Pi Pico qui produit un signal AFSK1200 au travers d'un
filtre analogique, relié à une carte son. Le WAV est **un enregistrement de
la sortie audio du matériel**. Il n'est ni généré par les tests IQScope, ni
une réception radio, ni un fichier IQ RF.

Le [WAV de 639 436 octets](https://github.com/eleccoder/raspi-pico-aprs-tnc/blob/d78e42f10dc11d6a8e983e90927b0ecc6cd9fedd/doc/aprs_pico_beacon_demo.wav)
est épinglé au commit `d78e42f10dc11d6a8e983e90927b0ecc6cd9fedd`, dont le
message indique la mise à jour de l'enregistrement avec la démonstration.
Son objet Git vaut `b5dfa24975035cb82390879fa75c54ca0587d080`. Taille, empreinte
de l'objet Git et SHA-256 sont vérifiés avant import. Le SHA-256 observé puis
épinglé vaut `4b3119170d9e5981532ce67cd67f21f3ef99064d7f9db7a691800a1a0d9b1375`.
Il est consigné dans les résultats. Le téléchargement lit au plus taille + 1
octet. `--offline` vérifie le WAV déjà en cache et `--cache-root` choisit
le répertoire. Le dépôt amont est sous GPL-3.0 ; le WAV n'est pas incorporé
au dépôt IQScope ni à son artefact de référence.

## Oracle indépendant et valeurs encodées

La [configuration publiée avec l'enregistrement](https://github.com/eleccoder/raspi-pico-aprs-tnc/blob/d78e42f10dc11d6a8e983e90927b0ecc6cd9fedd/src/aprs_pico_beacon_demo.c)
déclare `DL3TG-9`, destination `APPIPI`, chemin `WIDE1-1,WIDE2-2`, position
48,75588° N / 9,19011° E et altitude 483 m. L'[encodeur indépendant](https://github.com/eleccoder/ax25-aprs-lib/blob/2d8a85f7b5ec1f51d31c58a27f8693ebec76ce17/src/ax25beacon.c)
publie la conversion en coordonnées compressées et en pieds arrondis.
Le profil attendu est dérivé de ce code, avant le décodage du WAV :

- Mots de coordonnées base 91 : `15710957` et `36033715`, soit
  `48.755881719809096°` et `9.190105164782665°` après quantification.
- Préfixe de position `!/5n5qPkBr>` et trois espaces pour `csT` : aucune
  route ni vitesse ne doit être ajoutée.
- Annotation `/A=001585`, soit **1585 ft = 483,108 m**, distincte des
  483 m fournis à l'encodeur avant arrondi.

Le script compare chaque charge utile complète au profil attendu, ses
adresses, son CRC-16/X-25 reçu et les valeurs numériques. Les répétitions
restent des trames séparées. Le nombre de trois copies et leurs octets de
trame complets sont des régressions de développement issues des réceptions à
CRC valide ; l'auteur ne publie pas de total ni de trames complètes de référence.
La position géographique et l'altitude réelles
du matériel ne sont pas vérifiées par cette comparaison.

## Récupération automatique de l'horloge

Le récepteur initial essayait 32 phases à exactement 1200 bauds : aucune
trame valide, malgré 14 hypothèses rejetées au CRC. Les trois salves portent
des cadences estimées de 1194,8471, 1194,8298 et 1194,8542 bauds, relativement
au débit audio déclaré. L'écart d'environ −0,43 % suffit à décaler la lecture
pendant le paquet. Il ne permet pas d'attribuer l'erreur à l'horloge de
l'émetteur plutôt qu'à celle de l'enregistrement.

Après discrimination non cohérente des tonalités, les passages par zéro
fournissent des instants de transition `t_i`. Avec une période nominale
`T_nom = 40` échantillons à 48 kHz, les écarts donnent des nombres entiers
de symboles. Une régression ajuste `t_i = origine + n_i * T + résidu_i`.
Les centres de symboles sont alors `origine + (n + 1/2) * T`.

Le même algorithme s'applique à chaque chaîne de transitions, sans débit
spécifique au Pico codé dans le récepteur :

- Transitions retenues au-dessus de 3 % du maximum d'énergie des tonalités.
- Coupure de chaîne pour un écart inférieur à 0,45 symbole ou supérieur à
  8,5 symboles nominaux ; au moins 24 transitions sur 0,1 seconde.
- Cadence dans ±3 % de 1200 et résidu RMS au plus égal à 0,1 symbole.
- Au plus 50 000 transitions et 16 chaînes examinées, les plus longues en
  premier. Les 32 phases nominales restent disponibles.
- Budgets communs de 6000 couples de drapeaux et 128 trames. Les limitations
  du fit et des phases sont signalées séparément ; l'audio est borné à 20 s.

Chaque trame issue d'un fit exporte `clock_baud`, `clock_recovery` et
`timing_evidence`, dont le résidu et l'intervalle de transitions. Ses temps
utilisent le débit ajusté et restent relatifs au début du fichier.
`clock_phase_index` reste réservé aux essais de phase nominale.
Les copies de phase sont dédoublonnées ; les trois transmissions séparées
restent présentes. Le fit ne répare aucun bit et ne remplace aucun CRC.
Il n'effectue ni poursuite continue d'horloge, ni estimation des tonalités,
ni démodulation FM de données IQ.

Les tests synthétiques couvrent des cadences indépendantes de 1169 à 1230
bauds, deux salves à horloges distinctes séparées par du silence, l'origine
temporelle, le CRC corrompu, les débits hors plage, les négatifs existants et
les limites de recherche/durée. Ils complètent la capture matérielle.

## Parcours de validation

Le WAV original passe par `analyze_audio`, avec conversion mono 8 kHz par
ffmpeg et les essais AFSK1200 avec horloge estimée. Aucun réglage spécifique
au fichier, réencodage de paquets ou assouplissement du CRC n'est utilisé. Les résultats
restent dans le mode audio, avec centre RF nul.

La CI vérifie également l'import du WAV dans Chromium,
les coordonnées affichées, l'altitude, les adresses, le compteur de trames,
l'absence de mouvement/télémétrie inventés et les exports JSON. Les preuves
`summary.json`, `results/provenance.json`, `report.json`, `ax25-frames.json`
et la capture automatisée de l'interface vont dans `browser-checks`.

Cette référence vise un profil de position compressée avec altitude sur
liaison audio analogique. La validation de positions sur une réception RF,
de la télémétrie enregistrée et du frontal FM sur IQ reste à faire.
