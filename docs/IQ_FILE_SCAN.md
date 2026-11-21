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

## Catalogue chronologique des trames

Chaque passe produit aussi `scan-events.json`, repris intégralement dans
`event_catalogue` du bilan. Il indexe les voies CRC déjà implémentées :
ADS-B DF17/18, AIS GMSK, groupes RDS sur FM, AX.25 UI sur FSK/BPSK, AFSK1200/AX.25 et FM/AFSK1200/AX.25,
ainsi que les charges utiles du profil LoRa PHY partiel. Le CRC/FCS est
recalculé depuis les octets avant l'indexation. Les messages POCSAG, données
de capteurs externes, sorties FEC sans CRC et candidats audio/symboles restent
dans les rapports de fenêtre, avec leur validation propre.

Les événements sont triés par indice estimé dans le fichier. Les mêmes
octets peuvent être regroupés s'ils proviennent du même décodeur et frontend,
avec les mêmes paramètres PHY et une position/canal proches. La comparaison
reste ancrée à la première observation, sans dérive cumulative. Tolérances :

| Voie | Position source | Canal |
| --- | --- | --- |
| FM/AFSK1200 AX.25 | Deux symboles nominaux à 1200 bauds | 500 Hz |
| AIS GMSK | Deux symboles nominaux à 9600 bauds | 1 kHz |
| RDS sur FM | Deux bits nominaux à 1187,5 bits/s | 5 kHz |
| AX.25 FSK/BPSK générique | Un échantillon source | Même décalage |
| ADS-B | Une microseconde, au moins un échantillon | Réception directe |
| LoRa PHY | Un symbole au SF/BW retenu | Réception centrée |

Une répétition plus éloignée reste distincte. Ce regroupement est heuristique,
sans garantie de compter les paquets physiques uniques ; des émetteurs
simultanés indiscernables peuvent être regroupés. Les temps suivent la
convention de chaque décodeur : préambule ADS-B, premier symbole de données
AX.25 ou début des symboles de données LoRa, pas un horodatage RF calibré.

Le catalogue conserve au plus 128 événements, 32 références par événement
et examine au plus 512 observations par fenêtre. Les observations hors budget
et références omises sont comptées ; les rapports originaux restent présents.
L'arrêt ou une erreur ultérieure conserve le catalogue des fenêtres terminées.
Chaque point de contrôle réécrit atomiquement le bilan et le catalogue dans
des fichiers distincts ; il ne s'agit pas d'une transaction entre les deux.
Le catalogue inclus dans le bilan correspond à ce point de contrôle.

Chaque événement donne les indices fenêtre/essai/trame de ses observations,
leurs temps et canaux, les avertissements d'interprétation de l'entrée, et
un binaire sous `events/`. Les binaires AX.25 et ADS-B comprennent le FCS/CRC ;
les binaires LoRa contiennent la charge utile PHY sans CRC, dont la valeur
reçue est conservée séparément. Aucun paquet n'est modifié par l'indexation.
Les observations LoRa gardent les indications de correction FEC, de mode
expérimental et de quart de chirp non confirmé ; ces deux dernières sont
également signalées dans l'interface.
Les champs AX.25 sont reparsés : les hypothèses de mode I restent non choisies.
Il n'y a ni réassemblage, ni calibration APRS, ni association CPR entre fenêtres.

L'interface filtre le catalogue par famille et permet de télécharger les
octets ou de consulter une observation dans sa fenêtre d'origine. Une reprise
crée un catalogue séparé, comme les autres résultats de cette nouvelle passe.

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
Le catalogue regroupe ces dix observations en cinq événements estimés, chacun
avec ses deux références et les octets exacts. Les tests couvrent aussi les
répétitions séparées, canaux distincts, CRC erronés, limites et conservation
des avertissements d'entrée. ADS-B et LoRa sont exercés sur IQ synthétiques.

Chromium vérifie un budget d'une fenêtre, le bilan partiel, une reprise à
l'indice 195 310 et les exports imbriqués de la fenêtre `[5,15]`. Les contrôles
FCS, champs ambigus et origines source restent ceux des analyses ordinaires.
Chromium vérifie également les filtres ADS-B/LoRa/AX.25, les binaires et le
retour à la seconde observation d'un événement de l'enregistrement réel.
