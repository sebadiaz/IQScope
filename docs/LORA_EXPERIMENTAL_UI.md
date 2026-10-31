# LoRa expérimental dans l’interface

Pour analyser un fichier IQ, sélectionner la capture et ses métadonnées puis
cocher **LoRa expérimental** avant « Analyser automatiquement ». L’option est
désactivée par défaut. Elle n’apparaît pas pour les fichiers audio de récepteur.
Le mode temps réel conserve le décodeur standard.

Les résultats affichent « LoRa expérimental activé ». Les contenus sont
exportés en `.bin` uniquement après un en-tête valide et un CRC de données
valide. Les corrections de symboles et les quarts de chirp non confirmés sont
signalés. Le JSON conserve `analysis_options.experimental_lora`,
`mode: experimental_guarded`, les drapeaux des trames et les mesures.
Les matrices spectrales internes ne sont pas conservées dans le rapport UI.

L’option utilise les critères composites et l’inférence par parité/score
spectral de la [voie expérimentale](LORA_GUARDED_RESEARCH.md). Les choix de
phase, limite et correction ne sont pas sélectionnés à partir du CRC. Les
voies physiques existantes gardent leur priorité ; les données CR4/6 à CR4/8
conservent le décodeur et la FEC existants.

## API et ligne de commande

Ajouter `"experimental_lora": true` à une requête `/api/analyses` pour une
capture IQ. La valeur par défaut est `false`. Une combinaison avec
`input_kind: audio` est rejetée, sans lancer une analyse silencieusement
standard. Le téléchargement des artefacts utilise les mêmes routes que les
autres analyses.

```sh
iqscope analyze capture.sigmf-meta --experimental-lora --out results
```

Les politiques sont transmises aux fonctions par appel, sans remplacement
global. Le décodeur standard et le mode expérimental peuvent donc s’exécuter
sans modifier leurs fonctions respectives. Le script de recherche réutilise
les mêmes modules installables. Les tests couvrent l’API, l’export exact, la
FEC CR4/8 et des analyses concurrentes ; le parcours Chromium couvre la case,
la bannière, le JSON et le fichier binaire.

## Validation et limites

Le [rapport d’intégration](../corpus/loraiq-ui-experimental-observation.json)
retrouve les quatre références déjà étudiées par le pipeline principal et
vérifie tous les fichiers binaires exportés octet par octet. Les entrées,
leur empreinte et les comparaisons aux annotations sont conservées. Cela
reste une évaluation sur données exposées, pas une mesure de sensibilité sur
une population radio. Les validations synthétiques de la politique ne
suffisent pas à garantir un taux de fausses alarmes général.

La fréquence RF des captures LoRaIQ n’est pas promue comme vérifiée dans ce
rapport de validation. Le mode standard conserve son score 3/4 sur les
quatre autres sessions ; l’option expérimentale les récupère 4/4 localement.
La disponibilité de cette option ne change pas le statut expérimental de ses
critères. Les tests du navigateur et les benchmarks sont rejoués en CI.
