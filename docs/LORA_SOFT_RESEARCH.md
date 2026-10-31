# Recherche hors seuils sur le paquet faible

Le paquet SF7/BW125/CR4/5 annoté à −8,8366 dB est récupérable dans une analyse
expérimentale du membre `25_01_17-14_39/rrh2/1` : en-tête valide, contenu
`0000000`, CRC reçu et calculé `0xE654`. La comparaison aux annotations,
effectuée ensuite, confirme les octets dans un intervalle temporel unique.

**Le score automatique reste 3/4.** Le script de recherche contourne les
contrôles de confiance du sync word et des symboles ; le quart de chirp n’est
pas confirmé. Cette expérience n’est pas activée dans le détecteur, l’UI ou
les exports du produit. Le [rapport](../corpus/loraiq-forensic-observation.json)
conserve ces limites, les spectres dérivés, le résultat dur et l’inférence.

## Ce qui bloque la lecture dure

À une limite unique choisie depuis le sync word candidat, sans consulter
l’en-tête ni le CRC, la lecture des huit premiers symboles donne un en-tête
cohérent. Les décisions dures suivantes échouent sur la parité. Dans le bloc
commençant au symbole 13 (indices à partir de zéro), le cinquième symbole a
pour maximum spectral le bin relatif 108, presque à égalité avec 126. Choisir
uniquement ce maximum introduit une erreur dans plusieurs mots déinterlacés.

## Hypothèses d’effacement et score spectral

Le code CR4/5 utilisé ici impose une parité paire par mot de cinq bits. Il
ne corrige pas arbitrairement les erreurs en décision dure. Si l’on suppose
qu’une seule des cinq colonnes de symboles d’un bloc est erronée, les quatre
autres déterminent exactement les bits manquants par parité. Il existe donc
au plus cinq hypothèses, une par colonne effacée.

Pour chacune, le script reconstruit les bits Gray déinterlacés, inverse le
Gray mapping et obtient un symbole de remplacement. Il classe les hypothèses
par perte de puissance spectrale, normalisée par une estimation du fond de
bruit : `score[symbole dur] - score[symbole reconstruit]`. Il exige une marge
au moins 8 entre les deux meilleures hypothèses et un score de remplacement
au moins 8. Ce sont des seuils heuristiques, sans probabilité d’erreur garantie.
La métrique est un substitut de vraisemblance ; elle ne modélise pas exactement
le bruit coloré ou toutes les incertitudes de synchronisation.

Sur cette observation, l’hypothèse de la cinquième colonne retient 126 avec
une perte faible et une marge suffisante. Tous les choix de blocs sont faits
**avant** l’appel final au décodage et au CRC. Aucun classement, choix de
colonne, temps, phase ou octet ne dépend du résultat du CRC. Un bloc ambigu
n’est pas corrigé. Le script ne modifie pas les huit symboles de l’en-tête et
ne recherche pas plusieurs erreurs simultanées par bloc.

La séquence ainsi retenue donne `0000000` et son CRC. Une deuxième émission,
`0000001` vers 1,044203 s, passe déjà la parité et le CRC sans correction de
symbole. Les deux correspondances aux annotations sont faites après analyse ;
aucun octet attendu, temps annoté, SF, largeur ou CFO annoté n’est fourni au
script de détection.

## Reproduction et limites

Depuis la racine du dépôt, après installation des dépendances et récupération
du membre par le benchmark des autres sessions :

```sh
python scripts/loraiq_forensic_probe.py \
  --input corpus-cache/loraiq-extension/0/source.sigmf-meta
```

Le script utilise un patch local temporaire, restauré même en cas d’exception,
pour examiner une paire jointe, les positions autorisées du sync word et les
symboles sans leurs seuils de confiance de production. Il refuse un sync word
ambigu et n’examine qu’une limite de données par hypothèse unique. Il ne
modifie aucun fichier du décodeur. L’entrée est limitée à 32 Mio d’IQ et 64 Kio
de métadonnées, avec vérification du SHA512 SigMF. Le rapport expose les SHA256
des sources ; le centre RF n’est pas considéré comme vérifié.

Le helper `scripts/lora_soft_probe.py` ne reçoit que les symboles, les spectres
relatifs normalisés et le SF. Il est limité à SF7–10, CR4/5 avec en-tête valide,
64 symboles et cinq hypothèses d’effacement par bloc. Le test dérivé du signal
réel conserve attribution et empreinte de source. Les autres tests contrôlent
les cinq colonnes, les ambiguïtés, un CRC faux, l’indépendance du choix spectral
par rapport au CRC, les dimensions et valeurs invalides, et la restauration
du détecteur après une exception.

Les 225 tests passent localement. La CI dédiée reproduit l’expérience dans une
étape explicitement marquée « Research-only », avec un rapport séparé du score
automatique. Avant toute intégration, il reste à valider la synchronisation
à faible SNR et le taux de faux positifs sur d’autres signaux. Une seule
récupération développée sur ces données ne constitue pas cette validation.

Source : Joachim Tapparel et Andreas Burg, EPFL,
[LoRaIQ](https://zenodo.org/records/20341802), DOI 10.5281/zenodo.20341802,
licence CC BY 4.0. Les spectres du rapport et du test sont dérivés de cette source.


## Audit des critères de synchronisation

Un [audit séparé](LORA_SYNC_AUDIT.md) compare les scores d’alphabet sous bruit
blanc et coloré, avec deux graines et trois modèles de fond spectral. Il met
en évidence des passages indésirables et un compromis entre sensibilité et
rejet. Ces mesures ne rendent pas la voie expérimentale active en production.
