# Indicatifs et positions ADS-B

IQScope complète l'extraction de contenu des trames Mode S déjà reçues : indicatif de vol et coordonnées aériennes apparaissent dans l'interface et le rapport JSON. Le nouveau module n'ajoute aucun moteur externe ni téléchargement au moment de l'analyse.

## Périmètre

Le démodulateur PPM conserve son traitement et ses budgets : entrée d'au moins 2 Méch/s, grille d'énergie à 8 Méch/s, recherche de 2 000 candidats et 100 paquets par défaut. Les champs supplémentaires sont interprétés après contrôle CRC-24. Les DF17 et DF18 restent des paquets conservés ; les nouveaux champs sont limités aux DF17 et DF18 CF0/1, où le corps ADS-B utilisé ici est applicable. Les autres contrôles DF18 conservent leurs octets et leur note de sémantique d'adresse, sans identification ou coordonnées supposées.

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

Aucun décodage de position au sol, de CPR local sur une référence géographique, de position GNSS TC20–22, de vitesse ou de trajectoire entre analyses n'est ajouté. Une capture trop courte pour contenir une paire peut livrer des paquets et une altitude sans coordonnées. Les collisions et corrections de bits restent hors périmètre du récepteur.

Un CRC valide vérifie les bits du paquet, sans authentifier la station ni garantir la véracité, l'intégrité de navigation ou la précision de sa position. Les valeurs de qualité NIC/NAC/SIL ne sont pas encore interprétées. Les DF18 ne sont pas automatiquement étiquetés ICAO.

Sources des formats et valeurs de référence : [Aircraft Identification](https://mode-s.org/1090mhz/content/ads-b/2-identification.html) et [Airborne Position](https://mode-s.org/1090mhz/content/ads-b/3-airborne-position.html), The 1090 Megahertz Riddle, Junzi Sun. Les formules sont implémentées directement, sans reprise d'une bibliothèque de décodage tierce.
