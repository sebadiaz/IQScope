# Parcours automatique borné d'un fichier IQ

Dans le mode Fichier, cocher **Parcourir automatiquement le fichier IQ**.
Choisir la durée de chaque fenêtre et le budget : huit fenêtres par défaut,
32 au maximum. Les paramètres DSP restent choisis par les décodeurs ; le
point de départ et les formats sont ceux du lecteur IQ habituel.

Les fenêtres se recouvrent de 50 % par leurs indices source entiers. Elles
sont traitées successivement, avec huit millions d'échantillons au plus par
fenêtre. Le dernier départ peut être avancé pour lire une fin de fichier
inférieure à 1 024 échantillons sans créer une fenêtre trop courte.
Les fenêtres et leurs fichiers dérivés restent séparés.

```bash
iqscope scan enregistrement.wav --seconds 10 --max-windows 8 --out parcours
iqscope scan enregistrement.wav --start-seconds 35 --seconds 10 --out reprise
iqscope scan enregistrement.wav --start-sample 195310 --seconds 10 --out reprise-exacte
```

Choisir un dossier de sortie vide. Le CLI et l'API partagent le même moteur.
`--start-sample` reprend à l'indice entier du bilan ; ne pas le combiner avec
un `--start-seconds` non nul.
Une erreur de fenêtre produit un bilan partiel conservé ; le CLI retourne
alors un code d'échec. Les arrêts sur budget sont des résultats partiels prévus.

## Bilan et couverture

`scan-report.json` est actualisé atomiquement après chaque fenêtre terminée.
Il donne les plages source, rapports par fenêtre, limites de décodeurs,
observations CRC et `next_start_sample` pour reprendre avec le recouvrement
prévu. Les états finaux sont `source_end_reached`, `window_budget_exhausted`,
`cancelled` et `failed_window`.

La couverture est l'union des fenêtres terminées, depuis le départ demandé.
`whole_file_read` exige un départ à zéro et la lecture jusqu'à la fin ;
`from_requested_start_read_to_end` n'affirme rien sur le préfixe ignoré.
Ces champs décrivent les IQ parcourus. Ils ne garantissent ni la totalité
des émissions détectées, ni le traitement de chaque échantillon par tous
les décodeurs : leurs propres budgets sont conservés et signalés.

Les observations CRC ne sont pas des paquets uniques. Une même émission
peut apparaître dans plusieurs fenêtres recouvrantes ou voies de traitement.
Aucun état DSP, liaison AX.25 ou réassemblage applicatif n'est propagé.

## Interface et API

L'interface affiche l'avancement aux frontières de fenêtres, le bilan et les
boutons pour consulter chaque rapport. Les exports binaires, JSON et audio
de la fenêtre choisie restent accessibles. **Arrêter après la fenêtre en cours**
demande une annulation ; le calcul interne de cette fenêtre reste terminé
avant l'arrêt. Les fenêtres déjà terminées sont conservées.

`POST /api/analyses` accepte `scan: true` et `max_windows: 1..32`, avec les
paramètres IQ habituels. `GET /api/jobs/{id}` expose `progress`. L'annulation
utilise `POST /api/jobs/{id}/cancel`. Les artefacts sont servis sous
`scan/window-NNN/…`, avec contrôle du confinement au dossier du job.

**Reprendre le parcours** lance une nouvelle passe au `next_start_sample` du
bilan, avec le budget courant. Les bilans des passes restent distincts ;
télécharger celui que l'on souhaite garder avant de poursuivre. Le serveur
conserve les 32 derniers jobs comme auparavant. La limite d'import web reste
128 Mio et chaque passe réimporte le fichier. Le CLI accède directement aux
fichiers locaux plus grands.

## Validation

Les tests couvrent les plans d'indices, queues courtes, budget, reprise,
annulation avant/durant le parcours, erreur de fenêtre, changement de layout,
commande, API et chemins d'artefacts imbriqués. Le WAV IQ épinglé de 18,799 s
donne trois fenêtres `[0,10]`, `[5,15]`, `[10,18,799…]`, avec 3, 5 et 2
observations des cinq mêmes trames connues. Ce sont des régressions de
développement, pas un total indépendant des paquets émis.

Chromium vérifie un budget d'une fenêtre, le bilan partiel, une reprise à
l'indice 195 310 et les exports imbriqués de la fenêtre `[5,15]`. Les contrôles
FCS, champs ambigus et origines source restent ceux des analyses ordinaires.
