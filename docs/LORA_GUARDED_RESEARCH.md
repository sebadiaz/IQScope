# Prototype expérimental avec contrôles appliqués

Résultats locaux : **4/4 références connues**, **24/24 contrôles synthétiques
positifs**, **0 contenu accepté sur 64 cas synthétiques négatifs**. Les
**234 tests passent**. Ce mode est disponible dans l’UI par une option désactivée par défaut : le score du mode standard
par défaut est toujours 3/4 et le résultat historique du premier passage
est conservé. Ces captures ont déjà servi au développement.

## Critères et ordre des décisions

Le prototype conserve la synchronisation physique existante lorsqu’elle
réussit. Sinon, il filtre chaque hypothèse par les scores d’alphabet global
et local mutualisé avant de vérifier l’unicité du sync word. Il ne choisit
pas un mot à partir du CRC. Les hypothèses faibles ne doivent pas rendre
ambigu un mot mieux étayé.

Une limite de données confirmée par le quart de chirp garde sa priorité.
À défaut, une seule limite est inférée depuis le sync word et le quart reste
explicitement non confirmé. La lecture est centrée sur la fréquence mesurée
sur six chirps de préambule moyennés : le déchirpage retire cette fréquence
avant la FFT des symboles. Ce recentrage évite de confondre un bin relatif
entier avec une fréquence de référence fractionnaire.

Le helper d’effacement/parité conserve cinq hypothèses maximum par bloc et
ses marges spectrales. Le mode impose aussi un score spectral moyen d’au
moins 8 pour les huit symboles d’en-tête et chaque bloc de données. Tout bloc
ambigu ou trop faible est rejeté avant l’appel au décodage final/CRC. Les
critères sont expérimentaux, pas des probabilités d’erreur calibrées.

## Audit IQ de bout en bout

Le [rapport synthétique](../corpus/lora-iq-policy-audit.json) conserve les 104
entrées, graines et résultats :

| Famille | Cas | Contenus acceptés |
| --- | ---: | ---: |
| Bruit blanc | 8 | 0 |
| Bruit coloré IQ | 8 | 0 |
| Forme large bande périodique | 8 | 0 |
| Préambule seul | 8 | 0 |
| Symboles CSS aléatoires | 8 | 0 |
| Mauvaise somme d’en-tête | 8 | 0 |
| Mauvais CRC, parité cohérente | 8 | 0 |
| Charge utile tronquée | 8 | 0 |
| Paquet valide fort | 8 | 8 exacts |
| Paquet valide bruité | 8 | 8 exacts |
| Paquet valide avec sync word `00` | 8 | 8 exacts |
| Paire descendante supprimée | 8 | 0 |
| Quart supprimé, données conservées | 8 | 8 exacts, quart non confirmé |

Les deux dernières familles sont des ablations physiques, pas des faux
messages : des données codées subsistent dans ces signaux. Le mot `00`
n’est pas interdit pour masquer les contre-exemples d’un score seul.
L’audit commence aux échantillons et inclut acquisition, synchronisation,
en-tête, inférence de symbole et CRC. Il reste limité à SF7/BW125/CR4/5 et
à ces canaux synthétiques ; zéro résultat accepté sur 64 cas n’établit pas
un taux universel de fausses alarmes radio.

Le [suivi des quatre membres IQ](../corpus/loraiq-guarded-batch-observation.json)
compare après décodage chaque contenu à l’intervalle annoté sélectionné.
Il conserve séparément le score de production 3/4 et le résultat expérimental
4/4. Les autres émissions ne sont pas validées par ce sous-ensemble
 d’annotations. Le rapport de suivi complet antérieur conserve les
comparaisons supplémentaires disponibles dans le CSV entier.

## Reproduction

```sh
python scripts/loraiq_forensic_probe.py --guarded \
  --input corpus-cache/loraiq-extension/0/source.sigmf-meta \
  --out corpus-cache/loraiq-forensic/guarded-observation.json
python scripts/loraiq_guarded_batch.py
python scripts/lora_iq_policy_audit.py
```

Le benchmark des autres sessions doit d’abord avoir récupéré les quatre
membres. La CI publie ces rapports à part. Les politiques sont isolées par appel ; les trames brutes de la voie de recherche sont retirées
du résultat de recherche : seules les observations du mode choisi comptent.
Une validation sur davantage de signaux radio inédits reste nécessaire avant
une intégration par défaut.


Voir [l’option UI et API](LORA_EXPERIMENTAL_UI.md) pour l’analyse des fichiers IQ.
