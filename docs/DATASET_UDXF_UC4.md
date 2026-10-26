# UDXF Utility Collection 4 : références audio

Page examinée le 26 octobre 2026 : [UDXF UC4](https://www.udxf.nl/uc4.html).
Les six liens sélectionnés renvoient vers des fichiers MP3 (`audio/mpeg` annoncé
lors de la consultation). Ce sont des références d'audio de récepteur ; aucun
lien IQ brut n'a été établi pour cette sélection.

## Sélection initiale

| Identifiant local | Indication de la source | Usage proposé |
|---|---|---|
| `fdc_cw` | FDC FAF Metz, marqueur CW | Essai CW sur audio |
| `vtk_cw` | VTK, CW | Essai CW sur audio |
| `link11` | Link-11 | Référence de mode, aucun décodeur ajouté |
| `rnzaf` | Voix et MIL-STD-110A | Référence de mode, aucun décodeur ajouté |
| `akula` | Akula | Référence de mode, aucun décodeur ajouté |
| `singapore` | Voix, FSK et PSK | Référence de mode, aucun décodeur ajouté |

Les noms de stations et de modes viennent du site ; ils ne constituent pas une
identification indépendante. Certaines dates ou attributions de la page et des
noms de fichiers divergent. Le manifeste conserve ces ambiguïtés sans les
convertir en vérité terrain.

## Inspection reproductible

```bash
python scripts/udxf_audio_probe.py
python scripts/udxf_audio_probe.py --name fdc_cw
```

Dépendance optionnelle : `ffmpeg`. Par défaut : `fdc_cw`, `vtk_cw`, `link11`.
Le téléchargement s'arrête à 1 Mio par fichier, même si le serveur ignore Range.
La sonde décode au plus 20 secondes, en mono à 8 kéch/s, puis applique Hilbert
avant un essai du décodeur CW existant. Un signal analytique construit depuis
l'audio ne restitue ni le centre RF, ni la phase RF, ni la bande d'origine.
Les fréquences d'essai sont des fréquences audio ; zéro ne représente pas une
fréquence de réception RF.

Les rapports contiennent URL, taille reçue, empreinte du préfixe, durée décodée,
statistiques audio et éventuels textes candidats. Ils ne certifient ni le fichier
complet, ni le mode, ni le contenu. Un succès de la sonde prouve le téléchargement
et le décodage audio bornés ; il ne nécessite pas de candidat CW et ne prouve pas
la reconnaissance de Link-11 ou d'un autre mode.

Les octets MP3 ne sont pas stockés dans Git ni dans les artefacts CI. Les droits
de redistribution ne sont pas établis. Les téléchargements sont temporaires ;
seuls les rapports sont conservés. L'interface d'import IQ continue de refuser
ces MP3 : aucun faux canal I/Q n'est créé et aucune fréquence RF n'est inventée.

## Validation observée le 26 octobre 2026

Exécution vérifiée : [CI 40321949433](https://github.com/sebadiaz/IQScope/actions/runs/40321949433).
Le [résumé des résultats](../corpus/udxf_audio_validation.json) conserve les
empreintes des préfixes et les hypothèses, sans les fichiers audio.

| Extrait | Octets reçus | Audio décodé | Essai CW |
|---|---:|---:|---|
| `fdc_cw` | 331 904 | 20 s | Deux textes candidats, environ 24 mots/min |
| `vtk_cw` | 711 365 | 20 s | Aucun candidat cohérent |
| `link11` | 275 434 | 20 s | Aucun candidat cohérent ; aucune reconnaissance Link-11 effectuée |

Le meilleur texte FDC contient `VVV` répété, puis `DE FDC FDC FDC AR`.
Le préfixe initial diffère entre les deux hypothèses (`HV` ou `IV`) et peut
comprendre un caractère tronqué. Les groupes `AR` ne sont pas interprétés comme
un prosigne par ce décodeur. Le timing fournit une cohérence heuristique, pas un
CRC, une transcription de référence ni une authentification. Ce résultat est
une première observation sur audio réel, pas une mesure du taux d'erreur CW.
L'absence de candidat pour les autres extraits ne confirme ni n'infirme leur mode.

Les tests locaux vérifient la borne de lecture, la conversion audio bornée et un
texte CW synthétique indépendant. Les contrôles Python et navigateur passent ;
le catalogue distingue toujours ces références audio des imports IQ.
