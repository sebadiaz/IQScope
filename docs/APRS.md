# APRS : positions de stations non compressées et base 91

IQScope interprète automatiquement un premier profil APRS dans les charges
utiles AX.25 UI de PID `0xf0`. Les trames doivent déjà avoir passé le contrôle
CRC-16/X-25 et les vérifications de structure du décodeur englobant. La fonction
`parse_aprs_position` seule est un lecteur de syntaxe, pas un contrôle de trame.

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
- Mic-E, objets/items, encapsulations tierces, NMEA,
  télémétrie, météo détaillée et extensions supplémentaires ne sont pas encore
  interprétés. Leurs charges utiles AX.25 restent exportables ; un format non
  pris en charge n’est pas présenté comme une position décodée.
- Les limites et pertes possibles des récepteurs AX.25 restent applicables.
  Ce lecteur, borné à 256 octets, ne restaure aucun bit perdu ou mal reçu et
  ne réalise pas de suivi entre fenêtres en temps réel.

## Référence et vérifications

Référence primaire : [APRS Protocol Reference v1.0.1, APRS Working Group/TAPR](https://www.aprs.org/doc/APRS101.PDF),
chapitres 6–9 et 20. Le profil ci-dessus est volontairement limité ; cette référence
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
