# VKSDR : captures IQ WAV

Source examinée le 26 octobre 2026 : [VKSDR IQ Recordings](https://vksdr.com/iq/).
Le site présente cinq enregistrements WAV comme des IQ : NOAA-15 PDS,
Fengyun-4A LRIT, UHF-FO et deux variantes COMS-1 LRIT. Les descriptions de modes
proviennent du site ; elles ne sont pas des reconnaissances effectuées par IQScope.

Les liens sélectionnés sont conservés dans [le manifeste](../corpus/vksdr.json).
Les noms de fichiers contiennent des indications de fréquence et parfois de taux.
La sonde distingue ces indices des champs réellement lus dans le WAV ; elle ne
transforme pas un indice de nom de fichier en métadonnée RF vérifiée.

## Contrôle borné

```bash
python scripts/vksdr_corpus.py
python scripts/vksdr_corpus.py --name noaa15_pds --name uhf_fo
```

Chaque requête demande les deux premiers Mio. La lecture reste bornée même si
le serveur ignore Range. Un retour HTTP 206 doit débuter à l'octet zéro. Le
lecteur examine les chunks RIFF/RF64, exige deux voies I/Q et lit au plus une
seconde, dans les limites du préfixe reçu. Les imports WAV ordinaires continuent
de refuser les fichiers tronqués : `allow_prefix` est réservé à la sonde.

La sonde exporte une paire SigMF complète, la réimporte et compare les
échantillons et métadonnées exactement avant l'analyse. Les rapports conservent
URL, taille du préfixe, empreinte SHA-256, HTTP Content-Range, format, taux,
centre déclaré et indice de fréquence du nom de fichier. Les fichiers IQ ne
sont pas ajoutés à Git et seuls les rapports sont téléversés en artefacts CI.
Les droits de redistribution et l'intégrité des fichiers complets ne sont pas
établis par cette inspection.

## Portée

Le succès du contrôle prouve l'import d'un extrait et l'exécution de l'analyse
existante. Il ne prouve pas la reconnaissance d'un satellite, l'extraction
LRIT d'une image, le décodage PDS ou l'interprétation de communications UHF.
Un préfixe d'une seconde au maximum peut aussi être trop court pour un protocole.
Les résultats de taux et formats seront consignés après inspection de la CI
`vksdr-iq` ; aucun format particulier n'est supposé avant lecture des en-têtes.
