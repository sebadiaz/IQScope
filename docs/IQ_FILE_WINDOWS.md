# Fenêtres positionnées dans un fichier IQ

Le mode Fichier permet de choisir **Début dans le fichier**, puis d'analyser
la durée demandée. Les boutons **Fenêtre précédente** et **Fenêtre suivante**
parcourent ensuite le fichier avec des indices d'échantillons entiers, sans
recalculer la position par arrondis successifs en secondes.

La lecture effectue un seek vers les données utiles. Les échantillons précédents
ne sont pas chargés par le lecteur DSP. Chaque fenêtre conserve la limite de
huit millions d'échantillons ; le dernier segment peut être plus court. Si le
reste est inférieur au minimum de 1 024 échantillons, Suivante est désactivé
et le nombre d'échantillons restants demeure affiché.

Formats : cf32 brut, les cinq représentations SigMF déjà prises en charge,
WAV/RF64 stéréo PCM ou flottant, et SDRangel `.sdriq` avec contrôle d'en-tête.
Les métadonnées du fichier restent la source du débit et du centre RF quand
elles existent. Aucune fréquence n'est déduite d'un nom de fichier.

## Commande et API

```bash
iqscope analyze enregistrement.wav --start-seconds 120 --seconds 10 --out extrait-120s
```

`POST /api/analyses` accepte `start_seconds` (défaut 0), ou `start_sample`
entier exact pour la navigation. Les deux ne peuvent pas être fournis avec
un temps de départ non nul. La sélection par temps est arrondie vers le bas
au premier indice d'échantillon. Les valeurs invalides ou trop proches de la
fin pour fournir 1 024 échantillons sont refusées. Audio MP3/WAV et démo ne
prennent pas en charge ce déplacement.

## Temps et provenance

`report.json` conserve `source_sample_start`, `source_sample_end` exclusif,
`source_sample_reference: original_file_complex_samples`, et `source_window` :
positions entières, temps source, taille totale, durée demandée, limite de
fenêtre et positions de navigation. Le début demandé en secondes reste
distinct du début effectivement lu.

Les temps des décodeurs restent relatifs au début de leur fenêtre. Pour les
placer dans le fichier, ajouter `source_window.start_seconds`. Les JSON qui
exportent un essai complet reçoivent également `source_window_reference`,
afin de conserver cette origine avec les octets décodés. Les indices internes
et diagnostics de synchronisation ne sont pas artificiellement décalés.
L'interface affiche la plage source et cette convention de temps.

## Validation et limites

Les tests couvrent les formats, les offsets binaires, le non-chargement du
préfixe, les limites de mémoire, les fins de fichier, la commande et l'API.
Une capture synthétique contient des paquets après 12 s : ils sont retrouvés
par accès direct à cet instant, avec FCS et temps source vérifiés.

Sur le WAV IQ épinglé de 18,799 s, la fenêtre commençant à 10 s va de l'indice
390 620 à 734 328 et retrouve les deux dernières trames attendues. Chromium
parcourt les fenêtres dans les deux sens, vérifie les indices source et le
JSON exporté. Ces octets restent des références de développement, sans total
indépendant de paquets fourni par l'auteur.

Cette navigation est manuelle et les fenêtres suivantes sont adjacentes,
sans recouvrement automatique : une trame coupée peut nécessiter un autre
point de départ. Il n'y a pas de reconstruction d'état entre fenêtres. Un
[parcours automatique borné](IQ_FILE_SCAN.md) est disponible séparément. Les limites propres aux
décodeurs restent applicables à chaque fenêtre. Le CLI peut lire un grand
fichier local ; l'interface garde sa limite d'import de 128 Mio et réimporte
le fichier à chaque analyse. Le seek DSP ne supprime pas ce transfert initial.
