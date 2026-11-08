# Première récupération automatique de 16-QAM

IQScope essaie maintenant une chaîne **16-QAM carrée monoporteuse** dans les analyses IQ par fichier et les instantanés SDR. Les paramètres sont estimés à partir des échantillons : aucun débit symbole, décalage de porteuse ou filtre n’est fourni au décodeur. Les résultats sont des symboles et bits candidats, sans protocole ni CRC identifiés.

## Méthode

Une raie cyclique de l’énergie de l’enveloppe fournit un débit symbole candidat. Une raie de la puissance quatrième fournit le décalage de fréquence, avec raffinement dans un intervalle de deux cases FFT. Lorsque l’entrée contient entre quatre et huit échantillons par symbole, une interpolation polyphasée par deux précède les filtres et la synchronisation. Elle ne crée pas d’information supplémentaire. Trois filtres RRC sont essayés (roll-off 0,2 / 0,35 / 0,5, longueur dix symboles), après une décimation éventuelle. Une recherche initiale sur 24 phases puis un ajustement borné du débit et de la phase d’échantillonnage minimisent l’erreur vectorielle des symboles.

Le gain RMS commun conserve les amplitudes relatives : les symboles ne sont pas normalisés individuellement. La rotation est estimée par le moment d’ordre quatre d’une constellation QAM carrée. Les décisions utilisent les quatre niveaux de chaque axe, proportionnels à −3, −1, +1 et +3. L’acceptation exige une EVM RMS d’au plus 12 %, au plus 14 % dans chaque moitié, et au moins 1,5 % d’occupation pour chacun des seize états. Ces seuils sont structurels, pas une probabilité de classification.

Un candidat direct est recherché avant les canaux du détecteur spectral commun. En l’absence de candidat direct, jusqu’à quatre bandes de largeur au plus 48 kHz sont mélangées vers zéro et décimées avec filtrage antirepliement. Les offsets, débits de canal et intervalles source examinés sont enregistrés. Ce détecteur stationnaire peut fusionner ou manquer des émissions.

## Budgets et limites

- Entrée directe entre 1 kéch/s et 250 Méch/s, nominalement quatre échantillons source par symbole avec environ 1 % de marge d’horloge. Jusqu’à 96 kéch/s, la recherche peut atteindre min(9600, débit d’échantillonnage/3,96) bauds ; son plancher reste 30 bauds. La sélection entre plage nominale et étendue est décrite ci-dessous.
- Au-delà de 96 kéch/s, changement d’unité de temps vers une fréquence de calcul de 32 000, sans supprimer d’échantillons : recherche entre `Fs × 30/32000` et `Fs/3,96` bauds. Les débits, offsets et temps exportés sont reconvertis en unités physiques. À 200 Méch/s, le plafond nominal de 50 Mbaud peut ainsi être dépassé pour une erreur d’horloge positive, jusqu’à ≈50,505 Mbaud. Ce mode ne recherche donc pas les canaux étroits d’une telle source.
- Au moins 280 symboles dans la durée examinée et 256 symboles de sortie. La limite de trois secondes empêche donc certains bas débits d’aboutir.
- Trois premières secondes et 288 000 échantillons source au plus par essai direct ; l’interpolation par au plus trois peut porter le tampon à 864 000 échantillons. À 200 Méch/s, le budget source limite la fenêtre à 1,44 ms. Recherche spectrale jusqu’à 2,4 Méch/s, limitée également à 2 400 000 échantillons d’entrée et quatre canaux.
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

`scripts/qam_receiver_study.py` conserve les paramètres appris et les mesures dans `receiver-study.json`. Cette première étude utilise quatre voies, 512 symboles d’apprentissage, 32 itérations EM et un égaliseur de longueur trois. Les tests vérifient la reconstruction en unités physiques, la récupération d’un canal affine synthétique connu, l’absence de modification des échantillons et l’indépendance des paramètres de ces trois corrections vis-à-vis de la suite.

## Décisions par bit et sorties de fiabilité

La recherche a été étendue à treize voies de traitement : modèles circulaire et affine aveugles ajustés sur les points de toute la fenêtre, phase seule, gain par moments M2/M4, interpolation Lanczos de rayon huit et filtres RRC de longueur dix ou vingt symboles, avec plusieurs ouvertures. Tous les résultats restent rapportés dans le banc. Les meilleures corrections du signal donnent 608 ou 609 erreurs au lieu de 610 sur `f`, un gain trop faible pour justifier leur activation dans le chemin générique. L’interpolation plus précise améliore certaines EVM, mais donne 620 à 666 erreurs sur cette capture. Aucun bit PRBS de la suite n’intervient dans ces ajustements.

Une autre amélioration concerne la décision binaire : choisir le symbole le plus probable minimise les erreurs de symbole, tandis que chaque bit peut bénéficier d’une somme des probabilités des huit points qui portent sa valeur. `iqscope_qam_soft` estime un gain complexe et une variance de bruit circulaire par EM borné à 32 itérations, sans bits de référence. Il calcule ensuite les quatre rapports `LLR = log P(bit=0|échantillon) / P(bit=1|échantillon)` par sommes exponentielles stabilisées, avec des symboles équiprobables.

L’[essai matériel](https://github.com/sebadiaz/IQScope/actions/runs/42414169734) utilise la même table de correspondance et la même phase PN, acquises sur les 2 048 premiers bits de la référence. La décision par bit donne **602 erreurs sur 17 904 bits**, contre **610** pour les décisions de symbole : huit erreurs de moins, soit un gain observé modeste d’environ 1,31 % du nombre d’erreurs (BER de 3,407 % à 3,362 %). Les cinq captures plus fortes restent à zéro erreur. Ce résultat concerne le corpus de développement et sa table apprise sur le préfixe ; il ne prouve pas un gain général sur d’autres captures ni une identification automatique du codage binaire d’un protocole inconnu.

Dans l’application, chaque candidat QAM accepté propose désormais un export **fiabilité des bits** : au plus 40 000 LLR, rangés MSB-first par symbole, bornés entre −80 et +80, avec le gain, la variance estimée et les décisions obtenues par le signe. Une valeur positive favorise zéro ; une valeur négative favorise un. La convention générique reste le binaire naturel `4*rang_I+rang_Q`, avec les ambiguïtés de rotation/conjugaison déjà annoncées. Les exports de bits et de labels existants conservent leurs décisions initiales. Les LLR sont des vraisemblances sous le modèle estimé, pas une validation CRC ni une probabilité universellement calibrée. Ils peuvent alimenter une future correction d’erreurs quand le protocole et sa correspondance binaire seront connus.

La capture `f` conserve son refus générique et ses seuils d’EVM. La comparaison de laboratoire utilise son codage acquis sur le préfixe ; les exports génériques n’appliquent pas ce codage spécifique. Les tests vérifient le signe, l’ordre et la saturation des LLR, une baisse des erreurs sur une référence AWGN synthétique à codage non Gray, ainsi que le téléchargement du JSON par Chromium. Remplacer la suite par du hasard doit produire une mesure d’échec, sans empêcher la comparaison par un choix fondé sur cette suite.

Références techniques consultées : [récepteur de constellation GNU Radio](https://wiki.gnuradio.org/index.php/Constellation_Receiver), [interpolation fractionnaire GNU Radio](https://wiki.gnuradio.org/index.php/Fractional_Interpolator), [conception RRC et troncature](https://www.mathworks.com/help/signal/ref/rcosdesign.html), et [démodulation QAM avec LLR exacts](https://www.mathworks.com/help/comm/ref/qamdemod.html). L’implémentation utilise NumPy/SciPy et ses formules explicites, sans dépendance MATLAB ni GNU Radio.

## Correction de la borne d’horloge à quatre échantillons par symbole

Une erreur a été reproduite indépendamment du corpus matériel : le plafond strict `Fs/4` empêchait de rechercher le vrai débit lorsque l’émetteur était légèrement plus rapide que l’horloge nominale de l’ADC. Une erreur positive de 500 ppm pouvait conduire à une hypothèse d’horloge erronée et au refus d’une référence synthétique valide. À +175 ppm, le débit restait artificiellement bloqué à 50 Mbaud au lieu de 50,00875 Mbaud.

La recherche autorise maintenant une marge autour des quatre échantillons nominaux, jusqu’à `Fs/3,96`. L’interpolation choisit un facteur entier suffisant pour conserver au moins huit échantillons internes par symbole, avec un maximum de trois. L’élargissement est activé lorsque l’estimation dépasse la borne nominale de plus de 0,01 case FFT. Cette marge de stabilité évite des changements de branche pour de très petites fluctuations autour de la limite. Sinon, la recherche et la borne d’ajustement nominales sont conservées. Les seuils d’EVM, d’occupation et de durée ne changent pas.

Sur des références générées dans le domaine fréquentiel, à débit ADC de 200 Méch/s et débit symbole nominal de 50 Mbaud :

| Erreur d’horloge | Avant | Après |
| --- | --- | --- |
| −500 ppm | symboles récupérés, EVM ≈3,92 % | même récupération |
| +175 ppm | estimation bloquée à 50 Mbaud, EVM ≈9,65 % | estimation ≈50,008779 Mbaud, EVM ≈3,68 % |
| +500 ppm | référence refusée | estimation ≈50,025031 Mbaud, EVM ≈3,67 %, symboles récupérés conformes à la séquence émise |

Le [contrôle matériel après stabilisation](https://github.com/sebadiaz/IQScope/actions/runs/42417439750) conserve zéro erreur sur les cinq captures fortes et, sur `f`, 610 erreurs binaires après décision de symbole contre 602 après décision probabiliste par bit, sur les mêmes 17 904 bits de suite. Les empreintes des références PRBS prédites sont identiques à celles d’avant correction : le résultat ne provient pas d’un déplacement du segment évalué. La capture faible conserve son refus ; ce correctif améliore la couverture des erreurs d’horloge, sans revendiquer une réduction supplémentaire de ses erreurs.

## Recherche de phase variable et de bruit I/Q corrélé

`python scripts/qam_phase_study.py` complète le banc, après téléchargement et vérification de l’archive par `scripts/qam_lab_reference.py`. Il reconstruit les symboles du premier filtre RRC et vérifie leur identité avec les décisions du récepteur. Les cinq voies partagent ensuite exactement la table de bits et la phase PRBS acquises sur le préfixe de référence ; aucune voie ne réapprend cette calibration après correction. Les mêmes 17 904 bits de suite servent à la mesure.

Le suivi aveugle de phase essaie 61 rotations entre −0,3 et +0,3 radian autour de la phase constante estimée. Il minimise la distance aux seize points dans trois fenêtres fixes de 31, 127 et 511 symboles. Le coût de chaque symbole est exclu de sa propre fenêtre de décision. Les rotations conservent l’amplitude des échantillons ; aucun point n’est remplacé par un symbole idéal. Ce traitement utilise les voisins passés et futurs : il reste expérimental et hors ligne. Les trois résultats sont publiés sans sélectionner une fenêtre avec les erreurs de vérification.

Une autre voie ajuste par EM un gain complexe constant et une covariance réelle I/Q complète à deux dimensions, avec une constellation uniforme et 32 itérations. La covariance remplace la distance circulaire par une distance de Mahalanobis dans les probabilités de bits. Le gain reste borné entre 0,5 et 2 et le conditionnement de la covariance doit rester inférieur à 10. L’ajustement utilise uniquement les échantillons non étiquetés, sans valeurs de bits attendues.

Un diagnostic séparé utilise les symboles PRBS attendus pour mesurer les résidus de la suite : covariance I/Q, corrélations des retards de un à huit symboles, dispersion des phases par blocs de 128 symboles et approximation descriptive pour un bruit blanc circulaire. Ces valeurs de référence ne servent à aucun correcteur ni ajustement de vraisemblance. Elles peuvent caractériser un défaut, sans prouver qu’une méthode de réception est optimale.

Les tests synthétiques vérifient la récupération d’une dérive de phase sinusoïdale indépendante, la conservation des amplitudes, l’estimation d’une covariance connue et l’amélioration sur des symboles aléatoires distincts de ceux ayant servi à cet ajustement. Ils vérifient aussi l’équivalence avec les probabilités circulaires existantes lorsque la covariance est isotrope, ainsi que l’indépendance de la calibration PRBS vis-à-vis de la suite. Le chemin générique et ses seuils restent inchangés ; la CI conserve uniquement les mesures JSON dans `phase-study.json`.

Les [mesures sur les six captures](https://github.com/sebadiaz/IQScope/actions/runs/42419347686), conservées dans `corpus/qam-phase-observation.json`, donnent sur `f` :

| Voie | Erreurs sur 17 904 bits | Erreurs anciennes corrigées | Erreurs nouvelles introduites |
| --- | ---: | ---: | ---: |
| Probabilités circulaires actuelles | 602 | — | — |
| Bruit I/Q elliptique | 611 | 9 | 18 |
| Phase variable, fenêtre 31 | 750 | 82 | 230 |
| Phase variable, fenêtre 127 | 641 | 35 | 74 |
| Phase variable, fenêtre 511 | 621 | 12 | 31 |

Les cinq captures fortes restent à zéro erreur dans toutes ces voies. L’empreinte des bits attendus de `f` reste `b3b1c4c30aaed626eed153081907322f6325e409596c2834285c6bb5984710ac`. Aucune correction supplémentaire n’est activée à partir de ces résultats.

Sur la suite de `f`, le résidu par rapport à la référence a une puissance de 0,05754 et une covariance de conditionnement 1,024 : les dispersions I/Q sont proches. Les modules des corrélations mesurées aux retards de un à huit symboles restent inférieurs à 0,027. La dispersion des phases sur 34 blocs de 128 symboles vaut 0,0182 radian, contre une approximation de 0,0154 pour le bruit blanc circulaire ajusté. Ces observations sont compatibles avec une dégradation principalement bruitée ; elles ne prouvent ni la blancheur exacte du bruit ni l’absence d’une autre méthode utile.

Le même script calcule aussi une prédiction du BER sous le modèle circulaire ajusté, avec la table de bits du préfixe. Le BER après décision de symbole est calculé par les probabilités gaussiennes de franchissement des seuils. Le BER minimal par bit **dans ce modèle sans mémoire et à symboles uniformes** est obtenu en intégrant les densités des deux valeurs de chaque bit, puis leur minimum. Des grilles de 401 et 801 points par axe vérifient la stabilité numérique ; les tableaux temporaires sont limités à 8 192 points par seize symboles. La seconde grille prédit environ **630 erreurs sur 17 904 bits**, contre **602 observées**. Les deux résolutions diffèrent de moins d’une erreur sur cet intervalle. Un test Monte-Carlo indépendant vérifie les deux BER théoriques. Cette comparaison situe l’ordre de grandeur des erreurs ; ce modèle n’est pas une borne pour un décodeur utilisant un code correcteur, une mémoire de canal ou la structure d’un protocole.

## Détection de séquences et bruit impulsionnel

`scripts/qam_sequence_study.py` teste deux hypothèses supplémentaires après reconstruction du même premier filtre RRC. La table de bits et la phase PRBS sont acquises une fois sur le préfixe de référence, puis restent fixes pour toutes les voies et les mêmes 17 904 bits de vérification.

Le détecteur BCJR utilise le modèle `y[n] = h0·s[n] + h1·s[n−1] + w[n]`. Ses seize états représentent le symbole précédent et ses 256 branches les couples précédent/courant. Les passages avant et arrière, avec normalisation à chaque étape, calculent les probabilités marginales des symboles ; les LLR résultent des sommes par valeur de bit. Les états initial et terminal sont inconnus et uniformes. Le traitement utilise toute la fenêtre hors ligne, au plus 10 000 symboles, sans code correcteur ni prior PRBS.

Le gain principal, le coefficient d’interférence et la variance de bruit sont appris sur les seuls 512 premiers symboles non étiquetés. Huit itérations EM utilisent les probabilités des branches, sans décisions imposées ni symboles attendus. Deux pénalités fixes du coefficient d’interférence sont rapportées, nulle ou `0,05 × nombre de symboles`. Une voie témoin utilise le même ajustement initial sur préfixe, sans itération ni mémoire, pour distinguer l’effet du segment d’apprentissage de celui du BCJR. Le gain principal reste borné entre 0,5 et 2 ; le coefficient secondaire ne peut dépasser la moitié de son module.

Une variante supplémentaire du même BCJR apprend les paramètres sur toute la fenêtre non étiquetée, avec huit itérations et la pénalité fixe de 0,05. Elle utilise les échantillons de la suite pour ajuster le canal, sans accès aux bits attendus ; elle doit donc être distinguée des voies à paramètres appris uniquement sur préfixe. Sa calibration points/bits et sa phase PRBS restent celles du préfixe de référence, comme pour les autres méthodes. Le rapport déclare pour chaque voie son périmètre et son nombre de symboles d’ajustement.

La voie de bruit impulsionnel ajuste, sur les échantillons non étiquetés de la fenêtre, un gain complexe commun et deux composantes de bruit gaussien circulaire. Les 32 itérations EM estiment leurs variances et probabilités ; les probabilités sont bornées entre 2 % et 98 %. Les vraisemblances marginalisent les deux composantes avant de sommer les états associés à chaque valeur de bit. Aucun bit de vérification ne choisit une composante ou un modèle.

Les tests comparent le BCJR à l’énumération exhaustive des 65 536 séquences possibles pour trois observations et un symbole précédent inconnu. Ils vérifient son identité avec les LLR sans mémoire lorsque le coefficient secondaire est nul, l’apprentissage d’un canal synthétique inconnu et l’invariance de ses paramètres quand seule la suite change. Un autre essai apprend le bruit impulsionnel sur des symboles aléatoires et mesure la qualité probabiliste sur des symboles indépendants. Des composantes de même variance doivent restituer les LLR gaussiens existants.

Un diagnostic séparé mesure sur les résidus de référence le moment radial d’ordre quatre, des quantiles, des probabilités de queue et la corrélation avec le symbole précédent. Ces statistiques descriptives ne servent à aucun ajustement. Les mesures de toutes les voies sont enregistrées dans `sequence-study.json`, sans modification du chemin d’acceptation automatique.

Les [mesures du banc complet](https://github.com/sebadiaz/IQScope/actions/runs/42461984466), enregistrées dans `corpus/qam-sequence-observation.json`, donnent sur la capture faible :

| Voie | Symboles servant à l’ajustement | Erreurs sur 17 904 bits | Erreurs anciennes corrigées | Erreurs nouvelles introduites |
| --- | ---: | ---: | ---: | ---: |
| Probabilités circulaires actuelles | 4 988 | 602 | — | — |
| Bruit impulsionnel à deux composantes | 4 988 | 607 | 0 | 5 |
| Témoin sans mémoire appris sur préfixe | 512 | 622 | 17 | 37 |
| BCJR, pénalité 0,05 | 512 | 634 | 39 | 71 |
| BCJR, sans pénalité | 512 | 637 | 43 | 78 |
| BCJR, pénalité 0,05, fenêtre complète | 4 988 | 615 | 16 | 29 |

Les cinq autres captures restent à zéro erreur pour les six voies. Les empreintes des bits de référence restent identiques à celles des études précédentes, dont `b3b1c4c30aaed626eed153081907322f6325e409596c2834285c6bb5984710ac` pour `f`. Les voies BCJR réduisent la variance ajustée tout en ajoutant davantage d’erreurs qu’elles n’en corrigent. L’effet n’est donc pas un gain de décodage. La variante complète estime un coefficient secondaire d’environ 1,02 % du gain principal.

Sur les 4 476 symboles de vérification de `f`, le rapport `E|r|⁴ / (E|r|²)²` vaut 2,00985, contre 2 pour un bruit gaussien circulaire. Les quantiles à 90 %, 99 % et 99,9 % de `|r|² / E|r|²` valent 2,30566, 4,63646 et 7,03504, contre 2,30259, 4,60517 et 6,90776 sous cette hypothèse. Le mélange aveugle ajuste des variances de 0,05236 et 0,07809, avec environ 22,2 % dans la seconde composante ; il n’établit pas une population distincte d’impulsions extrêmes. Ces mesures renforcent la compatibilité avec un bruit principalement gaussien, sans constituer un test de normalité ni une preuve d’optimalité du récepteur.

Sur le canal synthétique indépendant à deux coefficients, les 1 077 erreurs de symboles avant traitement deviennent zéro après apprentissage aveugle sur préfixe et BCJR. Ce résultat vérifie que le détecteur peut corriger une interférence réellement présente ; il ne se transpose pas à un gain sur `f`. Tous les résultats réels ci-dessus restent exploratoires sur le corpus de développement. Le refus automatique de la capture faible et les exports génériques restent ceux du récepteur courant.

Les rapports donnent `clock_search_mode`, la marge en bauds et les facteurs réels de rééchantillonnage. Chaque essai de filtre conserve aussi la période utilisée pour ses coefficients RRC, distincte du débit affiné ensuite. Le banc reconstruit les décisions avec ces paramètres exacts, y compris pour l’interpolation par trois.
