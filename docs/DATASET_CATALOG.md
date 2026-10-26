# Catalogue des corpus IQScope et intégration des fenêtres HF

État : 25 octobre 2026. Ce catalogue répertorie des sources, pas un ensemble de décodeurs installés. Chaque entrée indique la nature des données et son niveau d'intégration.

## Catalogue livré

| Source | Nature et rôle | Intégration actuelle |
|---|---|---|
| [SDRangel](https://www.sdrangel.org/iq-files/) | Captures réelles multistandard | Extraits ADS-B avec CRC validé ; imports RTTY/radar validés |
| [imec / UGent sub-GHz](https://github.com/JaronFontaine/Sub-GHz-IQ-signals-dataset) | Reconnaissance de technologies | Documentation vérifiée ; fichiers non inspectés |
| [Panoradio HF](https://panoradio-sdr.de/radio-signal-classification-dataset/) | Fenêtres synthétiques de modes HF | Importateur d'une fenêtre NPY et validation publique bornée |
| [TorchSig](https://torchsig.com/) | Génération de scènes synthétiques annotées | À intégrer, avec version et configuration figées |
| [RadioPile](https://zenodo.org/records/22876704) | Agrégation de corpus pour reconnaissance | À intégrer ; recouvre notamment des sources imec et RadioML |
| [UPC-LPWAN-1](https://doi.org/10.34810/data1496) | Modes LPWAN acquis sur matériel | Documentation seulement |
| [NIST Wi-Fi/Bluetooth](https://doi.org/10.18434/mds2-2731) | Émissions réelles d'équipements commerciaux | Documentation seulement |
| [NIST LTE](https://www.nist.gov/ctl/spectrum-technology-and-research-division/applied-systems-metrology-group/iq-data-sets) | Collections de voies montantes LTE | Documentation seulement |
| [LTE/5G/Wi-Fi/ITS-G5/C-V2X](https://zenodo.org/records/10811147) | Reconnaissance de technologies | Documentation seulement |
| [POWDER](https://genesys-lab.org/powder) | Wi-Fi/LTE/NR et variation d'émetteur | Documentation seulement |
| [WiSig](https://cores.ee.ucla.edu/downloads/datasets/wisig/) | Empreintes RF Wi-Fi, matériel et canaux variés | Documentation seulement |
| [ORACLE](https://genesys-lab.org/oracle) | Empreintes RF | Documentation seulement ; distinguer les sous-ensembles et représentations |
| [Drone RF — KU Leuven](https://doi.org/10.48804/HZRVNZ) | Captures IQ de drones et télécommandes | Documentation seulement |
| [RadChar](https://github.com/abcxyzi/RadChar) | Fenêtres radar synthétiques annotées | Documentation seulement |
| [FPV analogique](https://zenodo.org/records/19870020) | Balayages HackRF avec essais TX actif/inactif | Lecteur des annotations ; IQ et vidéo non validés |
| [GNSS-SDR](https://gnss-sdr.org/my-first-fix/) | Capture et traitement GNSS de référence | Documentation seulement |
| [Satellite recordings](https://github.com/daniestevez/satellite-recordings) | Courtes références pour décodeurs satellites | Signaux mono ; pas des IQ stéréo pour le lecteur actuel |

Les sources ont leurs propres licences. Une licence de logiciel ne s'étend pas automatiquement à ses données. Aucun téléchargement massif ni ajout de fichiers IQ au dépôt n'est effectué par le catalogue.

## Utilisation

La commande `iqscope datasets` et l'API locale `GET /api/datasets` exposent le même registre embarqué que l'interface. Un paquet installé inclut ce registre ; il ne dépend pas du répertoire courant.

Dans l'interface : **Explorer les jeux de données** ouvre les sources et explique les statuts. Ce bouton ne lance pas de téléchargement.

Les statuts séparent documentation, adaptateur en validation, import d'une fenêtre validé et sous-ensemble de décodage validé. Même un import validé n'implique pas la reconnaissance de sa famille ni la lecture de son contenu.

## Premier adaptateur : Panoradio HF

Le format publié est un tableau NumPy de fenêtres IQ complexes. Le profil d'import accepte une matrice complexe64/complex128 de forme `(N, 2048)` et utilise 6 kS/s. Il lit une seule ligne choisie par index, sans charger la matrice en mémoire ni aplatir les lignes.

L'export crée :

- `prefix.sigmf-data` : les 2 048 valeurs complexes, converties en float32 I/Q ;
- `prefix.sigmf-meta` : taux, longueur et description de la fenêtre indépendante ;
- `prefix.provenance.json` : nom et taille source, dimensions, dtype initial, index, hash de sortie et limites.

L'accord RF d'origine n'est pas inventé pour ces signaux synthétiques en bande de base. La classe est laissée absente : ni la position de la ligne ni la forme du signal ne sont traitées comme une annotation validée. Le CSV d'étiquettes et son alignement restent à intégrer après vérification.

```bash
iqscope dataset-import panoradio_hf dataset_panoradio_hf.npy --record 17 --out imports/hf-17
```

Choisir ce profil constitue une déclaration de l'utilisateur sur le fichier ; ce n'est pas une preuve cryptographique que toute matrice locale provient de Panoradio. Le hash complet du fichier source n'est pas calculé automatiquement sur plusieurs gigaoctets. L'export refuse les objets/pickle, les tailles incompatibles, les indices invalides, les valeurs non finies et les chemins de sortie déjà occupés.

## Vérification publique bornée

`scripts/panoradio_smoke.py` demande les 64 premiers Kio du fichier officiel. Si le serveur ignore la requête Range, le script ne lit quand même que cette quantité et ferme la réponse. Il valide le header NPY puis une fenêtre complète stockée en ordre C ; il refuse de déduire une ligne depuis un simple préfixe si le fichier est en ordre Fortran.

La fenêtre est enregistrée dans un petit NPY local puis passe par l'importateur réel et l'analyseur IQScope. Le rapport expose dimensions originales, dtype, hash de fenêtre et quantité téléchargée. Il ne revendique ni intégrité du fichier entier, ni prédiction de mode, ni décodage de texte.

## Suite du programme

1. Vérifier et importer les étiquettes Panoradio, sans fuite entre acquisitions de référence.
2. Ajouter un lecteur de fenêtres HDF5 pour des schémas précisément vérifiés.
3. Figer une petite configuration TorchSig, avec vérité terrain temps-fréquence et seed reproductible.
4. Introduire des captures NIST et GNSS continues, en adaptant les limites de débit/durée avant les essais complets.
5. Mesurer reconnaissance et décodage séparément ; conserver des familles absentes de l'apprentissage pour évaluer la réponse « inconnu ».

Les 500 échantillons d'une fenêtre de classification RadioPile ou les données mono satellites ne doivent pas être forcés dans un lecteur qui attend au moins 1 024 échantillons IQ. Chaque représentation exige un contrat d'entrée explicite.

## Résultat public vérifié

La [CI 40217822845](https://github.com/sebadiaz/IQScope/actions/runs/40217822845), commit `22848ace4688e23ad6db22daf61a2ae7279c5b22`, a terminé avec succès : 45 tests sur Python 3.10/3.12/3.13, parcours navigateur incluant le catalogue, extraits SDRangel et fenêtre Panoradio.

Le serveur Panoradio a répondu HTTP 206 à la requête bornée : 65 536 octets reçus sur un fichier de 5 662 310 528 octets. Le header observé décrit `(172800, 2048)`, dtype complexe128 little-endian, ordre C. La fenêtre 0 a été exportée en SigMF puis analysée à 6 kS/s, pour une durée de 0,341333 s.

SHA-256 des octets source de cette fenêtre : `2100801cbf3e299a564d63b1e5c574aad5c714c7f2b13cb9be8cc4e5eb232d3e`. Cette référence est conservée dans le registre et contrôlée par le script de validation. Elle ne vérifie pas le fichier complet.

Aucune classe n'a été prédite ou importée depuis les étiquettes, aucun message n'a été décodé et aucune autre fenêtre n'est revendiquée comme testée. Le statut `window_import_validated` porte uniquement sur cet import et cette analyse.

Le jeu FPV est détaillé dans [les notes spécifiques](DATASET_FPV_ANALOG.md). Il porte le catalogue à 17 sources. Son annotation « TX inactif » ne constitue pas une classe de bruit pur.

Le [portail européen](https://data.europa.eu/data/datasets/oai-zenodo-org-10811147?locale=en) référence le même jeu Zenodo `10811147`, déjà enregistré sous `its_cellular`. Cet accès alternatif est conservé sans ajouter de source distincte ; [fiche du corpus](DATASET_MULTI_RAT.md).


## UDXF Utility Collection 4

Source ajoutée : [UDXF UC4](https://www.udxf.nl/uc4.html).
Les références MP3 sélectionnées sont de l'audio de récepteur, pas des IQ RF.
Le catalogue indique `audio_import_available` et l’adaptateur audio `receiver_audio_ffmpeg`.
Il ne s’agit pas d’un import IQ RF.
Voir [les notes et la sonde audio bornée](DATASET_UDXF_UC4.md).
