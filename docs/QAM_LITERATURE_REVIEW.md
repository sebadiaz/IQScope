# Revue des solutions pour la capture 16-QAM faible

Lecture du 8 novembre 2026. Code IQScope relu à la version `052e42cc4f15aeb5f7a8b90ff3f5d00cc415e156`, avec les observations QAM, les scripts de reconstruction, de phase et de détection de séquences. Cette revue apporte des pistes et un protocole d’essai ; elle ne rapporte aucun nouveau décodage de la capture réelle.

Mise à jour après cette lecture : le [premier banc fractionnaire sur préfixe](QAM16.md#filtres-fractionnaires-appris-sur-préfixe) est désormais mesuré. Il donne 638 erreurs pour le filtre aidé choisi sur les IQ, contre 602 pour la référence ; les contrôles et toutes les configurations sont publiés. Ce résultat concerne l’étape de diagnostic décrite ci-dessous, sans constituer l’essai CMA/MCMA–RDE proposé ensuite.

Le [transfert depuis les captures fortes et son adaptation au bruit mesuré](QAM16.md#calibration-à-partir-des-captures-fortes) est également évalué : les choix de calibration donnent 617 et 620 erreurs, puis 612 et 610 avec le bruit moyen, contre 602 actuellement. Les minima exploratoires ne sont pas présentés comme des choix automatiques. L’estimation sur acquisitions séparées est donc testée dans ce cadre, tandis que CMA/MCMA–RDE et la comparaison de synchroniseurs restent distinctes.

La priorité qui ressort est **l’apprentissage du filtre de réception avant la réduction à un point par symbole**, avec égalisation fractionnaire. Les échecs de nos corrections après filtrage ne suffisent pas à écarter cette famille. Les 602 erreurs actuelles sont un résultat mesuré du récepteur, pas une limite démontrée des échantillons IQ bruts.

## Ce que les éléments du projet établissent

Le [README de la source figée](https://github.com/billjgavin/28_and_75GHz_Capture_Files/blob/3f9ea40d9b187d0819b14cb254dc04905d398889/README.txt) annonce PRBS15, 50 Mbaud, 200 Méch/s, 160 MHz de bande FI et 100 µs par acquisition conduite. Il ne précise pas le filtre d’émission ni son roll-off. La plage de SNR figurant dans la présentation des captures 75 GHz ne fournit pas le SNR individuel de notre fichier 28 GHz. Un niveau de générateur n’est pas un SNR.

Les mesures internes, distinctes de la littérature, sont reproductibles dans [l’observation de séquences](../corpus/qam-sequence-observation.json) et [le banc CI](https://github.com/sebadiaz/IQScope/actions/runs/42461984466) :

| Élément | Résultat ou hypothèse | Conséquence pour la recherche |
| --- | --- | --- |
| Référence faible `f` | 602 erreurs sur 17 904 bits après décision probabiliste ; 610 après décision de symbole | Conserver ce segment et ces deux témoins |
| Autres captures 16-QAM | Zéro erreur sur la suite des cinq captures fortes | Vérifier leur conservation, sans en déduire un fonctionnement optimal à faible SNR |
| Modèle de bruit après reconstruction | Moment radial normalisé 2,00985 ; voisin de 2 pour le modèle gaussien | Compatibilité descriptive après traitement, pas preuve sur la chaîne brute |
| Prévision AWGN | Environ 630 erreurs avec le modèle circulaire ajusté | Prévision conditionnelle à cette représentation et ce modèle |
| BCJR | 615 à 637 erreurs | Canal à deux coefficients essayé sur les symboles reconstruits |
| Bruit impulsionnel | 607 erreurs | Le mélange testé n’améliore pas la décision actuelle |

Dans [le récepteur](../iqscope_qam.py), les essais utilisent trois RRC de roll-offs 0,2, 0,35 et 0,5. Le réglage de cadence et de phase minimise une distance aux points décidés, après normalisation RMS et estimation de rotation par moment d’ordre quatre. [La reconstruction](../scripts/qam_receiver_study.py) fournit ensuite un seul point complexe par symbole aux études EM, de phase et BCJR.

L’étude Lanczos constitue une exception importante : elle repart bien des IQ pour modifier interpolation, longueur et roll-off du filtre. Elle conserve toutefois une famille RRC et un critère de décision voisin ; elle ne teste pas un égaliseur fractionnaire apprenant le filtre d’entrée. Il serait donc inexact d’écrire que tous les essais antérieurs ignoraient les IQ bruts, comme il serait inexact d’affirmer que l’égalisation fractionnaire a déjà été testée.

Un filtre adapté correct suivi d’un bon échantillonnage peut fournir des statistiques suffisantes à un point par symbole. Deux points ne créent pas d’information supplémentaire. L’intérêt proposé ici est de **vérifier et apprendre la transformation qui précède cette réduction**, puisque sa forme exacte n’est pas documentée par la source.

## Solutions et sources consultées

**Égalisation fractionnaire.** La notice primaire [Bell Labs, *Fractionally-Spaced Equalization: An Improved Digital Transversal Equalizer* (1981)](https://www.nokia.com/bell-labs/publications-and-media/publications/fractionally-spaced-equalization-an-improved-digital-transversal-equalizer/) décrit un égaliseur dont les coefficients sont espacés d’une fraction du symbole, capable de réaliser conjointement filtrage adapté et égalisation avec une moindre sensibilité à la phase d’échantillonnage. Notice consultée ; aucun gain numérique de ce contexte modem n’est transféré à notre corpus RF.

**Cas explicite 16-QAM.** Le résumé éditeur de [Fatadin, Ives et Savory, *Blind Equalization and Carrier Phase Recovery in a 16-QAM Optical Coherent System* (2009)](https://opg.optica.org/jlt/abstract.cfm?uri=jlt-27-15-3042) compare CMA, RLS-CMA et RDE avec sept coefficients espacés de T/2. Le texte intégral n’était pas accessible ; le dépôt NPL indique également son absence. Cette référence justifie une famille à examiner, pas des paramètres prétendument reproduits de l’article complet. Les distorsions optiques et la double polarisation ne sont pas celles de notre liaison RF conduite.

**Récepteur aveugle avec filtre inconnu.** La [notice et le résumé de la thèse d’Evren Terzi (2009)](https://digitalcommons.usf.edu/etd/48/) décrivent l’estimation du débit, du roll-off, de la phase d’échantillonnage et des décalages de fréquence/phase pour la QAM monoporteuse. Le téléchargement institutionnel du PDF a renvoyé 403 ; seuls la notice et le résumé sont utilisés ici. Cela confirme l’importance de l’hypothèse de pulse shaping, sans fournir une implémentation que nous aurions validée.

**Synchronisation implémentée.** La documentation complète de [GNU Radio `symbol_sync_cc`](https://gnuradio.readthedocs.io/en/latest/classgr_1_1digital_1_1symbol__sync__cc.html) permet de choisir le nombre de points de sortie par symbole et un interpolateur avec filtre adapté polyphasé. Le gain attendu du détecteur temporel dépend de l’amplitude, de l’impulsion et d’Es/N0. Ces paramètres ne doivent pas être repris comme des constantes universelles. Les pages [liquid-dsp `symsync`](https://www.liquidsdr.org/doc/symsync/) et [`symtrack`](https://www.liquidsdr.org/doc/symtrack/) décrivent des chaînes existantes de synchronisation et de suivi avec égalisation. Ce sont des comparateurs possibles, sous hypothèses de modulation et de filtre configurées, pas des identificateurs universels automatiques.

**Mesure à faible SNR.** Le PDF R&S de 16 pages [*Measuring the BER and the EVM for Signals with Low SNR*](https://scdn.rohde-schwarz.com/ur/pws/dl_downloads/dl_common_library/dl_manuals/dl_application_sheet/FSW_VSA_BER_ApplicationSheet_en_01.pdf) a été consulté, notamment les pages 7 et 12–13 : une référence construite à partir de mauvaises décisions fausse la mesure ; le document traite aussi d’égalisation, de durée d’estimation et d’erreur de débit symbole. Pour IQScope, cela motive la comparaison à une référence connue dans le banc et l’abandon de l’EVM sur décisions comme seul critère de progrès. Cette référence de mesure ne doit pas remplacer les bits reçus dans les exports génériques.

**Apprentissage aveugle sur la forme d’onde.** L’article complet de [Lauinger, Buchali et Schmalen, *Blind Equalization and Channel Estimation … Using Variational Autoencoders* (2022)](https://arxiv.org/html/2204.11776) a été consulté : sections III–IV pour l’objectif et l’implémentation, V pour les conditions et résultats. Il traite notamment deux points par symbole avec apprentissage du filtrage adapté. Ses évaluations utilisent des flux longs, principalement des exemples 64-QAM ; notre fenêtre de 4 988 symboles exige une vérification distincte de convergence. Cette piste vient après un comparateur linéaire classique, sans supposer qu’un réseau garantit un gain.

**Bruit avant filtrage.** Le [plan de cours MIT 6.432, recitation 10](https://ocw.mit.edu/courses/6-432-stochastic-processes-detection-and-estimation-spring-2004/3cfb51ce35fb9bde72134004b4aa11b5_rec10.pdf) rappelle le blanchiment avant détection en bruit gaussien coloré. Les deux enregistrements de bruit du corpus peuvent servir à examiner sa densité spectrale et ses corrélations temporelles. L’essai de covariance I/Q instantanée déjà effectué ne remplace pas cette mesure temporelle sur les IQ d’entrée. L’utilité d’un blanchiment reste à établir sur les fichiers.

## Vérification du code disponible

Le code a été lu sans l’exécuter ni l’intégrer au récepteur.

| Projet et version consultée | Éléments vérifiés | Adaptation nécessaire |
| --- | --- | --- |
| [QAMpy `918723a`](https://github.com/ChalmersPhotonicsLab/QAMpy/tree/918723ad0f1ccfa413614410da54eb7592976400) | `qampy/core/equalisation/equalisation.py` expose `os`, `Ntaps`, `TrSyms`, `Niter`, des méthodes CMA/MCMA/RDE et une séquence de deux méthodes ; application du filtre avec décimation | Une seule voie complexe pour notre RF ; mêmes conventions de gain, retard et rotation |
| [Exemple QAMpy](https://github.com/ChalmersPhotonicsLab/QAMpy/blob/918723ad0f1ccfa413614410da54eb7592976400/Scripts/64_qam_equalisation.py) | Deux points par symbole, treize coefficients, 2^17 symboles, 64-QAM ; ce fichier utilise MCMA puis MDDMA | Ses valeurs ne constituent pas une recette validée sur nos 4 988 symboles 16-QAM |
| [VAE equalizer `16ea15b`](https://github.com/kit-cel/vae-equalizer/tree/16ea15b287c9d9a2f232181c4c31a71d89f0712a) | Branche AWGN lue, notamment `AWGN_channel/func_VAELE_MQAM_shaping.py` | Le programme est un environnement de simulation, pas un importeur IQ |

Dans ce dernier fichier, la fonction de coût utilise les observations et les probabilités de symboles, avec reconstruction sur les points suréchantillonnés. Les symboles simulés de vérité servent à l’évaluation. Le programme accepte aussi la 16-QAM, mais génère des données nouvelles pendant l’apprentissage et fournit au démappeur une variance issue du SNR de simulation (`10**(-SNR/10)`). Une adaptation réelle devra estimer cette grandeur sans les bits de vérification et travailler dans le budget de la capture. Le code ne peut donc pas être appliqué tel quel pour annoncer un résultat sur `f`.

## Protocole proposé pour IQScope

Les étapes suivantes sont une proposition issue de cette lecture, pas des mesures déjà réalisées.

1. **Établir un témoin aidé du filtre d’entrée.** Construire des vecteurs de points espacés de T/2 à partir des IQ, avant le RRC imposé. Apprendre un filtre linéaire régularisé avec les symboles connus du seul préfixe, puis le figer sur la suite. Une autre expérience peut estimer l’impulsion sur les captures fortes séparées et vérifier sa transférabilité. Ce témoin est explicitement aidé : il mesure un potentiel de correction linéaire et ne compte pas comme décodage aveugle. Il ne remplace jamais la suite reçue par le PRBS attendu.

2. **Tester l’égalisation fractionnaire aveugle.** Utiliser deux points par symbole avec antirepliement adapté et coefficients espacés de T/2 ; comparer des longueurs prédéfinies, par exemple sept et treize. Essayer CMA/MCMA pour l’acquisition puis RDE ou une mise à jour à décisions fiables. La 16-QAM a trois rayons : un coût de module constant reste un outil d’acquisition, pas une preuve de constellation correcte. Choisir les pas et budgets sur des synthétiques indépendants, puis les figer avant la comparaison réelle.

3. **Comparer une synchronisation polyphasée indépendante.** Conserver deux points à la sortie du synchroniseur pour l’égaliseur. Vérifier normalisation de constellation, gain du détecteur temporel, bande de boucle et transitoires. Comparer filtre d’impulsion appris et famille RRC estimée à partir des IQ ; ne pas appeler « estimation du filtre d’émission » le seul choix du meilleur de trois filtres sur l’EVM décidée.

4. **Examiner le bruit brut et l’objectif d’ajustement.** Mesurer le spectre des captures de bruit et conditionner un éventuel blanchiment à ce résultat. Pour comparer des modèles de filtrage, préférer une reconstruction de la forme d’onde et une vraisemblance tenant compte de l’énergie et du bruit. Une variance minimale obtenue après renormalisation ne suffit pas à comparer des filtres qui ont transformé différemment signal et bruit.

5. **Évaluer l’option variationnelle seulement ensuite.** Adapter le modèle linéaire mono-voie du VAE, avec estimation de variance et budget explicites, si un défaut de filtrage est mis en évidence ou si le comparateur classique échoue à converger. Publier aussi les échecs d’initialisation. Les résultats sur des flux de simulation longs ne préjugent pas de ceux d’une fenêtre courte.

Pour le témoin linéaire, une formulation possible est `w = (Ryy + λI)^−1 rya`, avec `Ryy = E[y yᴴ]`, `rya = E[y a*]` et sortie `wᴴy`. Ici `y` est un vecteur de points IQ voisins et `a` le symbole de référence du préfixe seulement. Le retard et la régularisation sont déterminés sur l’apprentissage ; les bits de la suite ne participent à aucun ajustement.

Les comparaisons doivent conserver les 17 904 bits de vérification et leurs empreintes. Retard entier, rotation et conjugaison éventuels sont résolus sur le préfixe ; les bords et le retard des filtres sont compensés avant le décompte. Les paramètres appris sur toute la forme d’onde non étiquetée restent permis comme expérience distincte, avec périmètre déclaré. Toute sélection d’hyperparamètres après consultation du BER réel doit être rapportée comme exploration, pas comme validation indépendante.

Un gain doit être vérifié par le BER et les erreurs corrigées/introduites, avec conservation des cinq références fortes et des contrôles négatifs. Une constellation resserrée par un égaliseur n’est pas, à elle seule, une preuve de meilleure réception. Les seuils d’acceptation ne sont pas abaissés pour fabriquer un gain.

La référence faible contient toujours 602 erreurs avec la meilleure voie retenue. Le [comparateur Gardner et CMA/MCMA–RDE](QAM_BLIND_SYNC.md) a maintenant évalué quinze voies sur six captures : aucune nouvelle configuration ne bat cette référence. Les trois voies principales donnent 655, 1 346 et 1 269 erreurs, avec zéro erreur sur les cinq captures fortes. Les variantes de boucle rapide dégradent aussi les captures fortes. Cette première réalisation des étapes 2–3 ne couvre pas tous les gains de boucle, initialisations ou budgets possibles ; l'acquisition grossière de débit/porteuse reste commune. L'objectif variationnel demeure à adapter et à évaluer. Aucun FEC ou protocole supplémentaire n'est établi par les éléments consultés.
