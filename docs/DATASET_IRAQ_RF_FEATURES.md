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
