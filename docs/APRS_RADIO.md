# Référence APRS enregistrée : paquet ISS

État : les bits publiés ont été vérifiés localement avec CRC correct. Le
contrôle du WAV et celui du navigateur sont préparés, mais n'ont pas encore
été exécutés : le téléchargement binaire local et la publication vers la CI
n'ont pas abouti. Leur réussite n'est donc pas revendiquée ici.

`python scripts/aprs_radio_reference.py` télécharge une seule capture audio
AFSK1200 de 70 444 octets, puis appelle l'import audio automatique complet.
`--offline` réutilise la source en cache après vérification de son intégrité ;
`--cache-root` choisit le répertoire de travail.

Le [TP de Berkeley](https://www-inst.cs.berkeley.edu/~ee123/sp17/lab/lab5/Lab5_Part_C-APRS.html)
décrit `ISSpkt.wav` comme un paquet enregistré lors d'un passage de l'ISS.
Le fichier est téléchargé depuis un [miroir étudiant du cours](https://github.com/lm-t/ee123-labs/tree/bb0f4dfdc876f4b13d75c25621766895bb4d2ad0/lab5),
épinglé au commit `bb0f4dfdc876f4b13d75c25621766895bb4d2ad0`.
Son objet Git vaut `7333932b16fc2c4bfa7bfef5a5301922370f6b91`.
La taille et le SHA-1 de l'objet Git complet sont contrôlés avant l'import ;
le SHA-256 du WAV est ensuite conservé dans les résultats. Aucune licence
explicite de redistribution de l'enregistrement n'a été identifiée dans ce
miroir : le WAV n'est pas incorporé au dépôt ni aux artefacts de référence.

Le [notebook épinglé](https://github.com/lm-t/ee123-labs/blob/bb0f4dfdc876f4b13d75c25621766895bb4d2ad0/lab5/Lab5-APRS.ipynb)
publie les bits NRZ après démodulation et le résultat attendu. Ils fournissent
un oracle indépendant du décodeur IQScope : source `RS0ISS`, destination `CQ`,
SSID 0, aucun relais, UI/PID `0xf0`, texte de statut
`>ARISS - International Space Station` et CRC reçu `0x84fb`.
La vérification exige exactement une trame, identique octet par octet au
paquet publié, avec CRC-16/X-25 correct. Les tests unitaires sur ces bits
vérifient uniquement l'étage AX.25 ; la démodulation du WAV est testée
séparément par le script de référence et l'import navigateur en CI.

La source reste inchangée : ffmpeg la convertit en mono à 8 kHz, puis la
chaîne essaie automatiquement ses 32 phases AFSK1200 fixes. Aucun bourrage
audio, réglage manuel de phase, correction de bits ou remplacement par un
signal généré n'est utilisé. Les fichiers audio d'au moins 0,2 seconde sont
acceptés ; chaque décodeur conserve ses propres limites de durée. Le budget
demandé reste de 1 à 20 secondes au maximum, sans rallonger un fichier court.

La CI vérifie également le dépôt du WAV dans l'interface, le texte et les
adresses affichés, le compteur d'une trame CRC et les exports JSON.
`summary.json`, `results/provenance.json`, `report.json` et `ax25-frames.json`
sont disponibles dans l'artefact `browser-checks`.

Cette référence couvre **un paquet de statut APRS enregistré en audio**.
Elle ne valide ni les positions, ni la télémétrie, ni un frontal FM sur IQ RF,
ni le temps réel, ni l'identité de l'émetteur. Les champs de position restent
absents et le centre RF reste nul. Les autres formes APRS conservent leurs
tests de syntaxe publiés et leurs régressions synthétiques.
