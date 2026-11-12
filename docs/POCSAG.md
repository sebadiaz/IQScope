# Réception automatique POCSAG

L'analyse IQ par fichier et par instantané SDR applique un parseur
POCSAG aux candidats de la chaîne 2-FSK. L'import audio dispose également d'un
frontal pour les niveaux issus d'un récepteur FM démodulé. Le parseur fournit les adresses numériques
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
Une correction bornée à **deux bits sur le message complet** est disponible,
comme décrit ci-dessous. Un mot non corrigeable ou une rupture de synchronisation
abandonne le message ouvert.
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

Les références IQ ci-dessus sont **synthétiques**. Les alphabets
nationaux, les formats propriétaires, FLEX/ERMES et la continuité entre instantanés
restent à réaliser. La validation audio indépendante suivante ne fournit pas les
IQ RF d'origine.

## Correction BCH bornée et conservation des mots reçus

Le code BCH(31,21) est complété par sa parité paire. Le décodeur calcule un
syndrome composé des dix bits de reste polynomial et de cette parité. Une table
de 529 masques couvre zéro, une ou deux inversions parmi les 32 positions ; la
construction exige des syndromes distincts. Le mot proposé est contrôlé à
nouveau après correction. La synchronisation de lot reste toujours exacte :
elle n'utilise pas cette table.

Par défaut, **la somme des corrections d'adresse, de données et de terminaison
ne dépasse pas deux bits**. Deux mots ayant chacun deux erreurs font donc
refuser le message. Un mot d'adresse peut terminer un message et ouvrir le
suivant ; sa preuve apparaît dans chacun des messages concernés, selon son rôle.
Il n'existe pas de compteur global additionnant ces preuves comme autant de
bits physiques distincts. Le paramètre `max_corrected_bits=0` sélectionne le
contrôle strict, et la valeur 1 limite la somme à un seul bit.

`codewords_hex` et `terminator_hex` conservent les mots récupérés, après choix de
polarité et avant correction. `decoded_codewords_hex` et
`decoded_terminator_hex` contiennent ceux utilisés pour les champs interprétés.
La liste `corrections` précise rôle, indice de bit dans le candidat, deux mots
hexadécimaux et positions changées, numérotées de 1 (bit fort) à 32 (parité).
`received_bch_parity_valid` distingue les mots reçus déjà valides ;
`validation_stage` indique si une correction a été appliquée. `bch_valid` et
`even_parity_valid` portent sur les mots finalement utilisés. L'interface affiche
le nombre de bits corrigés et laisse le compteur CRC inchangé.

La décision choisit un mot valide dans un rayon de deux bits. Quand davantage
d'erreurs se produisent, un autre mot valide peut se trouver dans ce rayon : ce
contrôle ne prouve donc pas la valeur initialement émise. La limite globale et
la synchronisation exacte restent nécessaires ; aucun CRC ou mécanisme
d'authentification supplémentaire n'est introduit.

Huit tests supplémentaires couvrent 2 112 injections d'une ou deux erreurs sur
quatre mots de référence, puis 14 880 injections de trois erreurs sur trois mots
(toutes refusées). Ils vérifient également la limite globale, les trois rôles,
les sources conservées, l'adresse partagée entre messages, le mode strict et la
récupération automatique sur IQ et audio synthétiques. Un test Chromium est
préparé pour le texte corrigé, l'indication de deux bits, le compteur CRC et les
deux mots distincts dans le JSON. Les huit captures audio indépendantes restent
des références sans correction : elles ne démontrent pas un gain sur signal
radio corrompu.

## Audio FM démodulé et références indépendantes

Le mode **Audio de récepteur** essaie automatiquement POCSAG sur les niveaux du
WAV/MP3 décodé en mono à 8 kHz. Il ajuste une horloge à partir des transitions
pour chacun des trois débits standard ; seules les hypothèses à ±3 % et à résidu
RMS inférieur ou égal à 0,15 symbole sont retenues. Les contrôles de lot,
BCH/parité et terminaison restent ensuite nécessaires pour publier un message.
Un alias d'horloge seul ne fournit donc pas de contenu. Les fréquences RF et les
caractéristiques I/Q ne sont pas reconstruites depuis cet audio.

Le frontal est borné à vingt secondes et 50 000 transitions. Il ajuste une
horloge globale dans la fenêtre, sans recherche de salves ni suivi adaptatif du
seuil. Un enregistrement trop silencieux, déformé, compressé ou discontinu peut
être refusé. Huit nouveaux tests vérifient débits et polarités, écarts d'horloge,
contenu numérique, erreur BCH, bruits/tons/AFSK négatifs, fenêtres séparées,
bornes, import WAV et export JSON. Les tests IQ existants restent distincts.

Le corpus [POCSAG-Decoder de Rob Ruark](https://github.com/rrruark/POCSAG-Decoder/tree/9c484c54d8afcde5357e1c170df43a865ac2bf7a)
apporte huit captures de laboratoire : transmissions de test RadioLib,
enregistrement GQRX, puis filtrage et découpage par l'auteur. Leur format est du
WAV mono à 48 kHz ; le chemin d'import habituel réalise le rééchantillonnage.
Chaque fichier fournit un message à contrôles BCH/parité valides, sans
correction, vers les capcodes 1100000–1100005, 1100007 et 1100008. Le débit
estimé est proche de 1 199,1 bauds. Cela valide ces captures audio préparées à
1 200 bauds, sans généraliser aux réseaux en service ou à tous les récepteurs.

La phrase de démonstration et le capcode 1100004 figurent dans le README de
l'auteur. Les sorties par fichier servent de régressions de développement.
`pager_addr5.wav` et `pager_addr7.wav` donnent des textes plus courts, terminés
respectivement par « couple fram » et « span a » : leurs bits reçus et leurs
terminateurs sont conservés. Le banc ne remplace pas ces sorties par la phrase
plus longue attendue dans les autres fichiers.

Le script télécharge les sources au commit figé, vérifie taille et SHA-256 avant
analyse et conserve rapports et provenance :

```sh
python scripts/pocsag_radio_reference.py
# Réutiliser les mêmes sources, avec nouvelle vérification des empreintes :
python scripts/pocsag_radio_reference.py --offline
```

La CI exécute ce banc et importe une de ces captures dans Chromium, vérifie le
texte, l'absence de centre RF, le compteur CRC et les JSON téléchargeables. Elle
archive `pocsag-radio.png`, les rapports et leurs provenances dans
`browser-checks`. Les sources restent liées à la
[licence MIT du corpus](https://github.com/rrruark/POCSAG-Decoder/blob/9c484c54d8afcde5357e1c170df43a865ac2bf7a/LICENSE).
