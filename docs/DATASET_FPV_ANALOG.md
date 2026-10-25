# FPV Analogue Video IQ Dataset

Source : [Zenodo 19870020](https://zenodo.org/records/19870020), Yelyzaveta Mashchenko, version 1, publiée le 29 avril 2026. DOI : `10.5281/zenodo.19870020`.

## Ce qui est établi

La description annonce des IQ capturés avec HackRF One, des transmissions vidéo analogiques et des essais sans émetteur actif. Le dépôt contient dix archives ZIP et un CSV récapitulatif, pour environ 26,8 Go. La prévisualisation de `chunk10.zip` montre plusieurs dossiers de balayage, chacun avec `iq.bin` et `metadata.csv`.

Le CSV récapitulatif présente 48 essais : 38 avec émetteur cible actif et 10 sans émetteur cible actif. Il décrit notamment puissance, distance, environnement, obstacles, différence d'étage et réglages de gain. Certaines distances sont des plages, conservées comme telles.

Le lien logiciel associé au dépôt a retourné 404 pendant l'examen. Aucun code de ce projet n'est installé ou exécuté par IQScope.

## Lecture des annotations

```bash
iqscope dataset-annotations fpv_analog iq_recording_meta.csv
```

Le lecteur gère les particularités du header source, dont un antislash final dans un nom de colonne, des espaces et une faute dans `obtacles`. Il conserve les noms d'origine, les valeurs brutes et les relations avec `iq_folder`, et refuse les identifiants dupliqués ou les états émetteur/puissance contradictoires.

L'étiquette s'applique à l'expérience de balayage. Un émetteur cible inactif ne signifie pas que la bande ne contient que du bruit. Un émetteur actif ne garantit pas que toutes les fenêtres de toutes les fréquences du balayage contiennent son signal.

Les valeurs numériques isolées de `sample_rate`, `samples_per_freq` et `drone_freq` ne sont pas converties automatiquement en Hz, éch/s ou durées. Leurs unités et leur correspondance avec les offsets IQ doivent être vérifiées dans les métadonnées de chaque balayage. Le taux brut « 20 » n'est notamment jamais utilisé comme 20 éch/s par ce lecteur.

## Inspection bornée des archives

`scripts/fpv_metadata_probe.py` télécharge le petit CSV et consulte les métadonnées Zenodo. Un lecteur ZIP distant utilise des requêtes HTTP Range pour lire le répertoire et un fichier `metadata.csv` interne de `chunk10.zip`, avec un budget de 1 Mio pour ces requêtes.

Le script refuse un serveur ignorant les plages demandées, les réponses de taille incohérente et les métadonnées dépassant son budget. Il ne décompresse ni n'extrait `iq.bin`. Les contrôles d'intégrité de ZIP s'appliquent au petit membre de métadonnées effectivement lu, pas aux fichiers IQ non lus.

```bash
python scripts/fpv_metadata_probe.py
```

Les rapports indiquent licence renvoyée par l'API, comptes d'annotations, noms et tailles des IQ, premières lignes des métadonnées internes et octets transférés. Le checksum du CSV est vérifié contre celui publié par Zenodo.

## Intégration IQ à construire

1. Établir précisément représentation I/Q, signedness, taille et ordre des composantes.
2. Vérifier les unités, les offsets et longueurs de chaque accord dans `metadata.csv`.
3. Importer les segments avec leur propre fréquence centrale et marquer les transitions de balayage.
4. Vérifier la détection de vidéo cible sur les expériences annotées et sur les négatifs.
5. Ajouter une chaîne vidéo analogique : démodulation adaptée, synchronisation lignes/trames, identification du standard et reconstruction des images.

Des segments de balayage à des fréquences différentes ne sont pas concaténés en une capture cohérente. La présence d'un signal vidéo ne prouve pas que la durée et la bande enregistrées permettent de reconstruire une image complète. Le démodulateur audio FM actuel n'est pas un décodeur vidéo.

## Limite actuelle

Le travail livré est le catalogue, le lecteur d'annotations et l'inspection de métadonnées. Aucun import IQ ni décodage vidéo FPV n'est revendiqué. La licence effective doit être enregistrée depuis la notice du jeu de données ; elle n'est pas déduite de la licence d'un logiciel associé.
