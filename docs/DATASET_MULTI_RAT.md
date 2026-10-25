# LTE / 5G NR / Wi-Fi / ITS-G5 / C-V2X PC5

Source canonique : [Zenodo 10811147](https://zenodo.org/records/10811147), DOI `10.5281/zenodo.10811147`, Girmay Merkebu, version v1 publiée le 13 mars 2024.

L'[entrée data.europa.eu](https://data.europa.eu/data/datasets/oai-zenodo-org-10811147?locale=en) est enregistrée comme accès alternatif à `its_cellular`. Le catalogue reste à 17 sources : il ne compte pas un index et son jeu d'origine comme deux corpus indépendants.

La notice décrit six familles : LTE, 5G NR, Wi-Fi, ITS-G5, C-V2X PC5 et bruit, pour des travaux de reconnaissance de technologie et de caractérisation du trafic. Elle annonce 7 500 exemples par technologie dans chaque cluster.

L'archive publiée, `dataset_multi_RAT.zip`, est annoncée à environ 1,2 Go. Sa prévisualisation montre `dataset_multirat/dataset_noise_added.mat`. Cette observation établit l'extension du conteneur ; elle ne vérifie ni version MATLAB, ni variables, ni dimensions, ni correspondance des étiquettes.

État IQScope : **documentation seulement**. Aucun import, modèle de reconnaissance ou décodage n'est validé sur ce corpus. Avant d'ajouter un lecteur, vérifier sa sérialisation et distinguer captures continues, fenêtres et données transformées ; ne pas confondre largeur RF et fréquence d'échantillonnage. La licence effective reste à vérifier séparément.

Examen de la notice et de la prévisualisation : 25 octobre 2026.
