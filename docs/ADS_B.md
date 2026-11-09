# Indicatifs et positions ADS-B

IQScope complète l'extraction de contenu des trames Mode S déjà reçues : indicatif de vol, coordonnées aériennes et vitesses apparaissent dans l'interface et le rapport JSON. Le nouveau module n'ajoute aucun moteur externe ni téléchargement au moment de l'analyse.

## Périmètre

Le démodulateur PPM conserve son traitement et ses budgets : entrée d'au moins 2 Méch/s, grille d'énergie à 8 Méch/s, recherche de 2 000 candidats et 100 paquets par défaut. Les champs supplémentaires sont interprétés après contrôle CRC-24. Les DF17 et DF18 restent des paquets conservés ; les nouveaux champs sont limités aux DF17 et DF18 CF0/1, où le corps ADS-B utilisé ici est applicable. Les autres contrôles DF18 conservent leurs octets et leur note de sémantique d'adresse, sans identification, altitude barométrique ou coordonnées supposées.

Les messages d'identification TC1–4 fournissent huit caractères. Les lettres, chiffres et espaces sont décodés ; les espaces extérieurs sont retirés. Un caractère réservé ou un identifiant vide produit un statut explicite sans indicatif fabriqué. L'indicatif est une donnée diffusée, pas un identifiant unique d'aéronef.

Les positions aériennes TC9–18 sont reconstruites par CPR global, avec un message pair et un impair de même adresse, format et contrôle. Leur séparation maximale est de dix secondes. Les zones de latitude doivent être compatibles ; les coordonnées de la trame la plus récente sont retenues et la longitude est ramenée dans [−180°, 180°). Le calcul gère les deux hémisphères et les cas polaires de NL.

## Intégration et provenance

Le traitement garde un état temporaire dans une seule analyse. Il trie les observations par temps pour choisir une paire, tout en conservant l'ordre et les données originales dans le résultat. Une paire d'une autre adresse, d'un autre contrôle DF18 ou d'une analyse précédente ne sert pas à remplir les coordonnées. Un temps non fini ou négatif, une paire trop ancienne, une latitude impossible ou des zones incompatibles laissent la position non résolue.

Le champ facultatif callsign est ajouté aux champs de la trame d'identification. Les coordonnées latitude_deg et longitude_deg sont ajoutées à la trame qui complète une paire admissible. Le champ cpr conserve le format, les codes reçus et le statut. position_evidence conserve les instants et indices source des deux trames, l'âge de la paire, l'instant de la position et la méthode. Ces temps sont relatifs à la capture et dépendent de son débit d'échantillonnage ; ils ne représentent pas une heure UTC reçue du satellite ou une télémétrie du SDR.

La trame reçue en premier n'est pas modifiée rétroactivement pour lui attribuer la position plus récente. Les compteurs de paquets CRC ne changent pas : l'ajout d'une position ne compte pas comme une trame supplémentaire. Les paquets déjà acceptés et leurs octets restent exportés. L'interface utilise des éléments texte pour afficher l'indicatif et des coordonnées à cinq décimales ; le nombre de décimales affiché ne constitue pas une garantie de précision.

## Vérification

Les exemples publics de Junzi Sun donnent une vérification indépendante des octets, du CRC et des valeurs attendues :

- identification : 8D4840D6202CC371C32CE0576098 → KLM1023 ;
- paire : 8D40621D58C382D690C8AC2863A7 et 8D40621D58C386435CC412692AD6 ;
- avec la trame paire plus récente : latitude 52,2572021484375°, longitude 3,91937255859375°.

Les tests passent aussi par une construction PPM indépendante du récepteur pour retrouver trois paquets et leurs champs. Les contrôles examinent la parité, l'adresse et le domaine DF18, l'expiration à dix secondes, l'ordre des temps, l'absence d'état entre analyses, les CRC corrompus, les caractères réservés et les formats exclus. Des transformations géométriques de la référence couvrent les hémisphères et le passage de la longitude à ±180°. Un test navigateur importe cette IQ synthétique et vérifie l'indicatif, les coordonnées, le compteur de trois paquets et la trame encore sans position.

Ces IQ de test sont une modulation synthétique de messages publiés ; elles ne sont pas présentées comme un nouvel enregistrement RF réel.

## Limites

Aucun décodage de position au sol, de CPR local sur une référence géographique, de position GNSS TC20–22, de trajectoire entre analyses n'est ajouté. Une capture trop courte pour contenir une paire peut livrer des paquets et une altitude sans coordonnées. Les collisions et corrections de bits restent hors périmètre du récepteur.

Un CRC valide vérifie les bits du paquet, sans authentifier la station ni garantir la véracité, l'intégrité de navigation ou la précision de sa position. Les indicateurs NIC complets, GVA et SDA restent hors périmètre ; le traitement de NACp, NACv et SIL est décrit dans la section statut ci-dessous. Les DF18 ne sont pas automatiquement étiquetés ICAO.

Sources des formats et valeurs de référence : [Aircraft Identification](https://mode-s.org/1090mhz/content/ads-b/2-identification.html) et [Airborne Position](https://mode-s.org/1090mhz/content/ads-b/3-airborne-position.html), The 1090 Megahertz Riddle, Junzi Sun. La distinction des corps DF18 est également vérifiée dans [dump1090, mode_s.c](https://github.com/flightaware/dump1090/blob/master/mode_s.c). Les formules sont implémentées directement, sans reprise d'une bibliothèque de décodage tierce.

## Vitesses et direction du mouvement

Les TC19 valides apportent leurs valeurs indépendamment d'une paire CPR ou d'une position résolue. Le champ velocity du JSON précise le sous-type, les disponibilités et les unités. Aucun suivi ni calcul de vitesse à partir de positions successives n'est utilisé.

Les sous-types 1/2 donnent les composantes est/nord, la vitesse au sol et sa route. Les sous-types 3/4 donnent une vitesse air IAS ou TAS et, si son indicateur est valide, un cap. Les résolutions horizontales sont respectivement 1 ou 4 kt. Le TC19 seul laisse ici la référence vraie/magnétique du cap non déterminée ; l'interface conserve cette distinction avec la route au sol. La vitesse verticale est signée en ft/min et étiquetée GNSS ou barométrique selon sa source.

Un code absent n'est pas transformé en zéro. Une vitesse réellement nulle reste affichable ; la route d'un vecteur sol nul reste indéfinie. Une seule composante sol disponible ne produit pas de vitesse totale. Les sous-types réservés n'ajoutent pas de valeurs numériques.

Les deux messages publiés de référence sont 8D485020994409940838175B284F et 8DA05F219B06B6AF189400CBC33F. Les tests attendent respectivement −8/−159 kt, une route de 182,88° et −832 ft/min ; puis 375 kt TAS, un cap transmis de 243,984375° à référence non résolue et −2304 ft/min. L'exemple au sol donne 159,201130649 kt par norme du vecteur.

Dix tests supplémentaires couvrent ces références, les directions cardinales, les résolutions, les zéros et absences, les sources verticales, les limites de codage et les CRC. Un second import IQ synthétique dans Chromium vérifie l'affichage, le rapport JSON téléchargeable et le compteur de deux paquets. La capture adsb-velocity.png est conservée avec les artefacts navigateur.

Source des champs et exemples : [Airborne Velocity, The 1090 Megahertz Riddle](https://mode-s.org/1090mhz/content/ads-b/5-airborne-velocity.html). La distinction de référence du cap est recoupée avec le type HEADING_MAGNETIC_OR_TRUE de [dump1090](https://github.com/flightaware/dump1090/blob/master/mode_s.c). Les formules sont implémentées directement ; aucune bibliothèque tierce n'est intégrée. Les écarts d'altitude ne sont pas interprétés. Les catégories de précision sont traitées seulement dans les contextes décrits ci-dessous.

## Statut opérationnel et qualité déclarée

Les TC31 des versions ADS-B 1/2, sous-types aérien et surface, exposent les champs communs définis : version, NACp, SIL, référence de cap et compléments disponibles. Les catégories NACp reconnues fournissent leur borne horizontale à 95 %. Le SIL est conservé comme code avec sa base : par heure ou par échantillon en v2, non déterminée par ce message en v1. Zéro reste une information non renseignée ; les codes réservés ne reçoivent pas de borne numérique.

Ces informations décrivent ce que l'émetteur annonce, sans mesure indépendante de l'erreur ni garantie de navigation. Les indicateurs NIC complets, GVA et SDA ne sont pas calculés. Les blocs de capacités et de mode sont exportés comme codes bruts, sans prétendre en interpréter tous les bits.

Le code applique une politique locale explicite : seul un statut aérien décodé, du même DF/contrôle/adresse, antérieur ou simultané déjà observé et âgé de dix secondes au plus, peut préciser un TC19 ou une position suivante. Le statut n'est jamais propagé à une autre analyse. Un nouveau statut surface, réservé ou de version non prise en charge annule le contexte précédent. Un statut corrompu ou sans temps utilisable ne fournit aucun contexte. L'ordre chronologique est examiné sans changer l'ordre des trames exportées.

Le cap conserve son angle ; la référence devient vraie ou magnétique selon le statut. Il n'y a aucune conversion par déclinaison. Le code de qualité TC19 reste brut en l'absence de version connue ; avec ce contexte v1/v2, il fournit la catégorie NACv et, si elle est définie, la borne d'erreur horizontale en m/s à 95 %. Une position CPR calculée peut recevoir les catégories de son statut récent, avec preuve de provenance. Son calcul géographique reste indépendant de ces catégories.

Les objets operational_status, position_quality et velocity.operational_context sont facultatifs. Ce dernier contient version, hexadécimal, indice et instant source du statut, plus son âge. Ces temps sont relatifs à la capture. Sans contexte admissible, l'affichage du cap garde sa référence non déterminée. La fraîcheur maximale de dix secondes est une politique de cette implémentation, sans prétendre être une durée universelle imposée par le standard.

Onze tests supplémentaires vérifient l'encodage des champs et leurs bornes, les versions et sous-types exclus, la causalité, l'expiration, l'isolation des domaines et des analyses, l'absence de mutation et le chemin PPM complet. Le statut figé 8DA05F21F8000000005A3E4E0708 est synthétique : v2, NACp10, SIL3 par échantillon, cap magnétique. Les messages de vitesse et de position de référence sont réadressés ou complétés pour cette scène de test ; elle n'est pas présentée comme une capture RF réelle. Chromium vérifie les champs affichés et le rapport téléchargé ; adsb-operational-status.png est conservée dans ses artefacts.

Références des champs : [Aircraft Operation Status](https://mode-s.org/1090mhz/content/ads-b/6-operation-status.html), [Uncertainties](https://mode-s.org/1090mhz/content/ads-b/7-uncertainty.html), et la lecture des versions/références de [dump1090](https://github.com/flightaware/dump1090/blob/master/mode_s.c). Le décodeur utilise ses propres fonctions et ne dépend d'aucune de ces bibliothèques à l'exécution.
