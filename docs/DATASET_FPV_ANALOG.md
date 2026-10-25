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

Le travail livré est le catalogue, le lecteur d'annotations et l'inspection de métadonnées. Aucun import IQ ni décodage vidéo FPV n'est revendiqué. L'API Zenodo confirme la licence CC BY 4.0 pour le jeu de données ; elle est enregistrée indépendamment de la licence d'un logiciel associé.

## Résultat de l'inspection publique

La [CI 40218880680](https://github.com/sebadiaz/IQScope/actions/runs/40218880680), commit `2fb31e3c04d521516d3d939e9713fed4067b9387`, a validé les annotations et l'inspection distante. Les 51 tests sur Python 3.10/3.12/3.13, le navigateur et les autres contrôles de corpus passent également.

Pour `chunk10.zip`, 32 019 octets ont suffi aux lectures de structure ZIP et de métadonnées internes. Trois fichiers `iq.bin` de 1 546 649 600 octets chacun sont répertoriés. Le fichier interne étudié est `chunk10/sweep_20260422_153008/metadata.csv`, avec 2 950 lignes de blocs et les colonnes :

```text
timestamp,center_freq,offset_bytes,num_samples
```

Les premières lignes indiquent des blocs de 65 536 échantillons et des offsets espacés de 524 288 octets. Cette observation est compatible avec un stockage de huit octets par échantillon déclaré ; elle ne suffit pas à choisir entre des types numériques possibles. Aucun dtype n'est donc imposé au lecteur IQ à partir de ce seul rapport.

Le CSV global porte le SHA-256 `b4e0c3747fce3a3bd8733d2538ec6743bf48728d1d1a05101cd5a09686d08e06`. Son checksum publié par Zenodo est contrôlé par le script. L'API renvoie `cc-by-4.0` pour la licence.

Le statut livré est `annotations_validated`. Il ne signifie ni lecture des données de `iq.bin`, ni identification automatique de vidéo, ni reconstruction PAL/NTSC, ni vérification d'intégrité des archives complètes.
