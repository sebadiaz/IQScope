# imec / UGent : LTE, Wi-Fi et DVB-T réels

Partage fourni : [qrJCWgzQaGPfHPr](https://cloud.ilabt.imec.be/index.php/s/qrJCWgzQaGPfHPr).
Le [dépôt des auteurs](https://github.com/JaronFontaine/Technology-Recognition-dataset-of-real-life-LTE-WiFi-and-DVB-T)
relie explicitement ce partage au corpus. Le README lu est identifié par le blob
`600de549458676e27f176b3f48f0e34d696ba6ac`.

## Identité vérifiée dans la documentation

Les auteurs décrivent des IQ capturés sur l'air pour trois technologies, dans
six lieux à Gand. Le taux publié est de 1 Méch/s sauf indication différente dans
le nom. Leur exemple de nom indique du Wi-Fi à 10 Méch/s, un gain de 76 dB et
un centre de 5 240 MHz. Ces paramètres décrivent un exemple ; ils ne sont pas
appliqués à tous les fichiers.

La licence annoncée est [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/).
Les références demandées par les auteurs sont conservées dans
[le manifeste](../corpus/imec-qrJCWgzQaGPfHPr.json). Il faut traiter les captures
originales et leurs éventuelles copies dans RadioPile comme potentiellement
recouvrantes lors des séparations entraînement/test.

## Format à confirmer

L'extension `.bin` et la convention de noms ne définissent pas le dtype,
l'endian, l'ordre I/Q, les voies ou un éventuel en-tête. Le README mentionne un
exemple MATLAB, absent de la racine GitHub inspectée, mais trouvé ensuite dans le
partage public. Cet exemple lit des entiers 16 bits signés et reconstruit I puis
Q. Il ne précise pas l’endian ; aucun octet IQ réel n’a été inspecté et aucun
importateur n’est donc déclaré.
Ce corpus reste distinct du partage sub-GHz `bqXtdp9QsfXLbb3`.

## Inspection des métadonnées publiques

```bash
python scripts/imec_catalog_probe.py --share-token qrJCWgzQaGPfHPr --out corpus-cache/imec/new-share.json
```

Le navigateur de recherche n'a pas pu ouvrir le partage. La sonde CI effectue un
GET HTML borné, puis une demande de listing public de profondeur 1. Elle essaie
les routes WebDAV publiques documentées, sans deviner de mot de passe et sans
télécharger les IQ. Chaque réponse est limitée à 256 Kio. Les erreurs HTTP et
les listings incomplets sont conservés comme observations, pas comme une preuve
de format ou de disponibilité des données.

La route publique moderne et l'en-tête requis sont décrits dans la
[documentation Nextcloud](https://docs.nextcloud.com/server/latest/developer_manual/client_apis/WebDAV/basic.html#public-shares).
Une erreur 401 reste une erreur d'accès ; elle n'est pas assimilée à un dataset
vide. Les observations vérifiées figurent ci-dessous.


## Résultats de l'inspection

Le [job 40387035954](https://github.com/sebadiaz/IQScope/actions/runs/40387035954)
a obtenu le listing public moderne en HTTP 207. Il montre les six dossiers de
lieux, un dossier de traitement, `readme.docx` et le petit script MATLAB.
L'[observation conservée](../corpus/imec-lte-wifi-dvbt-observation.json) contient les
noms, tailles, statuts et la provenance, sans les échantillons IQ.

Le script de 1 455 octets a été lu comme documentation, jamais exécuté.
Son empreinte est `d42050749e4fcedd81856f032d40ee5c215de7211528561239df15da1b7ceb9c`.
La lecture MATLAB utilise la précision `short`, puis une matrice à deux lignes :
I vient de la première ligne et Q de la seconde. Il faut donc distinguer cet
exemple int16 de l'import brut cf32 d'IQScope. La précision des fichiers réels,
leur endian et tout éventuel en-tête restent à valider sur un extrait.

Les commentaires d'unité et de durée du script sont incohérents avec certaines
constantes : vingt millions de valeurs scalaires représenteraient dix secondes
à un million d'échantillons complexes par seconde, pas une seconde. La durée
d'une capture ne doit donc pas être déduite de cette tranche de démonstration.


## Conversion candidate et essai borné

```bash
iqscope dataset-import imec_lte_wifi_dvbt fichier.bin --out extrait
python scripts/imec_iq_prefix.py --location rabot
```

La conversion lit au plus 256 Kio et produit `extrait.le.sigmf-data` /
`extrait.le.sigmf-meta` et les fichiers `.be` correspondants. Les octets sont
conservés à l'identique ; seul le datatype SigMF indique l'hypothèse. Aucun ordre
n'est sélectionné comme vérité. Le taux vient du nom lorsqu'il est explicite,
sinon du défaut des auteurs ; le centre RF suggéré par le nom n'est pas promu
en métadonnée vérifiée. L'en-tête éventuel du fichier reste non vérifié.

La sonde réseau explore au plus trois répertoires dans un lieu documenté,
choisit un `.bin` et demande seulement ses premiers 256 Kio. Elle vérifie le
chemin, le début de la plage HTTP et la taille annoncée, et conserve la borne
même si Range est ignoré. Les deux interprétations sont réimportées et leurs
octets reconstruits doivent être exactement ceux du préfixe avant analyse.
Ce contrôle de conversion ne démontre pas quel endian correspond au signal RF.
Les statistiques des deux hypothèses servent à comparer, pas à certifier.

Le rapport et l'interface gardent le statut d'interprétation non vérifiée quand
ces métadonnées sont réutilisées. Les données et les SigMF générés restent dans
`corpus-cache/` ; seuls les rapports sont téléversés en CI. Aucun classement de
technologie ni décodage de contenu n'est revendiqué par ce contrôle.
