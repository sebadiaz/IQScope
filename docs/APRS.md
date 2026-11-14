# APRS : positions, objets, items et télémétrie

IQScope interprète automatiquement un premier profil APRS dans les charges
utiles AX.25 UI de PID `0xf0`. Les trames doivent déjà avoir passé le contrôle
CRC-16/X-25 et les vérifications de structure du décodeur englobant. La fonction
`parse_aprs_position` et `parse_aprs_telemetry` lisent des syntaxes ; ces fonctions
seules ne contrôlent pas les trames. `parse_aprs_definition` lit les définitions ;
`enrich_aprs_telemetry_frames` associe les déclarations sous conditions explicites.

Le même lecteur sert aux trois chemins existants : bits 2-FSK issus d’IQ,
audio de récepteur AFSK1200 et BPSK avec débrassage G3RUH
(descrambling). Il n’ajoute ni essai DSP ni trame au compteur CRC. Les octets,
le texte, les temps et les fréquences du décodeur d’origine restent conservés.
Un fichier audio ne fournit toujours aucun centre RF.

## Profil actuellement extrait

| Champ reçu | Sortie |
| --- | --- |
| Position de station `!`, `=`, `/` ou `@`, non compressée ou base 91 | Latitude/longitude signées en degrés, coordonnées reçues, table et code de symbole |
| Horodatage `DDHHMMz`, `DDHHMM/` ou `HHMMSSh` | Composants et référence UTC ou heure locale de fuseau inconnu ; aucune date complète ni époque inventée |
| Extension initiale `ccc/sss` reconnue | Route de 1 à 360 degrés depuis le nord, vitesse en nœuds et m/s |
| Une annotation `/A=` suivie de six chiffres non signés | Altitude en pieds et mètres ; référence verticale non déterminée |
| Objet `;` ou item `)` ponctuel | Nom exact, état déclaré actif/retiré, coordonnées non compressées ou base 91 pour les annonces actives |
| Télémétrie classique `T#`, séquence numérique ou `MIC` | Cinq valeurs brutes 0–255, huit bits reçus et définitions antérieures éligibles avec provenance |
| Télémétrie base 91 dans un commentaire de position de station | Compteur, un à cinq canaux bruts 0–8280 et, si présent, mot binaire avec B1 au poids faible |

Les champs interprétés sont ajoutés à `frame.fields.aprs`, dans les rapports
JSON existants. L’interface affiche les valeurs reconnues et garde le texte
reçu via `textContent`, y compris les caractères ressemblant à du HTML.
L’indication de messagerie est une capacité déclarée par le paquet.

La résolution numérique du format non compressé est de 0,01 minute d’arc. Elle n’est pas une
mesure d’exactitude. Le datum du protocole est étiqueté WGS84 par défaut, sans
vérification indépendante. CRC, position déclarée et identité de l’émetteur
restent des notions distinctes.

## Abstentions et limites

- Les blancs d’ambiguïté en fin de minutes de latitude suppriment **les deux**
  coordonnées numériques, même si tous les chiffres de longitude sont présents.
  Les nombres de blancs incohérents et les coordonnées hors limites sont refusés.
  Aucune région ni coordonnée centrale n’est encore calculée.
- La position nulle standard `0000.00N\00000.00W.` est signalée inconnue. Les
  coordonnées ordinaires réellement encodées à zéro restent des valeurs valides.
- Les extensions de mouvement inconnues (`000/000`, points ou blancs) ne
  deviennent pas une vitesse nulle. `360/000` reste une route nord et une vitesse
  réellement encodée à zéro. Les symboles météo et radiogoniométriques ne
  produisent pas de vitesse de véhicule à partir de leur syntaxe ressemblante.
- Plusieurs annotations d’altitude, les valeurs signées ou un nombre de
  chiffres différent restent bruts. Aucun choix arbitraire entre annotations.
- Mic-E, géométrie des objets de zone, encapsulations tierces, NMEA,
  télémétrie décimale étendue, météo détaillée et extensions supplémentaires ne sont pas encore
  interprétés. Leurs charges utiles AX.25 restent exportables ; un format non
  pris en charge n’est pas présenté comme une position décodée.
- Les limites et pertes possibles des récepteurs AX.25 restent applicables.
  Ce lecteur, borné à 256 octets, ne restaure aucun bit perdu ou mal reçu et
  ne réalise pas de suivi entre fenêtres en temps réel.

## Référence et vérifications

Référence primaire : [APRS Protocol Reference v1.0.1, APRS Working Group/TAPR](https://www.aprs.org/doc/APRS101.PDF),
chapitres 6–9, 11, 13–14 et 20. Le profil ci-dessus est volontairement limité ; cette référence
ne constitue pas une déclaration de conformité APRS complète.

`tests/test_aprs.py` vérifie les exemples de syntaxe publiés, les quatre
identifiants, les unités, les bornes, les ambiguïtés, la position nulle et les
horodatages incomplets. Les cas négatifs couvrent aussi le mauvais PID, le CRC
corrompu, les symboles météo/DF et les annotations contradictoires. Les chemins
IQ 2-FSK, audio AFSK1200, import WAV/JSON et bits BPSK/G3RUH utilisent des trames
synthétiques avec FCS généré indépendamment du décodeur. Le test Chromium
importe le WAV, vérifie les valeurs et les exports, puis les abstentions
ambiguë/nulle et l’affichage littéral du texte.

Il manque encore un enregistrement APRS indépendant avec position attendue
vérifiable. Les captures satellitaires BPSK existantes valident leur propre
chaîne AX.25, pas ce nouveau profil APRS.

## Ajout du format compressé

Le bloc base 91 de treize octets fournit aussi les coordonnées et les symboles,
avec surimpressions numériques `a–j` conservées et traduites. L'indicateur `T`
sépare route/vitesse, altitude et portée radio déclarée. Un `c` espace ignore
les deux octets suivants ; un indicateur invalide conserve la position valide
mais ne produit aucune extension numérique. Les pas de quantification propres
aux deux axes restent dans le JSON ; l'affichage n'invente pas de précision GPS.
Le statut courant/ancien et la source NMEA sont des déclarations, sans âge déduit.

Les annotations textuelles d'altitude restent interprétables séparément.
En présence d'une altitude compressée et d'une annotation, les candidats sont
conservés mais aucune altitude principale n'est sélectionnée, même si l'une
des annotations est mal formée. La portée radio ne constitue pas une mesure
de réception. La position nulle reste sans point, dans les deux formats.

`tests/test_aprs_compressed.py` ajoute les exemples publiés, les valeurs zéro,
les bornes, surimpressions, caractères et types invalides, conflits d'altitude
et chemins IQ/audio/BPSK. Chromium vérifie le WAV, l'export et les affichages
distincts de mouvement, altitude, portée et conflit. Ces références restent
synthétiques ; aucun nouvel enregistrement RF indépendant n'est revendiqué.

## Objets et items ponctuels

Le nom de l'objet occupe neuf caractères ASCII imprimables ; celui de l'item
en occupe trois à neuf. Casse, espaces et octets reçus restent conservés.
L'objet exige un horodatage partiel valide ; l'item n'en fournit pas.
Les marqueurs actif/retrait sont interprétés selon le type de rapport.

`fields.aprs.entity` contient `kind`, `name`, `name_hex`, `marker` et
`state_reported`. `position_subject: named_entity` indique que la position
concerne le point nommé. Les coordonnées de l'émetteur ne sont pas déduites
de celles de l'objet ; l'adresse source reste dans les champs AX.25 existants.
Aucune capacité de messagerie n'est inventée par la réutilisation du lecteur
de position. Les coordonnées ambiguës/nulles gardent leur abstention.

Un retrait dont le corps est reconnu porte le statut `retracted_entity`.
Les octets du corps, son format et son statut restent exportés, avec le nom
et l'horodatage éventuel, mais aucune coordonnée active, vitesse ou altitude.
Un corps non reconnu porte `unresolved_entity_retraction`. L'interface affiche
l'annonce de retrait ; aucun autre rapport n'est supprimé ou remplacé.
Il n'existe pas encore de registre interfenêtres des objets courants.
L'identité de l'annonceur et son autorité sur le nom ne sont pas authentifiées.

Les objets de zone restent sans point ni vitesse de véhicule déduite : le
profil ne décode pas encore leur forme, couleur ou étendue. Les panneaux et
autres extensions spécialisées ne reçoivent pas de nouvelle interprétation.
Quinze tests supplémentaires vérifient ces règles, les chemins IQ/audio/BPSK
et les exports WAV/JSON. Chromium vérifie objets/items actifs et retirés,
le compteur CRC et l'affichage littéral des noms ressemblant à du HTML.
La validation sur un enregistrement APRS indépendant reste à réaliser.

## Télémétrie classique T# : valeurs brutes

Le lecteur accepte une séquence décimale à trois chiffres ou `MIC`, cinq
canaux analogiques décimaux à trois chiffres dans 0–255, puis huit caractères
binaires. La virgule après `MIC` peut être absente. Les zéros restent des
valeurs, les champs manquants ne deviennent pas des zéros. Les commentaires
et leurs octets sont conservés, y compris s'ils commencent par un chiffre.

Un rapport reconnu porte `status: decoded_telemetry` et un champ `telemetry` :

- `sequence` conserve la chaîne et, pour un compteur numérique, sa valeur.
  `MIC` ne reçoit aucun compteur inventé ; aucun taux de perte n'est calculé.
- `analog_raw` contient A1–A5, dans l'ordre reçu.
- `digital_raw` et `digital_bits` conservent B1–B8 de gauche à droite.
  Un bit 1 n'est pas déclaré « actif » : sa polarité peut dépendre du projet.
- `comment` et `comment_hex` conservent le commentaire ; le texte d'origine
  et `payload_hex` restent dans les champs AX.25.

L'interface conserve ces numéros et valeurs brutes. Les définitions éligibles
peuvent ajouter des interprétations déclarées, selon les règles ci-dessous.
Le lecteur de syntaxe seul n'applique aucune définition. Cette étape n'introduit
pas de registre interfenêtres.

Les variantes T# étendues, valeurs signées/flottantes, champs raccourcis ou
incomplets restent hors profil. Un corps non interprété ne fait pas perdre la
trame à FCS valide et n'expose aucune mesure partielle. L'intégrité du paquet
reste distincte de la véracité d'une mesure et de l'identité de son émetteur.

Quinze tests vérifient les exemples publiés, les bornes, le format MIC, les
bits, commentaires, refus, CRC/PID et chemins IQ/audio/BPSK. Chromium vérifie
les imports WAV, l'affichage sûr, le compteur CRC et l'export JSON. La validation
actuelle utilise des références synthétiques ; un enregistrement APRS
indépendant reste à intégrer.

## Définitions et interprétation déclarée

Les messages `PARM.`, `UNIT.`, `EQNS.` et `BITS.` sont lus avec leur adresse
fixe, leurs données et l'identifiant de message éventuel. Les noms/unités
conservent les champs vides et les limites de largeur du profil classique.
Une équation exige trois coefficients explicites pour produire une valeur :
`a*v*v + b*v + c`. Les bits sont comparés au sens transmis ; une correspondance
porte sur l'étiquette déclarée, pas sur une notion universelle d'entrée active.

L'association automatique est une politique prudente d'IQScope :

- Même source et SSID, même frontend et même canal. Sans fréquence connue,
  l'indice du candidat distingue les flux. Seules les définitions adressées
  à la source elle-même sont utilisées ; les annonces tierces restent lisibles.
- La trame de définition doit avoir une FCS valide et être entièrement reçue
  **avant** le premier centre de symbole de la mesure. `time_end_seconds`
  correspond à la fin du symbole du dernier bit du fanion de fermeture ;
  deux paquets peuvent donc partager ce fanion sans perdre l'association.
  Aucune définition future, simultanée ou temporellement indéterminée n'est
  utilisée comme nouvelle définition de la mesure.
- Chaque type expire séparément après 600 secondes par défaut. C'est une
  limite d'implémentation, pas une durée imposée par APRS. Le lecteur public
  accepte un budget fini de 0 à 3600 secondes ; les voies automatiques utilisent 600.
- Le dernier message d'un type remplace ses champs ; les champs manquants ne
  reprennent pas ceux d'un ancien message. Un remplacement mal formé bloque
  l'ancien type. Des définitions différentes finissant exactement au même
  instant restent en conflit jusqu'à une nouvelle annonce ultérieure.
- Le contexte est local à l'essai. Les phases AFSK sont réassociées après
  déduplication et les trames BPSK après ajustement de leurs références. Aucun
  contexte ne traverse une fenêtre ou un nouvel appel d'analyse.

Les sorties `analog_channels`, `digital_channels` et `definition_context`
complètent `telemetry` sans modifier `analog_raw`, `digital_raw` ou les octets
du paquet. Chaque type retenu renvoie à l'indice, aux octets, à la fin de
réception et à l'âge de sa trame. Noms, unités et coefficients peuvent être
disponibles indépendamment. Une unité seule ne calibre pas une valeur brute.
Un résultat non fini n'est jamais exporté comme valeur numérique.

Exemple de portée des unités : une valeur calculée de 1034,8 avec l'étiquette
`v/100` reste **1034,8 v/100** ; IQScope ne la transforme pas implicitement
en volts. Les coefficients et étiquettes sont des déclarations non authentifiées,
pas une calibration de capteur vérifiée indépendamment.

Vingt tests supplémentaires couvrent syntaxe publiée, causalité, isolement,
expiration, remplacements, conflits, idempotence, données brutes et débordement,
puis les voies IQ/audio/BPSK et WAV/JSON. Chromium vérifie l'interprétation, la
provenance et le refus d'associer des définitions adressées à une autre station.
La validation APRS sur enregistrement indépendant reste à réaliser.

## Télémétrie base 91 dans les commentaires de position

Référence primaire : [spécification de Heikki Hannikainen, OH7LZB, 2012-01-11](https://github.com/hessu/aprs-specs/blob/master/aprs-base91-comment-telemetry.txt).
Le profil accepte un unique bloc `|…|` dans le commentaire d'une position de
station non compressée ou compressée. Deux caractères codent chaque valeur :
d'abord le compteur, puis un à cinq canaux analogiques. Un septième couple
code le mot binaire. La plage codée est 0–8280 ; elle n'établit pas la résolution
réelle d'un capteur et aucune valeur 8 bits n'est artificiellement agrandie.

Le résultat complète `fields.aprs.telemetry` avec `encoding: base91_comment`.
Le statut et les coordonnées de position restent présents, sans trame ni CRC
supplémentaire. La télémétrie peut être lue avec une position ambiguë ou nulle,
sans inventer de coordonnées. Les formats de position non interprétés, Mic-E
et les commentaires d'objets/items ne reçoivent pas cette nouvelle extraction.

Les canaux absents restent absents. Sans septième couple, `digital_status`
vaut `not_transmitted` et aucun bit binaire n'est inventé. Sinon :

- `digital_word_raw` conserve l'entier complet et `digital_wire_hex` ses deux
  octets encodés ; `digital_reserved_value` conserve sa partie au-dessus de B8.
- `digital_bits` et `digital_raw` sont en ordre **canonique B1–B8**, obtenu du
  poids faible au poids fort. Ce n'est pas l'ordre d'affichage binaire MSB-first
  d'un entier. Aucun canal B9 ou suivant n'est déduit des bits réservés.
- `sequence` conserve les deux caractères et le compteur numérique. Aucun
  enroulement particulier, débit ou taux de perte n'est supposé.

Le commentaire original, son hexadécimal et les octets du bloc restent
conservés. `extension_span` exprime des offsets **en octets du commentaire**.
Plusieurs séparateurs, couples invalides ou tailles hors profil ne produisent
aucune valeur partielle ; la position peut rester interprétable. Après le bloc,
seule une fin vide ou une syntaxe DAO `!Wdd!`/`!wxx!` est reconnue et conservée,
sans affiner les coordonnées. Les autres suffixes restent hors profil.

Les octets entre séparateurs ne sont pas lus comme des annotations d'altitude,
même s'ils ressemblent à `/A=…`. Le masquage conserve les séparations : retirer
le bloc ne doit pas fabriquer une annotation entre deux morceaux de texte.
Une syntaxe DAO ressemblante à l'intérieur du bloc ne modifie pas la position.

La même association de définitions PARM/UNIT/EQNS/BITS reste applicable, avec
les mêmes contraintes de source/SSID, canal, frontend, temps et fenêtre.
Les calculs n'ajoutent pas les canaux manquants et l'ordre B1–B8 est conservé
avant de comparer les bits au sens déclaré. Les unités ne sont pas converties
implicitement et les valeurs brutes restent exportées.

Dix-huit tests supplémentaires couvrent les exemples publiés, bornes, bits,
octets, abstentions, annotations concurrentes, CRC/PID et voies IQ/audio/BPSK,
puis WAV/JSON. Chromium vérifie position et télémétrie simultanées, données
minimales, sens B1, calculs et maintien du compteur CRC. La validation sur un
enregistrement APRS indépendant reste à réaliser.
