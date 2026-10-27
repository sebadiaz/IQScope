# Iraq RF Spectrum : tableaux de caractéristiques

Source : [Mendeley v2zmysy94r, version 1](https://data.mendeley.com/datasets/v2zmysy94r/1),
DOI `10.17632/v2zmysy94r.1`. L'identité et la licence CC BY 4.0 ont été vérifiées
via les métadonnées publiques Mendeley et DataCite.

## Nature du corpus

Les auteurs publient des caractéristiques calculées depuis des enregistrements
RTL-SDR acquis en Irak. Ils annoncent 24 844 740 lignes de fenêtres, 84 colonnes,
297 enregistrements sources et 20 jours de mesure. Les fenêtres décrites portent
sur 8 192 échantillons complexes à 2,048 Méch/s, soit 4 ms nominalement. Les
catégories et bandes annoncées couvrent notamment FM, VHF/UHF, ISM/LoRa, des
bandes GSM et ADS-B. Ces catégories sont des annotations, pas des validations de
protocole effectuées par IQScope.

Deux fichiers CSV gzip représentent environ 10,57 Go compressés à eux seuls.
La liste publiée comporte aussi `metadata.csv`, `feature_description.csv` et
`README.txt`. Ce dépôt de tables ne doit pas être importé comme une forme d'onde
IQ. Les auteurs renvoient les IQ bruts vers des enregistrements Zenodo distincts.

## Intégration

Le catalogue utilise `kind: derived_features`, `adapter: null` et un rôle de
future évaluation de détection/classification à partir de caractéristiques.
Aucune reconstruction IQ, ligne de caractéristiques ou charge utile radio n'est
importée. Les lignes de fenêtres d'un même enregistrement sont fortement liées :
les évaluations devront séparer les enregistrements et jours, puis suivre le
recouvrement avec les IQ sources, plutôt que mélanger des fenêtres au hasard.

La sonde `scripts/mendeley_metadata_probe.py` lit des métadonnées publiques
bornées et au plus trois petits fichiers de documentation CSV/texte (64 Kio
chacun). Elle ne télécharge ni les gros CSV gzip ni les IQ. Les URL de
téléchargement signées ne sont pas conservées dans le rapport. Le
[manifeste](../corpus/mendeley-v2zmysy94r.json) sépare les chiffres annoncés des
contrôles effectivement réalisés.


## Observations vérifiées

Le [contrôle 40401653123](https://github.com/sebadiaz/IQScope/actions/runs/40401653123)
a obtenu les métadonnées DataCite et l'API publique du dataset. Le DOI, la version
1, le titre, la licence et les noms/tailles des cinq fichiers concordent.
Le [résumé conservé](../corpus/mendeley-v2zmysy94r-observation.json) distingue ces
vérifications des déclarations de volume contenues dans la description.

Les téléchargements de `README.txt`, `metadata.csv` et `feature_description.csv`
ont tous renvoyé HTTP 403 dans cet environnement. Aucune ligne de ces fichiers
n'a donc été inspectée ; les nombres de lignes et colonnes restent des chiffres
annoncés. Le succès du job de sonde signifie que les observations ont été
produites, pas que les fichiers sont importables.

### Sources IQ : métadonnées vérifiées, échantillons non inspectés

- [Zenodo 22019720](https://zenodo.org/records/22019720)
- [Zenodo 22036530](https://zenodo.org/records/22036530)
- [Zenodo 22046487](https://zenodo.org/records/22046487)
- [Zenodo 22052172](https://zenodo.org/records/22052172)
- [Zenodo 22071547](https://zenodo.org/records/22071547)

Ces liens viennent de l'API Mendeley. La [sonde Zenodo exécutée en CI](https://github.com/sebadiaz/IQScope/actions/runs/40484096396)
a obtenu HTTP 200 pour les cinq notices. Chacune déclare sa propre licence
`cc-by-4.0`, un accès ouvert et des mesures IQ RTL-SDR V3 à 2,048 Méch/s.
Le [rapport d'inventaire](../corpus/iraq-zenodo-observation.json) conserve les
identités, tailles et sommes MD5 annoncées ; les archives n'ont pas été
téléchargées et ces sommes n'ont donc pas été vérifiées sur leurs octets.

Les cinq parties couvrent les jours 1 à 20. Les fichiers sont essentiellement
des ZIP de plusieurs Go, avec un petit document Markdown par partie et un CSV
de métadonnées global dans la partie 5. Le découpage d'une journée en plusieurs
archives ne crée pas des journées indépendantes pour l'évaluation.

**Écart de provenance à résoudre :** la description Zenodo de la partie 5 annonce
295 enregistrements bruts, contre 297 sources dans Mendeley. Ne pas présumer une
correspondance un à un avant comparaison des identifiants dans les deux tables.

La sonde `scripts/iraq_zenodo_probe.py` limite chaque réponse JSON à 1 Mio et
refuse une identité de notice différente. Aucun fichier radio n'est demandé.
Le type numérique, l'ordre I/Q, le boutisme, les éventuels en-têtes et la
correspondance des annotations restent à vérifier dans la documentation puis
sur un extrait borné. Aucune validation LoRa, GSM ou ADS-B n'est déduite des
noms de bandes. Ces parties restent des sources de provenance, sans nouvelle
entrée de capture validée dans le catalogue.

### Documentation source inspectée

Le [contrôle 40500221026](https://github.com/sebadiaz/IQScope/actions/runs/40500221026)
a lu les cinq documents Markdown et le CSV global (150 700 octets), avec
vérification de la taille et de la somme MD5 publiées pour chacun des six
fichiers. Le [rapport](../corpus/iraq-zenodo-documentation.json) conserve les
sommes SHA-256, colonnes et observations.

Le CSV contient effectivement **295 lignes et 37 colonnes**, couvrant Day1 à
Day20. Les valeurs de fréquence d'échantillonnage sont toutes `2048000`.
Les formats renseignés sont `Complex Float32 IQ (complex64)` ou
`Raw complex64 IQ` ; certaines cellules de format sont vides. Le document de
la partie 1 précise que l'extension `.iq` ne définit pas l'encodage numérique.
Le boutisme, l'ordre des composantes et l'absence d'en-tête ne sont pas
explicitement établis par ces documents. Un futur import devra donc conserver
ces hypothèses et les confronter aux octets d'un extrait borné.

L'écart avec les 297 sources annoncées côté Mendeley reste ouvert : le CSV
Zenodo confirme le nombre 295 mais n'explique pas cette différence. Les noms de
bandes restent des annotations ; ils ne certifient pas la présence d'une trame
LoRa, GSM ou ADS-B. Les heures estimées et l'absence de calibration RF externe
sont explicitement documentées. Aucune archive IQ n'a été téléchargée à ce stade.

### Premier extrait IQ borné

La [sonde 40502220779](https://github.com/sebadiaz/IQScope/actions/runs/40502220779)
a inspecté l'index de `Day1-1.zip` par requêtes HTTP Range exactes et lu les
65 536 premiers octets de `Day1-1/Day1-1/loraism-outdoor_915e6MHz.iq`.
Le transfert total observé est de 66 335 octets ; aucune archive complète n'est
 téléchargée. L'index contient quatre fichiers IQ. Le
[rapport](../corpus/iraq-iq-prefix-observation.json) conserve leurs tailles,
le SHA-256 du préfixe et les hypothèses numériques.

En supposant du complexe float32 sans en-tête, le préfixe représente 8 192
échantillons, soit 4 ms au débit déclaré. Les deux boutismes donnent des valeurs
finies ; le RMS est environ 0,0202 en petit-boutiste contre 2,64e23 en
grand-boutiste. Cela favorise l'hypothèse petit-boutiste pour ce préfixe, sans
certifier l'ordre I/Q, l'absence d'en-tête ou tous les fichiers du corpus.
Aucune sélection automatique, conversion validée ou reconnaissance LoRa n'est
réalisée. Le nom 915 MHz reste une indication du nom de fichier. Les sommes de
l'archive entière et le CRC du membre entier ne sont pas vérifiés sur ce préfixe.

La sonde limite ses lectures réseau à 1 Mio et le préfixe décompressé à 64 Kio.
Le fichier binaire reste hors des artefacts CI ; seul le rapport JSON est publié.
