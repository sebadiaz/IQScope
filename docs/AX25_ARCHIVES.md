# Sauvegarder et relire un historique AX.25

Dans **SDR en direct**, télécharger **l’historique AX.25 (JSON)**. Ce fichier
contient les événements encore conservés : octets complets avec FCS, champs
de liaison et métadonnées de session. Il reste sur la machine après fermeture
d'IQScope. La sauvegarde est manuelle ; l'application ne crée pas de journal
permanent et les événements déjà évincés ne sont pas récupérés.

Dans une nouvelle session d'IQScope, choisir **Historique**, sélectionner ce
JSON puis **Ouvrir l’historique**. Les IQ d'origine ne sont pas nécessaires.
Tous les événements du fichier sont consultables, jusqu'à 128. La relecture
propose le JSON normalisé, les trames binaires avec FCS et un KISS chronologique
sans FCS. Un historique vide est également accepté.

## Vérifications à l'ouverture

`POST /api/archives/ax25/open` reçoit le fichier brut, limité à 1 Mio. Il accepte
le format d'historique AX.25 FM IQScope `0.1`, vérifie les limites d'événements,
identifiants, nombres finis et intervalles déclarés. Chaque FCS est recalculé
sans correction et les adresses/contrôles sont reparsés depuis les octets.
Une trame invalide fait refuser l'ensemble du fichier.

Les champs dérivés fournis dans le JSON — texte, positions, fréquence calculée,
temps calculé ou booléen `fcs_valid` — ne servent pas de preuve : ils sont
reconstruits. Les I/S/U conservent les mêmes limites de lecture ; les deux
hypothèses d'une trame I ambiguë restent non sélectionnées. Aucune calibration
APRS ou connexion de liaison n'est reconstruite entre événements.

Le contrôle FCS vérifie les octets archivés, sans prouver leur origine radio.
Les indices source, le débit, les paramètres RF et les nombres d'observations
restent des déclarations du fichier. Aucun spectre ou waterfall n'est fabriqué
à partir de ces seules trames.

## Séparation du direct et validation

La relecture ne remplit pas l'historique live, ne crée pas de job DSP et
n'écrit aucun fichier sur le serveur. Les résultats relus restent dans le
navigateur ; les téléchargements sont enregistrés à la demande de l'utilisateur.
Choisir cet onglet depuis le direct arrête le récepteur, comme le passage au
mode fichier.

Les tests couvrent export dans une application, fermeture puis ouverture dans
une autre, rejet des FCS altérés et des formats hors limites, champs dérivés
falsifiés, UTF-8, échappements KISS et ambiguïtés I. Chromium sauvegarde puis
recharge un historique simulé après réinitialisation du récepteur, télécharge
les octets exacts, refuse une archive altérée et vérifie la vue mobile.

Les cinq trames de la référence IQ épinglée sont également exportées puis
relues : trois I et deux RR, sans charge applicative sélectionnée. Ce rejeu
est une régression de développement sur ces octets, sans acquisition matérielle
en direct ni référence indépendante de l'auteur pour le contenu des paquets.
