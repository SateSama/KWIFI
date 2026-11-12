# Surveillance Box

Application de bureau (Python / Tkinter, bibliothèque standard uniquement) qui
surveille **tout ce qui entre et tout ce qui sort de votre box internet** :
débits descendant et montant en temps réel, volumes cumulés, appareils
connectés (Freebox), températures, et historique complet enregistré en SQLite
avec export CSV.

## 📥 Télécharger le .exe (Windows, sans installer Python)

Un exécutable Windows autonome est compilé automatiquement par GitHub Actions
à chaque mise à jour du code :

1. Ouvrez la page [Releases du dépôt](https://github.com/SateSama/KWIFI/releases)
2. Téléchargez **SurveillanceBox.exe** (release « latest »)
3. Double-cliquez dessus. C'est tout.

> Windows Defender/SmartScreen peut afficher un avertissement (« éditeur
> inconnu ») car l'exécutable n'est pas signé : cliquez sur
> « Informations complémentaires » puis « Exécuter quand même ».

Pour recompiler manuellement : `pip install pyinstaller` puis
`pyinstaller --onefile --windowed --name SurveillanceBox main.py`.

## Fonctionnalités

- **Détection automatique** de la box sur le réseau local, dans l'ordre :
  Freebox → Livebox → SFR → Bbox → UPnP générique (n'importe quelle autre box)
- **Freebox** (API officielle Freebox OS) :
  - débits instantanés descendant / montant
  - volumes totaux depuis le démarrage de la connexion
  - liste des appareils connectés (nom, IP, MAC, état)
  - températures, ventilateur, uptime
  - appairage guidé au premier lancement (validation sur l'écran de la Freebox)
- **Livebox (Orange) 3, 4, 5, 6, 7** (API sysbus) :
  - état de la connexion WAN, IP publique
  - compteurs total envoyé / reçu quand le firmware les expose
  - liste des appareils connectés et températures (mot de passe admin requis,
    par défaut les 8 premiers caractères de la clé Wi-Fi)
- **Box SFR / Red (Box 8, 10+...)** (API REST locale) :
  - état WAN, IP publique, uptime, température
  - liste des appareils connectés (mot de passe admin requis)
- **Bbox (Bouygues) Miami, Ultym, Must, Wi-Fi 6/7** (API REST locale) :
  - compteurs total envoyé / reçu, IP publique, appareils connectés
- **Toutes les autres box** (UPnP IGD) :
  - compteurs total envoyé / reçu, IP publique, débits calculés
- Quand une box ne fournit pas ses compteurs natifs, l'application les
  récupère automatiquement en UPnP en complément
- **Graphique** de l'historique des débits en direct
- **Historique** stocké dans une base SQLite locale, exportable en CSV

## Installation

Aucune dépendance externe : Python 3.8+ suffit.

```bash
python3 main.py
```

## Premier lancement

- **Freebox** : si l'application n'a jamais été autorisée, cliquez sur
  « Appairer la Freebox », puis **appuyez sur la flèche droite** de la Freebox
  pour accepter la demande. Le jeton est ensuite mémorisé dans
  `~/.config/surveillance-box/freebox_token.json`.
- **Livebox** : un mot de passe admin est demandé (par défaut : les 8 premiers
  caractères de la clé Wi-Fi). Sans mot de passe, l'application bascule en
  mode UPnP (volumes et débits, sans liste des appareils).
- **Box SFR / Red** : un mot de passe admin est demandé (par défaut : la clé
  Wi-Fi figurant sur l'étiquette de la box). Sans mot de passe : mode UPnP.
- **Bbox** : la plupart des informations sont accessibles sans mot de passe ;
  si la box le demande, utilisez le bouton « Mot de passe box ».
- **Autre box / routeur** : détection UPnP automatique, à condition que l'UPnP
  soit activé dans la box (c'est le cas par défaut sur la plupart des modèles).
  Le bouton « Mot de passe box » permet aussi de ressaisir un mot de passe
  sans redémarrer l'application.

## Données enregistrées

`~/.local/share/surveillance-box/traffic.db` (SQLite) contient, à chaque
mesure : horodatage, source, octets reçus, octets envoyés, débits.

## Structure

```
main.py                     point d'entrée
box_monitor/freebox.py      client API Freebox OS (appairage + session)
box_monitor/livebox.py      client API sysbus Livebox (Orange)
box_monitor/sfr.py          client API REST Box SFR / Red
box_monitor/bbox.py         client API REST Bbox (Bouygues)
box_monitor/upnp.py         client UPnP IGD générique (SSDP + SOAP)
box_monitor/storage.py      historique SQLite + export CSV
box_monitor/monitor.py      boucle de surveillance + chaîne de détection (thread)
box_monitor/gui.py          interface graphique Tkinter
```
