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

### Conversion candidate vers SigMF

Depuis un préfixe local de 8 à 64 Kio, contenant des paires float32 complètes :

```sh
python scripts/iraq_iq_probe.py --local-prefix prefix.bin --out /tmp/iraq-candidate
```

La commande produit deux paires `.le.sigmf-data`/`.le.sigmf-meta` et
`.be.sigmf-data`/`.be.sigmf-meta`. Les fichiers de données conservent exactement
les octets du préfixe ; la commande vérifie leur lecture par `read_iq` pour les
deux interprétations. Elle refuse tout écrasement. Aucun téléchargement n'est
effectué avec `--local-prefix`.

Les métadonnées reprennent le débit publié de 2 048 000 échantillons/s sans
fréquence RF vérifiée, et portent `iqscope:byte_order_status` à
`unverified_hypothesis`. Charger une de ces métadonnées SigMF dans l'interface
conserve donc l'incertitude dans le rapport d'analyse. Le boutisme, l'ordre I/Q
et l'absence d'en-tête restent des hypothèses ; la conversion ne certifie aucun
protocole. La sonde réseau effectue également cette relecture sur le préfixe
réel ; ses artefacts publics ne contiennent que le rapport JSON.

Le [contrôle réel 40502855066](https://github.com/sebadiaz/IQScope/actions/runs/40502855066)
confirme la conservation exacte des octets et la relecture des 8 192 échantillons
pour chacune des deux hypothèses. Ces contrôles de cohérence ne choisissent pas
le boutisme et ne vérifient pas le CRC du fichier IQ entier.

### Analyse explicite d'une hypothèse

```sh
python scripts/iraq_iq_probe.py --local-prefix prefix.bin --out /tmp/iraq-analysis --analyze-hypothesis le
```

Cette option lance le moteur existant sur l'hypothèse demandée et écrit
`/tmp/iraq-analysis.le.analysis/report.json` et `spectrum.csv`. Le rapport
conserve le statut d'encodage non vérifié et précise la référence fréquentielle
en bande de base, sans centre RF certifié. Aucun boutisme n'est sélectionné
implicitement. Sans cette option, la commande reste une conversion candidate.
La CI demande explicitement `le` pour examiner le préfixe réel et publie le
rapport et le spectre, sans le fichier IQ ni les essais audio/binaires.
L'absence de candidat sur ces 4 ms ne permet pas d'exclure un protocole du
fichier complet.

Le [contrôle 40503411350](https://github.com/sebadiaz/IQScope/actions/runs/40503411350)
a exécuté cette analyse sur les 4 ms réelles : aucune bande n'est retenue par le
détecteur stationnaire, aucune trame ADS-B/AX.25 n'est validée et aucune répétition
CP cohérente n'est retenue. RTTY, CW et FSK sont non applicables sur cette fenêtre
avec leurs contraintes actuelles. Ce résultat n'identifie pas le protocole et
n'établit pas l'absence de signal dans l'enregistrement complet. L'artefact CI
`iraq-iq-observation` contient le rapport détaillé avec spectre et waterfall,
ainsi que le CSV spectral ; l'incertitude d'encodage y est conservée.

### Fenêtre étendue bornée

L'option `--seconds 1` demande jusqu'à une seconde sous l'hypothèse du débit
publié, soit 16 384 000 octets décompressés. Le transfert HTTP reste plafonné à
16 Mio ; la valeur par défaut reste 4 ms. Une requête hors de l'intervalle
[0,004 ; 1] seconde est refusée. Le mode local accepte au plus 16 384 000 octets.

Chaque boutisme reste indépendant : une interprétation contenant des valeurs
non finies est conservée en octets mais signalée comme rejetée par le lecteur,
sans bloquer la lecture de l'autre hypothèse. Aucun remplacement de NaN ni
nettoyage silencieux n'est effectué. La CI demande désormais une seconde pour
exercer le moteur au-delà de la fenêtre initiale ; le rapport donne toujours
la durée réellement analysée. L'absence de candidat reste une observation sur
ce seul extrait, sous hypothèse d'encodage.

Le [contrôle 40504449495](https://github.com/sebadiaz/IQScope/actions/runs/40504449495)
a obtenu 16 384 000 octets décompressés, soit 2 048 000 échantillons candidats,
pour 16 384 799 octets transférés au total. Les deux exports SigMF conservent
les octets et se relisent exactement. Le
[rapport une seconde](../corpus/iraq-iq-one-second-observation.json) conserve
le hash du préfixe et le résultat d'analyse explicite en petit-boutiste.

Aucune bande spectrale ni candidat cohérent RTTY/CW/2-FSK/4-FSK/CP n'est retenu,
et aucune trame ADS-B/AX.25 n'est validée. Ce résultat porte sur une seconde,
sans centre RF certifié et avec encodage non vérifié. Il ne constitue pas un
test négatif de LoRa : aucun décodeur LoRa n'est encore implémenté. Les noms de
fichiers ne sont pas utilisés comme identification automatique de protocole.

### Quatre captures distinctes

La sonde accepte `--recording ism915|uhf450|vhf144|vhf150`. Ces identifiants
sélectionnent des chemins exacts de l'index déjà inspecté, avec contrôle de la
taille déclarée du membre et refus des noms absents ou dupliqués. Ils désignent
les indications des noms de fichiers, sans certifier une fréquence RF ou un
protocole. Aucune URL ni chemin d'extraction arbitraire n'est accepté.

La CI exécute les quatre captures séparément avec une seconde candidate et un
budget d'au plus 16 Mio par job. Chaque artefact porte l'identifiant de la
capture et contient son rapport, son spectre et sa provenance. L'échec d'une
capture n'annule pas les trois autres contrôles. Les hypothèses restent
indépendantes et les données binaires ne sont pas publiées dans les artefacts.

Le premier passage multi-captures (40505601077) a réussi l'import et l'analyse
d'une seconde VHF 144 MHz nominale, sans candidat retenu. Les trois autres
rapports contenaient des erreurs réseau/ZIP ; leur fin de job ne validait pas
l'import. La sonde fait désormais échouer le job en présence d'une erreur et
conserve le rapport avec `if: always()`. Les requêtes Range demandent une
revalidation du cache ; chaque capture a une URL de requête distincte, tout en
restant dans la même archive publique. Les contrôles stricts de plages et les
limites de transfert sont maintenus.

Le [passage corrigé 40505971755](https://github.com/sebadiaz/IQScope/actions/runs/40505971755)
a importé et analysé une seconde de chacune des trois nouvelles captures.
Deux bandes spectrales sont retenues dans `uhf450`, sans contenu validé ; aucune
bande n'est retenue dans `vhf144` et `vhf150`. Les essais numériques ne produisent
aucun candidat cohérent ni trame validée sur ces fenêtres. Les deux bandes UHF
ne constituent pas une identification de modulation ou de protocole.

La capture `ism915` a de nouveau échoué à l'ouverture de l'index ZIP distant.
Son analyse antérieure d'une seconde reste documentée séparément ; ce nouveau
passage n'est pas présenté comme une validation des quatre imports. Le
[rapport multi-captures](../corpus/iraq-iq-multi-observation.json) conserve les
trois réussites et l'erreur. Le job correspondant est bien en échec, les trois
autres sont indépendants et leurs rapports/spectres sont disponibles.

### Détail des bandes UHF

Le [contrôle 40531925274](https://github.com/sebadiaz/IQScope/actions/runs/40531925274)
a cette fois terminé les quatre imports sans erreur. Le
[rapport UHF détaillé](../corpus/iraq-uhf-band-observation.json) rend visibles
les mesures et les limites par décodeur :

| Bande | Décalage en bande de base | Largeur estimée | Excès spectral sur le fond |
| --- | ---: | ---: | ---: |
| 1 | −721 342 Hz | 1 500 Hz | 25,93 dB |
| 2 | +212 253 Hz | 1 000 Hz | 9,91 dB |

Ces nombres dépendent de l'interprétation petit-boutiste non certifiée. Ce ne
sont ni des fréquences RF mesurées ni des puissances absolues calibrées. Les
variations d'enveloppe sont respectivement 0,143 et 0,388 ; elles ne suffisent
pas à identifier une modulation. Aucun essai audio AM/FM n'est retenu par les
critères actuels et les recherches CW/FSK ne produisent pas de candidat
cohérent. Ces bandes restent donc `unresolved`, sans contenu validé.

La couverture temporelle varie par décodeur : les recherches RTTY/CW/FSK portent
sur une seconde ici, mais le détecteur CP/OFDM atteint son budget de 262 144
échantillons, soit **128 ms** à ce débit. Ne pas présenter son résultat comme
une inspection complète de la seconde ni comme une exclusion de l'OFDM.
Le résumé de sonde publie désormais ces limites et les mesures des bandes en
plus des simples compteurs, sans modifier les seuils pour forcer un résultat.


### Couverture CP distribuée

Le détecteur CP répartit désormais son budget de 262 144 échantillons sur au
plus trois fenêtres sans chevauchement, incluant le début et la fin de la
source. Pour une seconde à 2,048 Méch/s, la somme examinée reste 128 ms, mais
elle est répartie dans la seconde ; les intervalles entre fenêtres restent
non inspectés. `analyzed_seconds` indique la somme effectivement examinée,
`source_span_seconds` la durée source, et `coverage_complete` reste faux si des
échantillons ne sont pas examinés. Chaque fenêtre conserve son indice source.
Les observations précédentes décrivent l'ancienne sélection limitée au début.

Un test de régression place un signal à préfixe cyclique dans la fin d'un
long enregistrement : il doit être détecté au-delà des 262 144 premiers
échantillons. Des tests vérifient aussi l'abstention sur bruit, les limites
budgétaires et l'absence de chevauchement. Les seuils et les limites de
reconnaissance restent identiques : cette preuve structurelle ne décode aucun
protocole ni contenu.
