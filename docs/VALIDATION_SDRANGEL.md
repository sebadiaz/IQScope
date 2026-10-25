# Première validation sur les captures SDRangel

Date : 25 octobre 2026. Version IQScope : 0.3.0.

Source : [fichiers IQ SDRangel](https://www.sdrangel.org/iq-files/).
Exécution vérifiée : [GitHub Actions 40216155276](https://github.com/sebadiaz/IQScope/actions/runs/40216155276), commit `45b9d08d67f361f114c4fa904b556c120620e011`.

## Résultats observés

| Capture | Format lu | Taux | Intervalle fourni à l'analyse | Résultat |
|---|---|---|---|---|
| ADS-B | WAV IQ, PCM 16 bits | 2,4 Méch/s | 4 194 250 échantillons, soit environ 1,748 s | 4 paquets DF17/18 récupérés avec CRC-24 valide |
| RTTY | WAV IQ, PCM 16 bits | 2 kéch/s | 10 s | Import, spectre et analyse réussis ; aucun décodeur RTTY intégré |
| Radar GRAVES | SDRangel `.sdriq`, 24 bits dans conteneurs 32 bits | 6 kéch/s | 10 s | Import avec contrôle d'en-tête, spectre et analyse réussis ; pas d'interprétation radar |

Pour ADS-B, le budget de 2 000 candidats est atteint. Les quatre paquets sont un résultat partiel : ils ne représentent pas le nombre total d'émissions de la capture et ne permettent pas de mesurer un taux de récupération. Un CRC valide ne démontre pas l'authenticité d'un émetteur.

Les tests Python passent sur 3.10, 3.12 et 3.13. Le parcours Chromium passe : démo, import SigMF, résultats, accès audio, capacités et mise en page mobile. Les captures d'écran sont disponibles dans l'artefact `browser-checks` de l'exécution. Aucun SDR physique n'a été testé.

## Correction apportée grâce à la capture réelle

Le premier récepteur ADS-B fonctionnait sur les références synthétiques mais ne récupérait aucun paquet de l'extrait réel. Il comparait les impulsions après rééchantillonnage des IQ sur une grille de 2 Méch/s.

La correction calcule l'énergie de l'enveloppe, la rééchantillonne sur une grille temporelle de 8 Méch/s et intègre les demi-symboles PPM. Les tests couvrent désormais plusieurs phases d'acquisition fractionnaires. Le CRC reste vérifié sans correction de bits destinée à forcer une concordance.

Cette amélioration établit un premier succès sur cette capture, pas une robustesse générale aux collisions, au faible SNR ou à toutes les erreurs d'horloge.

## Provenance et reproductibilité

Le script télécharge un préfixe borné du premier membre IQ du ZIP et ferme la connexion une fois le budget atteint. Pour ADS-B, environ 8,13 Mo compressés ont suffi à obtenir 16 Mio de WAV, évitant le téléchargement complet de l'archive annoncée de 460 Mo.

Le fichier WAV partiel n'est pas présenté comme un WAV complet. Une lecture explicitement réservée au pipeline d'extraits produit une paire SigMF complète, réimportable normalement. Les imports utilisateurs ordinaires continuent de refuser les WAV tronqués.

Les empreintes des extraits vérifiés sont enregistrées dans [le manifeste](../corpus/sdrangel.json). Pour le budget par défaut de 16 Mio, un changement de contenu entraîne une erreur nécessitant une révision du manifeste. Ces empreintes ne vérifient pas l'intégralité du ZIP ni les données situées après l'extrait.

Commandes depuis le dépôt installé :

```bash
python scripts/sdrangel_corpus.py --name adsb --name rtty --name radar
```

Les résultats sont écrits sous `corpus-cache/`, avec URL, nom du membre d'archive, hash de l'extrait et rapport. Les artefacts CI contiennent uniquement les rapports et la provenance, pas les enregistrements IQ. Les droits de redistribution des captures ne sont pas établis.

## Étapes suivantes

- Réduire les candidats redondants et mieux répartir le budget ADS-B sur la durée.
- Constituer une vérité terrain indépendante pour mesurer rappel, erreurs et paquets manqués.
- Ajouter les captures AM et FM à la validation des essais audio.
- Intégrer AX.25, AIS, RTTY et les autres décodeurs, chacun avec ses propres preuves.
- Étendre les tests navigateur aux imports WAV/SDRangel et à une source rtl_tcp simulée de bout en bout.
