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
exemple MATLAB, mais le répertoire racine inspecté ne contient que le README et
une image ; le script n'y a pas été retrouvé. Aucun importateur n'est donc déclaré.
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
vide. Les résultats observés seront ajoutés après inspection du job de catalogue.
