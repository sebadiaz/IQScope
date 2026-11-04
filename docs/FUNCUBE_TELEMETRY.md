# Première interprétation de télémétrie FUNcube-1 FM

Après validation AO-40 FEC, IQScope peut interpréter une partie du paquet de 256 octets comme un profil FUNcube-1 Flight Model. L’en-tête est un indice de profil, pas une signature unique ni une authentification. L’interface indique donc **profil candidat** et l’export conserve `identity_confirmed: false`.

## Périmètre

Le premier octet donne l’identifiant de modèle et un code de type brut. Seul le modèle de vol FC1 (identifiant 2) est interprété. Le bloc temps réel commun couvre les 55 octets suivants. Le parseur extrait les huit mots EPS de 16 bits, le compteur logiciel de 24 bits, les indicateurs de validité des sous-systèmes et les indicateurs de mode. Les positions de bits sont absolues depuis le début du paquet, bit de poids fort d’abord.

Les valeurs électriques EPS sont transmises directement : tensions en mV, courants en mA. Les compteurs restent des comptes entiers. Les octets de température EPS restent des codes bruts sans unité attribuée ; les conversions ADC des autres cartes ne sont pas appliquées. Les 25 octets centraux non interprétés et les 200 octets de charge utile spécifique restent disponibles en hexadécimal, et le téléchargement binaire original conserve les 256 octets.

Chaque mesure exportée indique valeur brute, valeur affichée, unité, position/largeur et validité EPS déclarée. Une validité négative ne supprime pas les octets mais marque les valeurs comme non confirmées, éventuellement périmées. Une validité positive est l’affirmation du paquet : aucun contrôle indépendant des capteurs n’est réalisé. Le numéro de séquence n’est pas converti en date.

Le code de type est conservé sans lui attribuer un numéro ordinal WO/HR/FM : le document publié et des implémentations publiques emploient des conventions de numérotation différentes. Aucun assemblage de données d’orbite, de haute résolution ou de message n’est tenté ici. Les modèles d’ingénierie, FC2 et protocoles étendus ne sont pas interprétés.

## Sources et unités

- [Format de downlink FUNcube-1 « as flown »](https://funcube.org.uk/wp-content/uploads/2010/11/funcube-1-downlink-data-spec_ver1-as_flown.pdf) : ordre et largeur des champs, en-tête et drapeaux.
- [Équations publiées par le projet](https://funcube.org.uk/wp-content/uploads/2010/11/funcube-1_-telemetry_equations_b1.xls) : les valeurs EPS sont déjà transmises comme valeurs physiques. Copie consultée : 44 032 octets, SHA-256 `28b8ad4ac90c24b59ce031d2656654f80c5d3798ff7e6e2019723bd60d10d8cf`. La feuille de calcul porte un statut de travail ; elle n’est pas incorporée au paquet.
- [Unités du tableau de bord AMSAT-NL](https://amsat-nl.org/status/) : mV et mA pour l’alimentation.

Le parseur utilise ces informations de format ; aucun code de tableau de bord ou de gr-satellites n’est incorporé. Les sources sont citées dans le JSON. Aucune connexion externe ni transmission de télémétrie n’est effectuée par cette interprétation.

## Référence AO-73

Les 256 octets récupérés dans la référence audio donnent :

| Élément | Valeur |
| --- | ---: |
| En-tête brut | `0x89` |
| Identifiant de modèle | 2 |
| Code de type brut | 9 |
| Tension batterie | 8140 mV |
| Courant système | 206 mA |
| Redémarrages EPS | 721 |
| Séquence | 2543 |
| EPS déclaré valide | oui |
| Éclipse déclarée | oui |

Ces valeurs sont des interprétations de données de développement, sans confirmation indépendante de l’état physique du satellite. La validation FEC reste distincte de cette couche sémantique et n’est pas renommée CRC.

L’interface montre les mesures et propose `funcube-telemetry-N.json`, en plus de la charge utile binaire et du rapport AO-40. La télémétrie partielle est également incluse dans les rapports complets d’analyses audio et IQ.

Les tests utilisent des paquets synthétiques construits à des positions indépendantes du lecteur, avec des bits de validité isolés et des codes non convertis. Un vecteur de régression issu du paquet radio FEC complète ces cas, avec provenance explicite. Le contrôle de corpus et Chromium vérifient les valeurs et le JSON téléchargé. Cela ne constitue pas une validation générale de tous les profils FUNcube.
