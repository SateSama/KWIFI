# Surveillance Box

Application de bureau (Python / Tkinter, bibliothèque standard uniquement) qui
surveille **tout ce qui entre et tout ce qui sort de votre box internet** :
débits descendant et montant en temps réel, volumes cumulés, appareils
connectés (Freebox), températures, et historique complet enregistré en SQLite
avec export CSV.

## Fonctionnalités

- **Détection automatique** de la box sur le réseau local
- **Freebox** (API officielle Freebox OS) :
  - débits instantanés descendant / montant
  - volumes totaux depuis le démarrage de la connexion
  - liste des appareils connectés (nom, IP, MAC, état)
  - températures, ventilateur, uptime
  - appairage guidé au premier lancement (validation sur l'écran de la Freebox)
- **Livebox (Orange), Box SFR, box génériques** : via UPnP IGD
  - compteurs total envoyé / reçu, IP publique, débits calculés
- **Graphique** de l'historique des débits en direct
- **Historique** stocké dans une base SQLite locale, exportable en CSV

## Installation

Aucune dépendance externe : Python 3.8+ suffit.

### Windows

1. Installez Python depuis https://www.python.org/downloads/ (cochez
   « Add Python to PATH » à l'installation) ou via le Microsoft Store.
2. Ouvrez PowerShell dans un dossier classique (par exemple `Documents`),
   **évitez** `C:\Windows\system32` qui nécessite des droits administrateur :

```powershell
cd $HOME\Documents
git clone https://github.com/SateSama/KWIFI
cd KWIFI
py main.py
```

La commande `python3` n'existe pas sous Windows : utilisez `py` (ou `python`).
Si Windows affiche « Python est introuvable », ouvrez
Paramètres > Applications > Paramètres d'exécution des applications et
désactivez les raccourcis d'installation de l'application Python, puis
installez Python depuis python.org.

### Linux / macOS

```bash
python3 main.py
```

Sous Linux, si Tkinter manque : `sudo apt install python3-tk`.

## Premier lancement

- **Freebox** : si l'application n'a jamais été autorisée, cliquez sur
  « Appairer la Freebox », puis **appuyez sur la flèche droite** de la Freebox
  pour accepter la demande. Le jeton est ensuite mémorisé dans
  `~/.config/surveillance-box/freebox_token.json`.
- **Livebox / SFR / autre** : la détection UPnP se charge de tout, à condition
  que l'UPnP soit activé dans la box (c'est le cas par défaut sur la plupart
  des modèles).

## Données enregistrées

`~/.local/share/surveillance-box/traffic.db` (SQLite) contient, à chaque
mesure : horodatage, source, octets reçus, octets envoyés, débits.

## Structure

```
main.py                     point d'entrée
box_monitor/freebox.py      client API Freebox OS (appairage + session)
box_monitor/upnp.py         client UPnP IGD générique (SSDP + SOAP)
box_monitor/storage.py      historique SQLite + export CSV
box_monitor/monitor.py      boucle de surveillance (thread)
box_monitor/gui.py          interface graphique Tkinter
```
