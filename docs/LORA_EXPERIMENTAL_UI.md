# LoRa expérimental dans l’interface

Pour analyser un fichier IQ, sélectionner la capture et ses métadonnées puis
cocher **LoRa expérimental** avant « Analyser automatiquement ». L’option est
désactivée par défaut. Elle n’apparaît pas pour les fichiers audio de récepteur.
Dans l’onglet SDR, une case distincte « LoRa expérimental pour les fenêtres
SDR » applique ce mode aux instantanés reçus. Elle est également désactivée
par défaut. Le choix est figé dans chaque tâche d’analyse.

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
standard. Pour un instantané SDR, `POST /api/live/analyze` accepte aussi
`{"experimental_lora": true}`. Sans corps ou avec `false`, il garde le mode
standard. Le rapport conserve `source_sample_start` et la note de continuité :
ce sont des fenêtres récentes indépendantes, pas un décodage continu sans
pertes. Le téléchargement des artefacts utilise les mêmes routes que les
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


## Vérification du mode SDR

Le test API injecte un paquet IQ à 256 kéch/s dans le tampon du récepteur et
vérifie les deux modes, les octets exportés et l’origine de l’instantané. Le
parcours Chromium utilise une application de test dont le tampon contient
ce signal simulé ; il passe par les vraies routes HTTP de l’application. Il
vérifie le choix de la case, la requête périodique, la bannière et le fichier
binaire `HELLO`. Cette source de test ne fait pas partie du paquet installé
et n’est pas activée par `iqscope serve`. Aucun essai matériel sur antenne
n’est établi par ces tests.


## Sessions et couverture du direct

Chaque démarrage de réception crée un `session_id`. Le spectre et le statut
le conservent. Le rapport d’un instantané expose `source_session_id`,
`source_sample_start` et `source_sample_end` (borne de fin exclue), avec
`source_sample_reference: received_samples_in_session`. Les données, le taux
et la fréquence demandée sont copiés ensemble sous le verrou du récepteur.
Un redémarrage ne peut donc pas réétiqueter un ancien instantané avec les
paramètres de la nouvelle session.

L’interface ne relance pas automatiquement le même mode sur une fenêtre
inchangée. Un changement volontaire du mode LoRa autorise la réanalyse de
la même fenêtre ; un appel API explicite reste également possible. Le
waterfall est réinitialisé lorsque la session du spectre change.

Après deux analyses réussies de la même session, l’interface affiche soit
leur recouvrement, soit le nombre d’échantillons reçus non analysés entre
leurs intervalles. Les durées utilisent le taux nominal demandé. Ces écarts
ne mesurent pas les pertes matérielles, invisibles dans rtl_tcp. La première
fenêtre d’une session ne permet pas de conclure sur les périodes précédentes.
Les rapports individuels conservent les intervalles. L’historique LoRa décrit
ci-dessous regroupe des observations par une heuristique ; il ne constitue
pas une archive continue.

Le test Chromium laisse la source simulée inchangée au-delà de la période
d’analyse pour vérifier l’absence de nouvelle tâche automatique, puis change
le mode LoRa et vérifie la réanalyse volontaire et l’indication de
recouvrement. Les tests API et récepteur contrôlent les bornes, la copie du
contexte et le renouvellement de session après redémarrage.


## Historique LoRa du direct

Le panneau SDR conserve au plus **128 événements estimés**, en mémoire,
pour la session courante. Les **12 plus récents** sont affichés. Chaque entrée
conserve les octets à CRC valide, le nombre d’observations et les modes qui
les ont obtenus. Un lien télécharge les octets du paquet ; le JSON permet
d’exporter les 128 entrées retenues. Aucune copie d’IQ brut n’est ajoutée.

Deux observations sont regroupées si elles ont les mêmes octets, paramètres
PHY et taux de codage, et si leurs débuts estimés sont à au plus un symbole
du premier début retenu. L’ancre temporelle ne dérive pas à chaque fusion.
Deux émissions identiques à des instants distincts restent donc séparées.
La position correspond au début estimé des symboles de données, dans le
compteur d’échantillons reçus de la session ; ce n’est pas une heure RF
matérielle ni le début exact du préambule.

Cette règle est une estimation d’événement, pas une identité d’émetteur. Des
émetteurs identiques qui se recouvrent peuvent rester indiscernables. Seules
les entrées encore conservées sont comparées ; la limite de rétention ne
garantit pas un décompte unique de toute la session. Le CRC n’authentifie pas
l’émetteur. Les paquets ADS-B/AX.25 continuent d’apparaître dans leurs résultats
d’analyse ; ce nouvel historique concerne LoRa uniquement.

`GET /api/live/frames` retourne la session, une révision, les événements, la
capacité et le nombre d’anciennes entrées écartées. Le statut SDR expose
`history_revision` pour éviter de recharger la liste sans changement. Les
trames du rapport d’analyse reçoivent un `live_event_id` ; le rapport inclut
un `live_history_summary`. Les octets restent disponibles dans l’historique
indépendamment de la rétention des tâches d’analyse. L’interface ne crée pas
de fichiers supplémentaires sur le serveur pour les téléchargements du
paquet retenu : elle restitue les octets conservés dans l’entrée.

Un nouveau démarrage SDR réinitialise l’historique. Un changement du mode
LoRa ne le réinitialise pas : le même événement peut porter les deux modes
et plusieurs observations. Une analyse ancienne qui se termine après un
redémarrage garde son rapport mais n’entre pas dans le nouvel historique.
L’arrêt de réception laisse l’historique consultable jusqu’au prochain
démarrage. Les entrées sont volatiles ; télécharger le JSON pour les garder.

Les tests vérifient le regroupement de fenêtres et modes, les répétitions à
des instants distincts, le rejet des CRC invalides et des positions hors
fenêtre, les sessions et la rétention. Chromium vérifie une seule entrée
pour les réanalyses standard/expérimentale et télécharge ses octets `HELLO`.
