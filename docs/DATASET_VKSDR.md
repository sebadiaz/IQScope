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
Les taux et formats ci-dessous proviennent de la lecture des en-têtes.


## Résultats observés

Exécution : [CI 40361285578](https://github.com/sebadiaz/IQScope/actions/runs/40361285578).
Le [résumé de validation](../corpus/vksdr_validation.json) conserve les empreintes
SHA-256 et les réponses HTTP.

| Identifiant | Taux lu | Durée analysée | Format |
|---|---:|---:|---|
| `noaa15_pds` | 250 000 éch/s | 1 s | PCM16, deux voies |
| `fengyun4a_lrit` | 1 024 000 éch/s | 0,512 s | PCM16, deux voies |
| `uhf_fo` | 750 000 éch/s | 0,699 s | PCM16, deux voies |
| `coms1_multiple` | 375 000 éch/s | 1 s | PCM16, deux voies |
| `coms1_fd02` | 375 000 éch/s | 1 s | PCM16, deux voies |

Deux Mio ont été reçus par fichier et les cinq conversions SigMF sont exactes.
Aucun centre RF n'a été trouvé dans les en-têtes lus : le rapport reste relatif
à la capture, tandis que les indications des noms de fichiers sont conservées
séparément. Le statut `validated_subset` concerne ces préfixes et l'import,
pas le décodage des modes ni l'intégrité des captures complètes.


## Import depuis l'interface

Ouvrir **Explorer les jeux de données**, puis la fiche VKSDR. Les cinq
captures ont chacune un bouton **Analyser un extrait · 2 Mio maximum**. Le
serveur télécharge le préfixe après ce clic, convertit les IQ en SigMF et lance
l'analyse existante. Le catalogue lui-même utilise les métadonnées embarquées :
il ne télécharge pas les cinq WAV lors de son ouverture.

Le résultat montre le nom fourni par la source, les octets reçus et la durée
analysée. Les fichiers `excerpt.sigmf-data`, `excerpt.sigmf-meta` et
`provenance.json` sont téléchargeables séparément. Le WAV tronqué reste interne
au traitement et n'est pas proposé comme une capture WAV complète.

L'API expose `GET /api/recordings/vksdr` et
`POST /api/recordings/vksdr/{id}/analyze`. Les identifiants doivent appartenir
à la liste embarquée ; aucune URL fournie par l'appelant n'est utilisée. Les
redirections sont limitées au bucket HTTPS VKSDR. Les jobs partagent la file
locale d'analyse, les erreurs réseau apparaissent dans leur statut, et les
résultats sont évincés selon la même limite de 32 jobs que les autres analyses.
Une connexion Internet du serveur est requise pour importer un extrait.

Ce raccourci réutilise le même lecteur et les mêmes contrôles que la sonde de
corpus. Il ne fournit toujours pas de décodeur satellite ni de garantie de
reconnaissance des modes annoncés. Les taux affichés dans le catalogue sont ceux
du contrôle de référence ; le rapport d'import utilise les en-têtes effectivement
lus lors du téléchargement.
