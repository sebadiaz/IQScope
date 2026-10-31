# Audit des scores du sync word faible

La recherche retrouve les positions candidates du sync word `96`, mais un
score concentré dans l’alphabet autorisé ne suffit pas à valider la
synchronisation. **Aucun nouveau critère n’est activé en production.** Le
score automatique des autres sessions reste 3/4 ; les deux récupérations
expérimentales restent des résultats de recherche hors seuils.

## Comparaison de trois modèles

Le score examine les 16 positions autorisées de chaque nibble, à ±1 bin.
Les deux lettres retenues doivent aussi correspondre aux maxima spectraux
observés. Les puissances sont normalisées par une estimation du fond ; les
scores des lettres sont transformés par une exponentielle puis normalisés.
Le produit des deux masses relatives doit atteindre 0,99, avec pic/fond au
moins 8 dans chacun des trois chirps et somme des trois rapports au moins 32.
Cette masse est un score sous un modèle simplifié, **pas une probabilité
calibrée que le mot soit correct**. Aucun octet attendu ni CRC n’intervient.

Trois estimations du fond sont comparées, sans modifier ces seuils :

- Globale : médiane hors ±2 bins du maximum, divisée par `ln(2)`.
- Locale : médiane des six voisins aux distances 2, 3 et 4 du maximum,
  divisée par `ln(2)`.
- Locale mutualisée : mêmes positions voisines, réunies sur les trois spectres.
  Cette variante suppose le bruit stationnaire sur les trois chirps.

Les variantes locales sont des contrôles supplémentaires après le contrôle
global, pas un blanchiment exact du bruit.

## Audit conditionnel sur spectres simulés

Chaque tirage comporte trois spectres de 128 bins. Les puissances de bruit
blanc suivent une loi exponentielle. La famille colorée multiplie le même
tirage par `1/(1+a²-2a*cos(2*pi*k/N))`, avec `a=0,9`. Deux graines sont
conservées ; chacune utilise 4096 tirages par famille. Les maxima, la référence
et les lettres sont recalculés à chaque tirage.

| Graine | Famille | Contrôle global | Global + local | Global + local mutualisé |
| --- | --- | ---: | ---: | ---: |
| 20261031 | Blanc | 0 | 0 | 0 |
| 20261031 | Coloré | 1298 | 23 | 34 |
| 20261101 | Blanc | 0 | 0 | 0 |
| 20261101 | Coloré | 1362 | 17 | 42 |

Les nombres sont des **passages de ces contrôles**, pas des trames fausses
acceptées par IQScope. L’acquisition IQ, la paire opposée, le quart de chirp,
l’en-tête et le CRC ne sont pas simulés dans cet audit. Ces résultats ne
donnent donc pas un taux de fausses alarmes du produit. Le second tirage
vérifie la stabilité sur le même modèle ; ce n’est pas une validation radio
indépendante ou un nouveau dataset.

Une autre limite est explicite : trois tonalités déchirpées persistantes
peuvent passer tous les modèles en donnant `00`. Cela peut représenter une
continuation de préambule ; le seul score du sync word ne prouve pas la
frontière d’un paquet. À l’inverse, deux lettres légales à égalité sont
rejetées. Les [rapports](../corpus/loraiq-sync-score-audit.json) et le
[second tirage](../corpus/loraiq-sync-score-audit-second-seed.json) conservent
ces contre-exemples au lieu de les exclure de l’évaluation.

## Effet sur les deux émissions réelles

Le [rapport IQ de suivi](../corpus/loraiq-sync-score-observation.json) mesure
les trois critères sans les utiliser pour choisir ou rejeter les données.
Le détecteur de production reste inchangé et le script de recherche conserve
ses contournements de seuils, explicitement indiqués.

| Émission expérimentale | Global | Local | Local mutualisé |
| --- | --- | --- | --- |
| `0000000`, données vers 0,034467 s | Passe | Passe | Passe |
| `0000001`, données vers 1,044203 s | Passe | Rejette | Passe |

Pour la cible faible, les masses de score valent respectivement environ
0,99361, 0,9999998 et 0,99636. La variante locale rejette la deuxième émission
pourtant conforme au CRC et aux annotations : un de ses rapports pic/fond
vaut 7,86 et sa masse environ 0,98690. Les seuils n’ont pas été retouchés pour
la faire passer. La variante mutualisée conserve les deux émissions, mais
laisse davantage de spectres colorés passer dans ces simulations.

Les comparaisons aux annotations sont effectuées après décodage. Les octets
réels restent ceux du rapport expérimental précédent. La conclusion est un
compromis mesuré entre rejets et passages indésirables, pas une validation
suffisante pour activer la voie dans le produit.

## Reproduction

```sh
python scripts/lora_sync_gate.py
python scripts/lora_sync_gate.py --seed 20261101 \
  --out corpus-cache/loraiq-forensic/sync-audit-second-seed.json
```

Le script `loraiq_forensic_probe.py` ajoute les mesures aux observations IQ.
La CI dédiée publie les rapports de simulation séparément du benchmark
automatique. Les tests contrôlent l’alphabet dans les deux polarités,
l’ambiguïté, les pics hors alphabet, l’invariance au gain, le bruit, les
entrées invalides et le contre-exemple de continuation du préambule.

Les spectres IQ proviennent de LoRaIQ, Joachim Tapparel et Andreas Burg,
EPFL, DOI 10.5281/zenodo.20341802, licence CC BY 4.0. Les familles simulées
ne prétendent pas représenter tous les bruits radio.
