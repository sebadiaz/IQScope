# Fenêtres de réception SDR

Le tampon `rtl_tcp` conserve les quatre dernières secondes reçues, avec une
limite de **8 000 000 échantillons complexes**. Le début du plus ancien bloc
est coupé précisément si nécessaire ; le tampon ne dépasse pas cette limite
en attendant le prochain bloc complet. Le comptage reste relatif à la session
de réception, sans horodatage matériel.

| Débit demandé | Échantillons conservés au maximum | Durée maximale |
| --- | ---: | ---: |
| 256 000 éch/s | 1 024 000 | 4 s |
| 1 024 000 éch/s | 4 096 000 | 4 s |
| 2 048 000 éch/s | 8 000 000 | 3,90625 s |
| 2 400 000 éch/s | 8 000 000 | 3,333333… s |

En production, les échantillons sont des complexes 64 bits : au plus 64 Mo
de données utiles sont retenues dans la file. Les objets Python, le bloc ancien
partiellement utilisé, la copie instantanée et les tableaux DSP ajoutent leur
propre mémoire ; cette valeur ne borne pas toute la mémoire du processus.

## Traçabilité et interface

`GET /api/live/status` expose `buffered_seconds`, `window_sample_limit` et
`window_seconds_limit`, cohérents avec les autres métadonnées sous verrou.
L'interface affiche durée reçue et maximum au débit courant, même si le tampon
n'est pas encore plein. Les rapports d'analyse conservent les indices source
et `source_window_limits: {samples, seconds}` capturés avec les IQ. Une reprise
du récepteur vide le tampon et crée une nouvelle session comme auparavant.

## Validation

La référence de développement est synthétique : une trame AX.25 UI de
230 octets d'information, cadencée à 1 194,8 bauds, modulée en AFSK puis en FM
à 256 kéch/s avec bruit ajouté. Le contrat `rtl_tcp` est simulé en mémoire : en-tête, IQ quantifiés
sur huit bits, lectures fragmentées et assemblage des blocs. Aucun socket,
matériel SDR ou enregistrement indépendant n'est utilisé pour ce cas.

Une pause précède la trame pour forcer l'éviction des anciens échantillons.
La fenêtre de quatre secondes récupère le contenu exact avec FCS valide,
après découverte spectrale automatique. Sa seule dernière seconde ne fournit
aucune trame valide. Le temps de début est vérifié par rapport à la source.
Les tests couvrent également les quatre débits, les coupes au milieu d'un bloc,
les indices source et la limite de huit millions d'échantillons.

Chromium reçoit cette même fenêtre injectée par un serveur réservé aux tests.
Il vérifie l'analyse automatique, les durées affichées, le contenu, les indices
source et le téléchargement KISS. La route d'injection n'existe pas dans
l'application de production. Les autres références IQ/audio restent en CI.

## Limites

Les analyses restent des instantanés indépendants déclenchés périodiquement.
Le tampon plus long augmente le coût de traitement ; aucune cadence temps réel
n'est garantie. Une trame coupée à une frontière, la perte entre deux fenêtres,
les pertes matérielles, les paramètres RF sans lecture de retour et les limites
propres à chaque décodeur restent possibles. Aucun état DSP n'est poursuivi
entre fenêtres. Ce changement ne fournit ni capture continue ni balayage RF.
