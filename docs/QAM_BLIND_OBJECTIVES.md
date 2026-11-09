# Objectifs aveugles et bruit dans l'égalisation 16-QAM

Cette étude prolonge le [banc Gardner et CMA/MCMA–RDE](QAM_BLIND_SYNC.md). Son objectif est de comprendre pourquoi des filtres qui récupèrent un canal synthétique déformant augmentent les erreurs sur une constellation déjà correctement échantillonnée mais bruitée. Elle ne change pas le décodeur générique, ses seuils ou les bits exportés.

## Comparaisons fixées avant la mesure RF

Le banc emploie les mêmes vecteurs bruts de 21 coefficients espacés de T/2. Il compare quinze voies : la référence circulaire, une projection linéaire de ses échantillons complexes, l'ancien MCMA stochastique puis RDE, quatre sorties de calcul global démarré au coefficient central, six sorties démarrées à la projection initiale, et deux corrections des moments du bruit.

La projection reproduit la sortie complexe non étiquetée du récepteur initial par moindres carrés, avec régularisation relative 10⁻⁴. Elle n'utilise pas de symboles idéaux ou de décisions binaires. Le calcul global optimise séparément MCMA puis RDE par L-BFGS-B, au plus 80 itérations par étage. Les deux sorties et leurs états d'optimisation sont conservés. La variante pondérée utilise l'inverse de l'énergie des vecteurs : elle examine l'effet de la normalisation des mises à jour antérieures. Le calcul global n'utilise pas leur écrêtage, ce qui empêche d'attribuer toute différence à la seule stochasticité.

Les démarrages sur projection ajoutent ½λ E|X(c − c₀)|² au coût, avec λ = 0 / 0,01 / 0,1. Cet ancrage limite l'abandon du filtre initial ; il n'est pas un apprentissage sur PRBS. La voie principale retenue après les seuls contrôles synthétiques est MCMA avec pénalité 0,1, avant RDE. Les autres configurations restent publiées.

## Correction des moments gaussiens

Pour un bruit additif complexe gaussien propre, indépendant du signal, de variance complexe v, les moments vérifient :

- puissance observée P = puissance propre + v ;
- somme des moments quatrièmes des deux axes F = F_propre + 3v × puissance propre + 1,5v².

Avec la constante MCMA R = 0,82, le coût propre estimé devient :

    J(c) = [F − (3v + 2R)P + 1,5v² + 2Rv + 2R²] / 4

La variance dépend du filtre : v(c) = cᴴNc, où N est la covariance des vecteurs de bruit avec la convention E[XᴴX]/n et la sortie Xc. Sa dérivée est incluse dans le gradient. La correction est exacte en espérance sous ces hypothèses ; elle ne rend pas exacte l'estimation de moments sur une fenêtre finie.

Dans le contrôle synthétique, N est connu à partir du bruit injecté. Sur les IQ réels, N est estimé par la moyenne des deux enregistrements de bruit séparés, filtrés et interpolés sur la même grille. Leurs puissances sont ramenées à l'échelle de la capture cible. Cela suppose des enregistrements représentatifs et une échelle de réception commune, sans bruit simultanément mesuré. La pseudo-covariance relative est rapportée pour documenter l'hypothèse de bruit propre ; aucune compensation automatique de son éventuelle impropriété n'est prétendue.

SLSQP minimise le coût corrigé avec un déplacement RMS de sortie limité à 5 % ou 15 % de la sortie initiale. Le meilleur coût non étiqueté parmi les évaluations admissibles et l'étape terminale projetée est conservé, avec le filtre initial inclus. L'état terminal du solveur reste rapporté, même s'il échoue ; un coût inférieur ne devient pas une garantie de BER. La contrainte à 5 % est la seconde voie principale prédéfinie.

## Contrôles et périmètre

Trois graines synthétiques de développement (811 / 922 / 1033) servent à choisir les paramètres avant lecture des nouveaux résultats RF. Deux graines nouvelles (1207 / 1439), ensuite conservées sans retouche des paramètres, contrôlent leur transfert. Chaque graine produit 5 000 symboles 16-QAM uniformes, un canal identité à deux points par symbole et deux variances de bruit circulaire : 0,0008 et 0,057. Les échantillons intermédiaires contiennent seulement du bruit. Ce modèle ne reproduit pas la mise en forme RF.

Le contrôle synthétique vérifie 17 792 bits après le préfixe et avant le bord final. Sur les six captures réelles, toutes les voies partagent la correspondance binaire et la phase PRBS acquises sur les 512 premiers symboles de la référence initiale. Retard entier jusqu'à ±6 symboles (les 21 coefficients couvrent ±5 symboles, plus une marge d'un symbole), conjugaison et quart de tour sont résolus sur le seul préfixe complexe non étiqueté ; un mauvais accord est signalé, pas dissimulé par une recherche sur la suite. Le préfixe est exclu du score. Les mêmes 17 904 bits de vérification sont conservés, dont 17 744 effectivement traités : les quarante premiers et derniers symboles conservent les LLR initiaux.

Les six nouveaux tests vérifient les gradients complexes contre des différences finies indépendantes, la correction des moments gaussiens contre une construction statistique indépendante, la récupération d'un canal déformant, la contrainte RMS avec changement d'échelle la validation des budgets/covariances et la récupération des retards de filtre à ±5 symboles sans consultation de la suite. Les bits attendus servent uniquement à ces vérifications et aux scores, jamais aux mises à jour des filtres.

## Résultats réels

Le [banc du commit cdee716](https://github.com/sebadiaz/IQScope/actions/runs/42657163501) conserve les [mesures compactes](../corpus/qam-blind-objective-observation.json). Le JSON complet avec coefficients et états d'optimisation est joint à cette exécution CI.

| Voie | Erreurs sur les mêmes 17 904 bits de `f` | Contrôle des cinq captures fortes |
| --- | ---: | --- |
| Référence circulaire | 602 | zéro erreur |
| Projection du récepteur initial | 606 | zéro erreur |
| Ancien MCMA stochastique → RDE | 1 346 | zéro erreur |
| MCMA global, démarrage central | 1 098 | 43 erreurs sur e, 5 sur d |
| Puis RDE, alignement corrigé | 712 | zéro erreur |
| MCMA global ancré à 0,1, voie principale | 886 | 6 erreurs sur e |
| Puis RDE, contrôle de sensibilité | 738 | zéro erreur |
| Moments corrigés, déplacement maximal 5 %, voie principale | 656 | zéro erreur |
| Moments corrigés, déplacement maximal 15 % | 989 | 1 / 1 / 2 / 12 / 49 erreurs sur a–e |

Aucune configuration de ce comparateur ne bat 602. La voie MCMA principale corrige 157 erreurs initiales mais en introduit 441 ; la correction du bruit à 5 % en corrige 73 et en introduit 127. L'ancrage limite la dégradation du traitement stochastique, sans en faire un meilleur récepteur que la référence. La projection suit de près le préfixe initial (MSE ≈1,29×10⁻⁶ sur f), mais elle ajoute néanmoins quatre erreurs nettes de vérification : elle est donc rapportée comme contrôle distinct.

Les deux optimisations principales sur f annoncent une convergence : MCMA fait passer son coût de 0,14804 à 0,14396 en 67 itérations ; la correction des moments de 0,12942 à 0,12591 en 49 itérations. Leurs BER empirent. Ce constat ne s'explique donc pas seulement par un arrêt prématuré du solveur. Les sorties RDE atteignent souvent leur budget d'itérations ; leurs résultats ne sont pas décrits comme des optima garantis. Une répétition sur des runners différents a donné 745 puis 738 erreurs pour le RDE ancré à 0,1, avec retard nul dans les deux cas : cette sensibilité numérique est conservée comme limite de convergence, sans sélection d'une répétition au BER.

La covariance de bruit séparée a une pseudo-covariance relative de 4,56 % sur f. Ce diagnostic ne prouve pas un bruit parfaitement propre, indépendant du signal ou stationnaire entre les enregistrements. Même dans les contrôles synthétiques où sa variance est connue, la correction des moments ne garantit pas de meilleures décisions après apprentissage.

## Défaut de couverture du retard corrigé

La première exécution cherchait seulement ±3 symboles pour aligner la sortie sur le préfixe. Un filtre de 21 coefficients à T/2 peut couvrir ±5 symboles. Plusieurs RDE se déplacent effectivement de quatre symboles : le pic des coefficients se trouve au coefficient 18, et l'accord au préfixe initial devient mauvais. La recherche est maintenant bornée à ±6 pour cette étude, à partir du support physique du filtre, avec un test indépendant des décalages ±5. Les autres utilisateurs du synchroniseur gardent leur borne par défaut ±3.

| Voie sur f | Avant, recherche ±3 | Après, recherche ±6 | Retard trouvé |
| --- | ---: | ---: | ---: |
| RDE global non pondéré | 8 795 | 712 | −4 |
| RDE global pondéré | 8 825 | 722 | −4 |
| RDE sans ancrage, démarrage sur projection | 8 796 | 709 | −4 |

Pour le premier cas, la MSE du préfixe passe de 1,715 à 0,00460. C'était un défaut de mesure du retard ; l'empreinte de référence reste identique pour les six captures. Sur e, le RDE pondéré reste en échec malgré cette correction : 4 154 erreurs et une MSE de préfixe de 0,322, signalée comme accord non fiable. Il n'est donc pas présenté comme réparé par le seul élargissement du retard.

## Validation synthétique indépendante

À variance 0,0008, les deux voies principales gardent zéro erreur pour les cinq graines. À variance 0,057 :

| Graine et rôle | Référence | Ancien MCMA–RDE | MCMA global ancré 0,1 | Moments corrigés à 5 % |
| --- | ---: | ---: | ---: | ---: |
| 811, development | 501 | 620 | 521 | 549 |
| 922, development | 569 | 721 | 581 | 603 |
| 1033, development | 576 | 697 | 607 | 643 |
| 1207, validation | 552 | 663 | 581 | 619 |
| 1439, validation | 565 | 695 | 599 | 628 |

Chaque ligne mesure 17 792 bits synthétiques, distincts des 17 904 bits réels. Le calcul global et l'ancrage réduisent le dommage, mais les deux nouvelles graines confirment encore une dégradation par rapport au canal identité initial. Cela motive un objectif de vraisemblance ou de reconstruction de la forme d'onde qui traite explicitement le bruit, plutôt que d'assimiler automatiquement une baisse du coût de module à une meilleure réception. Ces résultats ne démontrent pas une limite des IQ bruts. Aucun FEC ou protocole supplémentaire n'est établi, et aucune variante n'est activée dans le chemin générique.
