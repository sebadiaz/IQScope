# Réception automatique POCSAG

L'analyse IQ par fichier et par instantané SDR applique désormais un parseur
POCSAG aux candidats de la chaîne 2-FSK. Il fournit les adresses numériques
« capcodes », les fonctions, le texte ou les chiffres et les mots reçus. Aucun
réglage de polarité, de phase de mot ou de débit n'est demandé à l'utilisateur.

## Format et contrôle

Le format est celui de l'annexe 1 de la
[recommandation UIT-R M.584-2](https://www.itu.int/rec/R-REC-M.584-2-199711-I/en).
La synchronisation exacte `7CD215D8` ouvre un lot de seize mots. Les trois bits
bas de l'identité dépendent de la position de l'adresse dans ses huit groupes,
et non de trois bits supplémentaires dans le mot d'adresse. Chaque mot de
contenu porte vingt bits. Un message peut traverser des lots ; la synchronisation
suivante doit alors apparaître à l'emplacement attendu, après 544 bits.

Les mots d'adresse, de données et de terminaison doivent satisfaire le
BCH(31,21), de générateur x¹⁰+x⁹+x⁸+x⁶+x⁵+x³+1, et la parité paire du mot complet.
Il n'y a **aucune correction d'erreur** dans cette première version. Un mot
corrompu ou une rupture de synchronisation abandonne le message ouvert.
L'adresse ou l'idle suivant termine le message ; une fin de capture n'est pas
interprétée comme une terminaison. Des messages indépendants suivants peuvent
encore être reçus. Les répétitions sont conservées.

La fonction 0 sélectionne le format numérique standard, avec quatre bits par
caractère ; la fonction 3 sélectionne IA5/ASCII de base, avec sept bits par
caractère et continuité entre mots. Les caractères arrivent bit faible en
premier. Le code numérique réservé reste marqué et conservé brut ; les espaces
finaux sont préservés. Les fonctions 1/2 gardent leurs bits sans texte supposé.
Un appel sans données est distingué d'un message texte vide.

## Rapport et interface

L'essai `pocsag` apparaît dans `wideband_trials`. Chaque élément de `messages`
contient les champs interprétés, les bits utiles, les mots hexadécimaux, le
terminateur, les indices de synchronisation, la polarité et le canal source.
Le temps correspond au centre du premier bit d'adresse, relativement à la
capture. Les fréquences viennent du canal IQ, sans déduire un réseau du capcode.
Les interprétations ASCII conservent les codes et les éventuels bits de queue.

L'interface affiche une section POCSAG et permet de télécharger
`pocsag-messages.json`. Les caractères sont insérés comme texte, y compris les
chevrons. Le compteur de trames à CRC n'augmente pas : BCH/parité constituent
ici des contrôles différents, sans authentification de l'émetteur.

## Bornes et validation

Le parseur accepte les débits estimés à ±3 % de 512, 1 200 ou 2 400 bauds, dans
les deux polarités. Les limites par analyse sont de huit candidats, 100 000 bits
par candidat, 128 synchronisations, 8 192 mots examinés, 128 mots par message
et 64 messages. Les limites et les rejets sont exposés dans le rapport.
La démodulation conserve les limites de la chaîne 2-FSK : signaux stationnaires,
douze secondes au plus, recherche directe ou canaux détectés de 24 kHz au plus.
Elle peut manquer les salves courtes, collisions et bandes regroupées avec leurs
lobes. Aucun état ne traverse deux analyses ou instantanés.

Quatorze tests vérifient notamment les mots de synchronisation/idle publiés,
un encodeur polynomial indépendant, les huit groupes d'adresse, les deux
polarités et les trois débits, les changements de lot, les caractères et les
erreurs d'un ou deux bits, les limites et les exports. Une scène synthétique
filtrée à 192 kéch/s vérifie la découverte du canal malgré une porteuse plus
forte. Un autre test importe les IQ dans Chromium, contrôle le texte et les
chiffres, télécharge le JSON et vérifie l'absence d'interprétation HTML.

Ces références sont **synthétiques**. Aucun enregistrement RF POCSAG indépendant
n'a encore été validé. La correction BCH, les alphabets nationaux, les formats
propriétaires, le frontal audio FM, FLEX/ERMES et la continuité entre instantanés
restent à réaliser.
