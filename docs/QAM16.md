# Première récupération automatique de 16-QAM

IQScope essaie maintenant une chaîne **16-QAM carrée monoporteuse** dans les analyses IQ par fichier et les instantanés SDR. Les paramètres sont estimés à partir des échantillons : aucun débit symbole, décalage de porteuse ou filtre n’est fourni au décodeur. Les résultats sont des symboles et bits candidats, sans protocole ni CRC identifiés.

## Méthode

Une raie cyclique de l’énergie de l’enveloppe fournit un débit symbole candidat. Une raie de la puissance quatrième fournit le décalage de fréquence, avec raffinement dans un intervalle de deux cases FFT. Lorsque l’entrée contient entre quatre et huit échantillons par symbole, une interpolation polyphasée par deux précède les filtres et la synchronisation. Elle ne crée pas d’information supplémentaire. Trois filtres RRC sont essayés (roll-off 0,2 / 0,35 / 0,5, longueur dix symboles), après une décimation éventuelle. Une recherche initiale sur 24 phases puis un ajustement borné du débit et de la phase d’échantillonnage minimisent l’erreur vectorielle des symboles.

Le gain RMS commun conserve les amplitudes relatives : les symboles ne sont pas normalisés individuellement. La rotation est estimée par le moment d’ordre quatre d’une constellation QAM carrée. Les décisions utilisent les quatre niveaux de chaque axe, proportionnels à −3, −1, +1 et +3. L’acceptation exige une EVM RMS d’au plus 12 %, au plus 14 % dans chaque moitié, et au moins 1,5 % d’occupation pour chacun des seize états. Ces seuils sont structurels, pas une probabilité de classification.

Un candidat direct est recherché avant les canaux du détecteur spectral commun. En l’absence de candidat direct, jusqu’à quatre bandes de largeur au plus 48 kHz sont mélangées vers zéro et décimées avec filtrage antirepliement. Les offsets, débits de canal et intervalles source examinés sont enregistrés. Ce détecteur stationnaire peut fusionner ou manquer des émissions.

## Budgets et limites

- Entrée directe entre 1 kéch/s et 250 Méch/s, avec au moins quatre échantillons source par symbole. Jusqu’à 96 kéch/s, recherche d’horloge de 30 à min(9600, débit d’échantillonnage/4) bauds.
- Au-delà de 96 kéch/s, changement d’unité de temps vers une fréquence de calcul de 32 000, sans supprimer d’échantillons : recherche entre `Fs × 30/32000` et `Fs/4` bauds. Les débits, offsets et temps exportés sont reconvertis en unités physiques. Par exemple, à 200 Méch/s la plage cherchée est 187,5 kbaud à 50 Mbaud. Ce mode ne recherche donc pas les canaux étroits d’une telle source.
- Au moins 280 symboles dans la durée examinée et 256 symboles de sortie. La limite de trois secondes empêche donc certains bas débits d’aboutir.
- Trois premières secondes et 288 000 échantillons source au plus par essai direct ; l’interpolation peut porter le tampon à 576 000 échantillons. À 200 Méch/s, le budget source limite la fenêtre à 1,44 ms. Recherche spectrale jusqu’à 2,4 Méch/s, limitée également à 2 400 000 échantillons d’entrée et quatre canaux.
- 24 phases initiales et au plus 160 évaluations par filtre, ajustées sur au plus 2048 centres répartis dans la fenêtre.
- Au plus 40 000 bits (10 000 symboles) et 512 points de constellation par candidat. Les limites de durée et de sortie sont signalées.

La puissance quatrième laisse une ambiguïté de fréquence modulo le débit d’échantillonnage/4 ; la plage directe non ambiguë est donc ±débit/8. La rotation par quart de tour, la conjugaison I/Q, la correspondance des bits et l’alignement des octets restent inconnus. Le débit peut également présenter des alias si la raie d’horloge sélectionnée est une harmonique.

Cette voie ne traite pas les autres tailles de QAM, le QAM croisé, l’OFDM/QAM de standards cellulaires ou Wi-Fi, les canaux à trajets multiples nécessitant un égaliseur, les sauts de fréquence ou les dérives suivies par une boucle persistante. Les impulsions rectangulaires ne sont pas revendiquées. Des salves faibles ou incomplètes, une faible ouverture de filtre ou des états peu présents peuvent provoquer une abstention.

## Convention de sortie et interface

Les rangs I et Q croissent de −3 à +3. Le label est `4*rang_I + rang_Q` (0 à 15), rangé en binaire naturel sur quatre bits. C’est une convention explicite, sans affirmation de correspondance Gray ni de correspondance avec les bits émis par un protocole réel. Les décisions restent compatibles avec plusieurs rotations/conjugaisons.

L’interface montre constellation, EVM, débit estimé, correction de porteuse, filtre essayé et premiers bits candidats. Le compteur des trames CRC n’augmente pas. Les liens proposent :

- texte des bits ;
- binaire empaqueté MSB-first, dernier octet complété par des zéros si nécessaire ;
- labels de symboles dans un tableau JSON ;
- rapport `qam16-candidates.json`, avec paramètres, ambiguïtés et points de constellation.

Les échantillons source ne sont pas modifiés par le décodeur. Les essais SDR restent indépendants entre fenêtres : aucune continuité d’horloge ou de phase n’est revendiquée.

Le champ `processing` conserve la fréquence d’échantillonnage source en Hz, le nombre d’échantillons lus, la fréquence dans la coordonnée de calcul, son facteur de conversion vers les Hz physiques et le facteur d’interpolation. L’ambiguïté de porteuse se réfère toujours à la fréquence source, avant interpolation.

## Validation actuelle

Les références **synthétiques** vérifient les symboles émis. Le générateur de test applique un filtrage RRC dans le domaine fréquentiel, indépendant des coefficients temporels employés par le récepteur. Les comparaisons tiennent compte des huit rotations/conjugaisons possibles, plusieurs débits et graines, erreurs d’horloge constantes, fréquences positives/négatives et gains différents. Les tests à quatre échantillons par symbole et à 200 Méch/s contrôlent les labels récupérés, les unités physiques, les durées et les budgets ; ils ne représentent pas une mesure RF.

Un mélange de deux canaux 16-QAM et d’une porteuse parasite vérifie la séparation automatique. Les cas BPSK, QPSK, 8-PSK, 64-QAM, FSK, porteuse, silence et bruit testés ne doivent pas produire de candidat. Les exports doivent restituer exactement les bits et labels décidés. Chromium importe une référence synthétique par les vrais chemins de l’application, affiche la constellation et télécharge le rapport.

Une référence matérielle indépendante complète ces essais ci-dessous, avec constellation et comparaison à un motif PRBS15 connu. Ces contrôles ne prouvent pas une couverture générale des signaux radio ni des protocoles utilisant la QAM. Des corpus plus larges, des tests de faux positifs supplémentaires, l’égalisation, la poursuite de phase et des déframeurs de protocoles restent nécessaires.

## Référence matérielle indépendante à 28 GHz

Le dépôt [28_and_75GHz_Capture_Files, version figée](https://github.com/billjgavin/28_and_75GHz_Capture_Files/tree/3f9ea40d9b187d0819b14cb254dc04905d398889) décrit des acquisitions RF de laboratoire par liaison conduite, sans rayonnement. Son README annonce de la 16-QAM à 50 Mbaud, échantillonnée à 200 Méch/s, avec PRBS15 et fenêtres de 100 µs. L’[inspection CI](https://github.com/sebadiaz/IQScope/actions/runs/42289341612) confirme six CSV étiquetés 16-QAM, des en-têtes N9030B à 28 GHz, une durée de 100 µs et un pas de 5 ns.

`python scripts/qam_lab_reference.py` télécharge seulement l’archive 28 GHz de 8 425 587 octets, vérifie sa taille, son empreinte Git et sa SHA-256 `4959f58182b54a8ba25893106be939f34716d0c3832afa4d88d1658e54844240`. Il inventorie ses membres sans extraire ni exécuter leur contenu, lit le README embarqué et essaie le décodeur QAM sur les CSV. Le parseur reconstruit les valeurs I puis Q alternées du résultat 0 ; le pas, le nombre de points du résultat 1 et la durée de capture doivent concorder. Les autres colonnes ne sont pas traitées comme des échantillons I/Q. Le workflow séparé `QAM laboratory reference` produit le rapport d’inspection et les résultats structurels, sans publier les échantillons ni les bits décidés : la licence de redistribution des données n’est pas établie.

Le format I/Q et les scalaires sont documentés dans le [manuel Keysight IQ Analyzer](https://www.keysight.com/so/en/assets/9018-04709/user-manuals/9018-04709.pdf), section « IQ Waveform Measurement / Remote Command Results ». Le pas de 5 ns, les 20 001 points complexes et la durée de 100 µs concordent : la durée couvre l’intervalle du premier au dernier point.

L’[essai CI sur les 32 CSV](https://github.com/sebadiaz/IQScope/actions/runs/42289680499) accepte cinq des six captures étiquetées 16-QAM, sans fournir de débit ni de filtre au décodeur :

| Fichier | Niveau TX déclaré | Symboles candidats | Débit estimé | EVM RMS du récepteur |
| --- | ---: | ---: | ---: | ---: |
| 16qam a | −10 dBm | 4 988 | ≈50 Mbaud | 1,52 % |
| 16qam b | −15 dBm | 4 988 | ≈50 Mbaud | 1,89 % |
| 16qam c | −20 dBm | 4 988 | ≈50 Mbaud | 2,93 % |
| 16qam d | −25 dBm | 4 988 | ≈50 Mbaud | 4,60 % |
| 16qam e | −30 dBm | 4 988 | ≈50 Mbaud | 7,95 % |
| 16qam f | −40 dBm | aucun candidat accepté | — | — |

Les 26 CSV BPSK, QPSK, 8-PSK, porteuse et bruit du même corpus ne produisent aucun candidat QAM. Ce résultat n’est pas une estimation générale du taux de faux positifs. Les niveaux TX proviennent du README embarqué ; ce ne sont pas des SNR. L’EVM est celle calculée après les estimations et décisions d’IQScope, sans séquence de symboles de référence.

Le workflow contrôle ces issues, les ordres de grandeur du débit physique et le nombre de symboles. Ces attentes proviennent du premier décodage de développement : il ne s’agit pas d’une évaluation sur un corpus réservé. Le parseur CSV reste dans le script de référence ; ce format constructeur n’est pas encore importable directement dans l’interface.

## Comparaison des bits au PRBS15 annoncé

Le [contrôle PRBS15 sur les captures](https://github.com/sebadiaz/IQScope/actions/runs/42364274111) retrouve **zéro erreur sur 17 904 bits de vérification par capture**, pour chacun des fichiers `16qam a` à `16qam e`. Chaque capture contient 19 952 bits décidés ; les 2 048 premiers servent exclusivement à l’acquisition de la correspondance points/bits et de la phase du PRBS. Les 17 904 suivants servent exclusivement au décompte d’erreurs. La capture `f` reste refusée avant cette mesure.

La première recherche, limitée aux codes naturels/Gray par axe, permutations et inversions des bits, laissait environ 12,5 % de désaccord. Une table bijective apprise entre les seize labels et les seize mots de quatre bits élimine ce désaccord. Cette observation caractérise la correspondance de ce corpus ; aucun standard constructeur précis n’est déduit de la table.

`scripts/qam_prbs15.py` construit une période de 32 767 bits selon la convention explicite `b[n] = b[n-14] XOR b[n-15]`, initialisée par quinze uns. Les deux sens de parcours et toutes les phases sont examinés. Pour chaque phase, des corrélations circulaires calculées par FFT déterminent les quatre bits majoritaires associés à chaque label dans le préfixe. Les tables bijectives sont retenues ; aucune optimisation d’affectation n’est tentée lorsque la table majoritaire n’est pas bijective. La phase et la table sont choisies uniquement sur le préfixe. Elles restent fixes sur la suite ; aucun bit n’est corrigé par le PRBS.

L’essai exige au moins 1 024 symboles, huit occurrences de chaque label dans le préfixe et utilise au plus 10 000 symboles. Le statut de cohérence exige une table bijective et au plus 10 % de désaccord dans chacune des deux portions ; la régression de ce corpus exige **zéro erreur** et au moins 17 000 bits de vérification. Le rapport fournit la table complète, la phase, le sens, les nombres de bits/erreurs, le BER de la suite et les SHA-256 des bits décidés et prédits, empaquetés MSB-first avec bourrage final par zéros. Il conserve le contrôle structurel de constellation séparément.

Les tests utilisent un générateur LFSR SciPy indépendant, des tables non linéaires, des inversions de sens et des erreurs injectées. Remplacer uniquement la suite par du hasard doit laisser la table et la phase acquises inchangées et faire échouer la vérification. La CI mélange aussi les symboles de chaque capture réelle pour contrôler le rejet d’un ordre sans PRBS.

Cette mesure exploite l’annonce explicite du PRBS15 par la source. La séquence mathématique est indépendante des décisions ; sa phase et la table sont inférées sur le préfixe, sans graine ni octets de référence fournis par l’auteur. La suite disjointe vérifie la prédiction, sans constituer un corpus indépendant réservé. Aucun protocole ni CRC n’est identifié. Dans l’application, les exports génériques QAM conservent leur convention naturelle et leur statut de bits candidats : la comparaison PRBS reste un outil de mesure du corpus de laboratoire.

## Diagnostic de la sixième capture refusée

Le [diagnostic CI](https://github.com/sebadiaz/IQScope/actions/runs/42408173967) établit le refus de `16qam f.csv` (niveau TX déclaré −40 dBm). L’horloge est retrouvée à ≈49,999935 Mbaud et la correction de porteuse à ≈267,74 Hz. Les seize états sont suffisamment occupés : au moins 5,65 % chacun, au-dessus du minimum de 1,5 %. Les trois essais fixes échouent aux deux critères d’EVM :

| RRC | EVM RMS globale | Erreurs PRBS dans la suite | Bits de vérification | BER observé |
| --- | ---: | ---: | ---: | ---: |
| 0,20 | 22,18 % | 610 | 17 904 | 3,407 % |
| 0,35 | 22,30 % | 644 | 17 904 | 3,597 % |
| 0,50 | 22,52 % | 711 | 17 904 | 3,971 % |

La limite globale est 12 % ; la limite dans chaque moitié est 14 %. Pour le premier filtre, les moitiés sont à 22,34 % et 22,02 %. L’acquisition de l’horloge et de la porteuse aboutit, mais les décisions contiennent des erreurs mesurables. Le diagnostic établit le critère de refus et le désaccord binaire ; l’origine physique de la dégradation reste à caractériser.

Les trois résultats PRBS sont rapportés séparément, sans sélectionner un filtre avec les erreurs de la suite. Chaque table et phase PN est apprise sur les seuls 2 048 bits du préfixe, puis figée. La cohérence avec un motif connu malgré plusieurs pour cent d’erreurs ne transforme pas cette sortie en candidat générique accepté. Le nombre de captures acceptées reste cinq sur six.

Le rapport générique fournit désormais un `rejection_reason`, les estimations d’acquisition disponibles et au plus trois résumés `filter_trials` : EVM globale/par moitié, occupation minimale et motifs de refus. La recherche multicanal range l’essai direct sous `direct_trial` et conserve les diagnostics de chaque canal dans `channels_examined`, pour distinguer un refus direct d’un canal accepté.

Le paramètre Python optionnel `trial_observer` reçoit des copies des diagnostics et des labels bornés par le budget de sortie. Ses retours ne participent pas aux ajustements ni aux critères d’acceptation. Le script de laboratoire l’utilise pour examiner cette capture refusée ; les labels rejetés ne sont pas ajoutés aux candidats de l’application. Les tests vérifient l’isolation des copies et le refus d’une référence QAM bruitée. La CI conserve également le refus de `f`, ses deux motifs EVM, une EVM entre 20 et 25 %, un BER PRBS entre 2 et 6 % pour chaque filtre, et le rejet des contrôles à symboles mélangés.

## Étude de corrections apprises sur le préfixe

Le [banc comparatif](https://github.com/sebadiaz/IQScope/actions/runs/42412233040) reconstruit exactement les décisions du premier essai RRC 0,20 à partir des paramètres physiques exportés. Il vérifie cette égalité avant de comparer quatre voies sur chacune des six captures : référence, soustraction de la moyenne I/Q, correction affine par mélange gaussien à seize états, et égaliseur complexe causal à trois coefficients appris sur les décisions du préfixe. Les corrections utilisent les 512 premiers symboles, sans bits PRBS. La synchronisation aveugle initiale utilise sa fenêtre habituelle ; les tables et phases PRBS sont ensuite acquises sur le préfixe pour mesurer les erreurs sur les mêmes 17 904 bits de suite.

Résultats pour `16qam f.csv` :

| Voie | EVM sur la suite | Erreurs PRBS sur la suite | BER |
| --- | ---: | ---: | ---: |
| Référence | 22,11 % | 610 | 3,407 % |
| Moyenne I/Q soustraite | 22,29 % | 694 | 3,876 % |
| Correction affine EM | 22,96 % | 645 | 3,603 % |
| Égaliseur à trois coefficients | 21,94 % | 640 | 3,575 % |

L’égaliseur réduit légèrement l’EVM calculée sur ses propres décisions tout en augmentant les erreurs de bits. L’EVM seule ne suffit donc pas à justifier son activation. Les cinq autres captures restent à zéro erreur PRBS dans les quatre voies. Toutes les voies sont rapportées, sans choisir une correction avec les erreurs de la suite. Cette étude est exploratoire sur le corpus de développement, pas une validation sur des captures réservées. Le chemin générique conserve le traitement de référence et ses seuils ; les correcteurs restent dans le script d’étude.

La puissance moyenne brute de `f` vaut environ `2,5454e-6` dans les unités du fichier. Les deux captures de bruit valent `5,2362e-7` et `5,0896e-7`, soit environ 20 % de cette puissance. Sous l’hypothèse d’une calibration identique et d’un bruit représentatif, le rapport `(puissance_f − puissance_bruit) / puissance_bruit` correspond à environ 5,87–6,02 dB. Ces enregistrements séparés donnent un indice compatible avec une limitation par le bruit ; ils ne constituent pas une mesure simultanée étalonnée du SNR.

`scripts/qam_receiver_study.py` conserve les paramètres appris et les mesures dans `receiver-study.json`. Les essais sont bornés à quatre voies, 512 symboles d’apprentissage, 32 itérations EM et un égaliseur de longueur trois. Les tests vérifient la reconstruction en unités physiques, la récupération d’un canal affine synthétique connu, l’absence de modification des échantillons et l’indépendance des paramètres vis-à-vis de la suite.
