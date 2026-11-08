# Synchronisation fine et égalisation aveugle 16-QAM

Cette étude de laboratoire compare des traitements des IQ bruts à la voie circulaire donnant 602 erreurs sur les 17 904 bits de vérification de `16qam f.csv`. Elle ne modifie pas le décodeur générique ni ses seuils. Le fichier faible reste un candidat refusé tant qu'aucune modification du décodeur n'est validée séparément.

## Ce qui est indépendant

La boucle de Gardner reprend seulement le débit grossier et la porteuse de l'acquisition existante. Elle n'utilise ni la phase temporelle ni le débit affiné par minimisation de l'EVM. Le signal est interpolé à au moins huit points par symbole, puis filtré par un RRC de roll-off 0,2 et de longueur dix symboles. Un interpolateur FIR à 128 phases et seize coefficients alimente le détecteur `Re((précédent − courant) × conj(milieu))`. Une boucle PI, amortissement 1/√2, suit la phase et la fréquence ; la correction de fréquence est bornée à ±0,5 %. Il s'agit d'une **synchronisation fine indépendante**, pas d'une acquisition entièrement indépendante du débit et de la porteuse.

Les vecteurs de l'égaliseur comportent 21 points espacés de T/2, prélevés avant le RRC. Un filtre antirepliement Kaiser de coupure 0,9 fois le débit symbole précède l'interpolation Lanczos de rayon huit. Deux grilles sont comparées : celle du récepteur existant et celle suivie par Gardner. Pour cette dernière, les demi-symboles se trouvent au milieu des centres temporels successifs, avec compensation en unités physiques.

## Apprentissage sans symboles cibles

CMA ou MCMA sert à l'acquisition, puis RDE utilise les trois rayons de la constellation. Pour une 16-QAM carrée d'énergie moyenne unitaire, les constantes sont 1,32 pour CMA, 0,82 par axe pour MCMA, et les rayons au carré 0,2 / 1 / 1,8 pour RDE. Les seuils RDE 0,6 / 1,4 partitionnent les **rayons au carré**. Chaque mise à jour est divisée par l'énergie du vecteur d'entrée ; l'erreur est bornée en amplitude à deux.

Chaque étage effectue quatre passes sur l'intérieur non étiqueté de la fenêtre. Cette étude est donc un traitement hors ligne de toute la fenêtre, pas encore un égaliseur causal temps réel. Elle n'utilise ni PRBS ni décisions du récepteur comme symboles cibles. L'orientation initiale provient du moment d'ordre quatre. Le retard entier (±3 symboles), le quart de tour et la conjugaison sont résolus uniquement en comparant le préfixe non étiqueté au préfixe du récepteur existant. Ce lien au récepteur initial est explicite ; ce n'est pas une identification du codage binaire.

Les bandes de boucle 0,01 / 0,03 et les pas d'acquisition 0,02 / 0,08 sont fixés après essais synthétiques indépendants et avant lecture des nouveaux BER matériels. RDE utilise un pas quatre fois plus petit. Les trois voies principales prédéfinies sont Gardner 0,01 seul, MCMA 0,02 sur la grille initiale et leur combinaison. Les autres configurations servent de contrôles de sensibilité ; leur minimum après lecture des résultats ne constitue pas une sélection validée.

## Vérification

Le préfixe de 512 symboles acquiert une seule correspondance binaire et une seule phase PRBS à partir de la voie initiale. Ces éléments sont figés pour toutes les variantes. Les 17 904 bits de la suite servent uniquement à compter les erreurs, avec la même empreinte de référence. Les premiers et derniers quarante symboles conservent leurs LLR initiaux : 17 744 bits de vérification traversent effectivement le traitement expérimental. Le gain et le bruit du démappeur circulaire sont estimés sur l'intérieur non étiqueté, sans symboles attendus.

Les tests indépendants vérifient le suivi de ±500 ppm sur des signaux RRC générés dans le domaine fréquentiel, la suppression d'une interférence entre symboles par les quatre variantes aveugles, l'indépendance de l'alignement vis-à-vis de la suite, les budgets et la conservation des entrées. Les données matérielles proviennent de l'archive à empreinte vérifiée décrite dans [QAM16.md](QAM16.md).

## Sources des équations

- [GNU Radio, détecteur temporel Gardner](https://github.com/gnuradio/gnuradio/blob/main/gr-digital/lib/timing_error_detector.cc), fonction `ted_gardner::compute_error_cf` : signe et forme complexe du détecteur.
- [QAMpy, fonctions d'erreur à la version 918723a](https://github.com/ChalmersPhotonicsLab/QAMpy/blob/918723ad0f1ccfa413614410da54eb7592976400/qampy/core/equalisation/pythran_equalisation.py) : formes CMA, MCMA et RDE, notamment la partition des rayons au carré.
- [Revue des autres sources et limites de transfert](QAM_LITERATURE_REVIEW.md).

L'implémentation NumPy/SciPy applique ces équations ; elle ne reprend pas une chaîne GNU Radio ou QAMpy avec ses paramètres supposés universels. Aucun des essais ne suppose le filtre d'émission connu.

## Résultats matériels

Le [banc CI du commit 77548d8](https://github.com/sebadiaz/IQScope/actions/runs/42503960338) a exécuté les quinze voies sur les six captures. Les [mesures conservées](../corpus/qam-blind-sync-observation.json) comprennent aussi tous les contrôles de sensibilité.

| Voie prédéfinie | Erreurs sur `f` / 17 904 bits | Erreurs corrigées / introduites par rapport à la référence | Cinq captures fortes |
| --- | ---: | ---: | --- |
| Référence circulaire existante | 602 | — | zéro erreur |
| Gardner, bande 0,01 | 655 | 70 / 123 | zéro erreur |
| MCMA 0,02 → RDE, grille initiale | 1 346 | 194 / 938 | zéro erreur |
| Gardner 0,01 + MCMA 0,02 → RDE | 1 269 | 193 / 860 | zéro erreur |

Aucune des quatorze nouvelles variantes n'améliore la référence faible : elles donnent de 655 à 5 390 erreurs. Sur la grille initiale, CMA donne 1 617 / 1 986 erreurs et MCMA 1 346 / 1 727 pour les pas 0,02 / 0,08. Gardner 0,03 seul donne 882 erreurs ; les variantes utilisant cette boucle rapide introduisent aussi 4 à 45 erreurs sur les captures fortes. Le zéro erreur des trois voies principales ne doit donc pas être étendu à toute la grille.

Tous les alignements sur `f` retiennent un retard entier nul et aucune conjugaison. Les variantes MCMA nécessitent un quart de tour, résolu sur le préfixe avant comptage. Gardner 0,01 retrouve en fin de fenêtre environ 49,99717 Mbaud à partir d'une amorce de 49,99994 Mbaud. Il ne découvre pas une autre modulation ou un autre segment ; l'empreinte des bits attendus reste `b3b1c4c30aaed626eed153081907322f6325e409596c2834285c6bb5984710ac`.

La variance complexe du modèle circulaire de sortie passe de 0,05722 à 0,05986 pour Gardner, 0,08605 pour MCMA et 0,08574 pour leur combinaison. Ces ajustements non étiquetés accompagnent la dégradation mesurée ; ils ne séparent pas à eux seuls bruit physique, interférence résiduelle et défaut d'apprentissage. Le passage de 0,01 à 0,03 montre aussi qu'une boucle plus rapide n'est pas automatiquement meilleure.

## Contrôle supplémentaire : aucun canal à corriger

Après les mesures RF, un diagnostic indépendant emploie un canal identité : impulsions 16-QAM uniformes à deux points par symbole, points intermédiaires nuls, puis bruit blanc gaussien circulaire. Il ne reproduit pas la mise en forme RF ; il vérifie si l'adaptation MCMA 0,02 → RDE peut dégrader une entrée déjà correctement échantillonnée. Aucun paramètre n'est choisi à partir de ses résultats. L'orientation est résolue sur le seul préfixe non étiqueté initial, puis les décisions sont vérifiées sur 17 792 bits synthétiques, hors préfixe et bord final.

| Variance complexe du bruit | Graine | Erreurs initiales | Erreurs après MCMA → RDE |
| --- | ---: | ---: | ---: |
| 0,0008 | 811 / 922 / 1033 | 0 / 0 / 0 | 0 / 0 / 0 |
| 0,057 | 811 | 501 | 620 |
| 0,057 | 922 | 569 | 721 |
| 0,057 | 1033 | 576 | 697 |

La dégradation est donc reproductible pour ces réglages même sans interférence entre symboles ni protocole inconnu. Ce contrôle ne démontre pas que le mécanisme précis est identique dans la capture réelle. Il justifie de vérifier l'objectif et l'adaptation en présence de bruit avant d'ajouter des coefficients ou de réutiliser les paramètres de démonstrations à fort SNR. Le contrôle se lance séparément par `from scripts.qam_blind_sync_study import synthetic_noise_control` et figure aussi dans le JSON du banc CI.

La conclusion porte sur ces configurations et cette courte capture. Elle ne prouve ni une limite d'information des IQ bruts, ni l'échec de toute égalisation aveugle. Il reste notamment à distinguer biais de l'objectif aveugle à faible SNR, initialisation du filtre et budget de convergence. Un prochain modèle de reconstruction de la forme d'onde devra estimer son bruit sur les observations, conserver les contrôles synthétiques et les échecs d'initialisation, et être comparé sans sélectionner ses paramètres sur le BER de `f`. Aucun de ces résultats ne justifie d'activer ces voies dans le décodeur générique.
