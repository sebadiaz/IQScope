# Dataset imec / UGent sub-GHz : identification et plan d'intégration

État au 25 octobre 2026 : documentation identifiée ; fichiers du partage non inspectés. Ce document ne revendique aucun import ni décodage validé sur ce dataset.

## Provenance établie

Le [dépôt des auteurs](https://github.com/JaronFontaine/Sub-GHz-IQ-signals-dataset) renvoie explicitement au [partage fourni](https://cloud.ilabt.imec.be/index.php/s/bqXtdp9QsfXLbb3). Il présente des captures pour la reconnaissance de technologies sub-GHz, comprenant LoRa, Sigfox, SUN-FSK, SUN-OFDM, IEEE 802.11ah et du bruit.

Référence demandée par les auteurs : Fontaine et al., *Multi-band sub-GHz technology recognition on NVIDIA’s Jetson Nano*, VTC2020-Fall, DOI [10.1109/VTC2020-Fall49728.2020.9348566](https://doi.org/10.1109/VTC2020-Fall49728.2020.9348566). [Notice et manuscrit UGent](https://biblio.ugent.be/publication/8683397).

Le manifeste [imec-subghz.json](../corpus/imec-subghz.json) sépare les paramètres publiés des métadonnées de fichiers encore inconnues. Aucun identifiant numérique de classe n'a été inventé.

## Intérêt pour IQScope

SDRangel fournit déjà un premier contrôle d'import et de décodage. Ce nouveau corpus permettra surtout d'évaluer la sélection des familles et la bonne abstention sur le bruit. Des mesures avec câbles ne couvrent pas à elles seules la diversité d'une réception radio en environnement réel.

Le taux publié est de 2,048 Méch/s. Les accords de réception sont distincts des fréquences des émetteurs : ne pas attribuer la fréquence d'un signal à toute la capture. Le montage à plusieurs récepteurs ne garantit pas leur cohérence de phase.

## Vérification indispensable avant import

Le manuscrit décrit des fichiers compatibles MATLAB et des exemples de classification IQ ou FFT. Cela ne confirme ni l'extension effectivement distribuée, ni les noms de variables, ni les types numériques.

Le traitement décrit utilise des fenêtres de 500 échantillons complexes, environ 244 µs au taux indiqué. Une telle fenêtre n'est pas une trame protocolaire et peut être trop courte pour retrouver un paquet complet. On ne doit pas reconstruire une continuité temporelle en concaténant des exemples indépendants. Une FFT ou une représentation normalisée doit également être identifiée comme telle.

Inspection à réaliser :

1. Lister les fichiers, tailles, formats et documents fournis, sans télécharger tout le partage.
2. Vérifier un petit fichier de chaque famille : dimensions, types, champs IQ, étiquettes et accord du récepteur.
3. Distinguer captures continues, fenêtres indépendantes et données transformées.
4. Vérifier l'ordre I/Q, l'échelle, la fréquence d'échantillonnage et la correspondance classe/paramètres.
5. Produire un convertisseur spécifique au schéma observé ; ne pas deviner une variable MATLAB appelée `data`.
6. Exporter en SigMF les seuls flux continus établis ; conserver les exemples indépendants dans un format de benchmark distinct.
7. Figer les hashes et la provenance des échantillons retenus.

Les annotations de famille ne fournissent pas nécessairement les bits transmis, les frontières de paquets, les CRC ou les valeurs applicatives. Un benchmark de reconnaissance et un benchmark de décodage restent séparés.

## Évaluation prévue

Construire une matrice de confusion, mesurer faux positifs sur bruit, rejet de familles absentes, calibration et temps de calcul. Séparer entraînement et validation par session ou capture source avant de créer les petites fenêtres, pour éviter que des segments voisins du même enregistrement apparaissent des deux côtés.

Garder un test externe sur d'autres matériels et sur captures radio réelles. Les performances publiées par les auteurs ne sont pas celles d'IQScope. Aucun entraînement ni modèle issu de ce corpus n'est présent actuellement.

## Accès et licence

L'ouverture du partage par l'outil web a échoué. Cette observation ne prouve pas que le lien est mort ou protégé par mot de passe. Un script de diagnostic distinct teste l'accès public et, si possible, une liste WebDAV en lecture seule ; il ne télécharge pas de fichier IQ et n'essaie aucun mot de passe.

La licence annoncée par les auteurs est **CC BY-NC-SA 4.0**. Le catalogue conserve cette information et la citation. Les enregistrements ne sont pas inclus dans le dépôt Apache-2.0 ; une utilisation commerciale ou une redistribution de données dérivées nécessite de vérifier les conditions applicables. La disponibilité d'un partage ne change pas sa licence.

```bash
python scripts/imec_catalog_probe.py --out corpus-cache/imec/catalog.json
```

Les diagnostics d'accessibilité ne sont pas un test de validité de signal. Tant que les fichiers n'ont pas été inspectés, le statut reste `documentation_verified_files_not_inspected`.
