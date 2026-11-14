# Position APRS : enregistrement matériel Pico

Le contrôle `python scripts/aprs_pico_reference.py` est préparé pour vérifier
une position et une altitude sur un enregistrement indépendant. Les tests des
valeurs attendues passent localement ; l'exécution du WAV et de l'interface
reste à valider en CI.

## Source et provenance

Le [projet de Thomas Glau, DL3TG](https://github.com/eleccoder/raspi-pico-aprs-tnc/blob/d78e42f10dc11d6a8e983e90927b0ecc6cd9fedd/README.md)
décrit un Raspberry Pi Pico qui produit un signal AFSK1200 au travers d'un
filtre analogique, relié à une carte son. Le WAV est **un enregistrement de
la sortie audio du matériel**. Il n'est ni généré par les tests IQScope, ni
une réception radio, ni un fichier IQ RF.

Le [WAV de 639 436 octets](https://github.com/eleccoder/raspi-pico-aprs-tnc/blob/d78e42f10dc11d6a8e983e90927b0ecc6cd9fedd/doc/aprs_pico_beacon_demo.wav)
est épinglé au commit `d78e42f10dc11d6a8e983e90927b0ecc6cd9fedd`, dont le
message indique la mise à jour de l'enregistrement avec la démonstration.
Son objet Git vaut `b5dfa24975035cb82390879fa75c54ca0587d080`. Taille et
empreinte de l'objet Git sont vérifiées avant import ; le SHA-256 calculé
est consigné dans les résultats. Le téléchargement lit au plus taille + 1
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
restent des trames séparées. La position géographique et l'altitude réelles
du matériel ne sont pas vérifiées par cette comparaison.

## Parcours de validation

Le WAV original passe par `analyze_audio`, avec conversion mono 8 kHz par
ffmpeg et les essais AFSK1200 existants. Aucun réglage spécifique au fichier,
réencodage de paquets ou assouplissement du CRC n'est prévu. Les résultats
restent dans le mode audio, avec centre RF nul.

La CI est configurée pour vérifier ensuite l'import du WAV dans Chromium,
les coordonnées affichées, l'altitude, les adresses, le compteur de trames,
l'absence de mouvement/télémétrie inventés et les exports JSON. Les preuves
`summary.json`, `results/provenance.json`, `report.json`, `ax25-frames.json`
et la capture automatisée de l'interface vont dans `browser-checks`.

Cette référence vise un profil de position compressée avec altitude sur
liaison audio analogique. La validation de positions sur une réception RF,
de la télémétrie enregistrée et du frontal FM sur IQ reste à faire.
