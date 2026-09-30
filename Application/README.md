# Index Stellaire - Application

Application web/mobile responsive (Django) permettant de piloter et suivre en temps réel le bras robotique **Index Stellaire**, un instrument pointant automatiquement vers des objets célestes (étoiles, planètes, ISS, ou toute direction/position arbitraire).

> Ce document décrit la **vision globale** de l'application. Les détails techniques d'implémentation (modèles de données, endpoints API, protocole BLE) seront traités dans un document séparé.

---

## Objectif

Permettre à l'utilisateur de :
- Visualiser le ciel et sélectionner un astre à pointer
- Suivre en continu un objet céleste (y compris rapide, comme l'ISS)
- Découvrir les événements observables à l'œil nu depuis sa position
- Contrôler l'appareil physique (Index Stellaire) via le serveur, en WiFi ou en partage de connexion 4G/5G (le Bluetooth n'est qu'un mode de secours local)
- Consulter l'état de l'appareil (batterie, position, dernière synchronisation) même sans lien temps réel permanent

---

## Fonctionnalités principales

### Carte du ciel interactive
- Visualisation du ciel en temps réel (calcul des positions via Skyfield côté serveur)
- Sélection d'un astre par clic ou recherche par nom
- Bouton **Pointer** / **Arrêter** pour déclencher ou stopper le suivi
- Position de repos ("parking") définie pour l'appareil quand rien n'est ciblé

### Événements à l'œil nu
- Liste des événements visibles **ce soir, depuis la position réelle de l'utilisateur** (pas un calendrier générique) : conjonctions, essaims de météores, passages ISS, etc.
- Notification push quand un événement approche
- Bouton pour pointer directement l'appareil vers l'événement sélectionné

### Recherche & planification
- Recherche libre d'un objet (planète, étoile, ISS, ou saisie manuelle de coordonnées RA/Dec pour un usage avancé)
- Programmation d'une cible à une heure donnée ("suivre l'ISS à 21h47")
- File d'attente de plusieurs cibles enchaînées dans la soirée

### Mode "cible personnalisée"
- Pointer une position arbitraire (coordonnées GPS d'un lieu, par exemple), y compris à travers le sol si l'objet/lieu est sous l'horizon, exploite la structure mécanique à liberté de mouvement complète de l'appareil

### Journal d'observation
- Historique des cibles pointées/observées
- Possibilité d'ajouter une note ou une photo prise au même moment

### Tableau de bord de l'appareil
- Batterie restante
- Cible actuellement suivie
- Statut GPS (fix ou non)
- Dernière synchronisation RTC
- Statut connecté / hors ligne, avec horodatage de la dernière donnée reçue (pas de fausse impression de temps réel permanent)

---

## Deux modes d'interface

L'application fonctionne même **sans appareil connecté** :

| Sans connexion à l'appareil | Avec connexion à l'appareil |
|---|---|
| Carte du ciel, recherche, événements, planification, historique | Pointer maintenant, calibration, statut batterie/position en direct |

Les actions nécessitant l'appareil sont désactivées (ou remplacées par un bouton "Connecter l'appareil") tant qu'aucune liaison n'est établie. Ça permet de développer/démontrer toute la partie logicielle indépendamment de l'avancement du matériel.

---

## Communication Application ↔ Appareil

### Architecture générale
- **Django** héberge la logique métier (calcul astro, événements, planification) sur un serveur. Pas de comptes utilisateurs au départ : l'accès se fait avec un code de session.
- **Déploiement en deux temps** :
  - **Mode local (maintenant)** : le téléphone, l'ESP32 et le serveur (Raspberry Pi) sont sur le même WiFi. Fonctionne uniquement à portée de ce WiFi.
  - **Mode distant (plus tard)** : le serveur est rendu accessible depuis internet via un tunnel, et l'ESP32 s'y connecte par le partage de connexion 4G/5G du téléphone.
- **ESP32** communique avec Django en HTTP/HTTPS, que ce soit sur le WiFi domestique ou via le partage de connexion 4G/5G du téléphone en extérieur, même flux dans les deux cas
- Polling léger et espacé (l'ESP32 récupère sa consigne et remonte un statut à intervalle régulier), pas de connexion permanente nécessaire
- **Répartition des rôles** : l'ESP32 gère la communication réseau ; le STM32 (relié par UART) fait les calculs de suivi et pilote les moteurs. L'application envoie une **cible** (un astre ou des coordonnées), pas des angles : c'est l'appareil qui calcule.
- **Bluetooth (secours)** : mode local optionnel pour pointer sans aucun réseau, à côté de l'appareil. Uniquement sur Android/Chrome (Web Bluetooth n'existe pas sur iPhone). Ce n'est pas le chemin principal.

### Cas particulier : suivi de l'ISS
L'ISS est un objet proche et rapide (contrairement aux étoiles, à distance infinie) : sa position nécessite une propagation orbitale (SGP4) à partir de données orbitales (TLE) fraîches.
- Avant un passage programmé, le serveur fournit à l'appareil un TLE à jour (l'ESP32 le relaie au STM32)
- Le suivi pendant le passage se fait ensuite **en calcul local** sur le STM32, sans dépendre d'une connexion active pendant les quelques minutes du survol

### Fonctionnement autonome (48h hors-ligne)
L'appareil ne dépend pas du réseau pour suivre une cible : son GPS embarqué, sa RTC et des éphémérides pré-chargées permettent un suivi continu jusqu'à 48h sans connexion (pour les satellites, le suivi autonome n'a de sens que peu après une mise à jour des TLE). Le réseau ne sert qu'à envoyer une consigne ponctuelle et récupérer un statut de temps en temps.

---

## Connexion de l'appareil

1. **Nouveau lieu / premier démarrage** : si l'ESP32 ne reconnaît aucun réseau WiFi enregistré, il crée son propre WiFi temporaire (par exemple `IndexStellaire-Setup`)
2. **Configuration du WiFi** : le téléphone s'y connecte, une page de configuration (servie par l'ESP32 lui-même) permet de choisir le réseau WiFi, la maison ou le partage de connexion du téléphone, et de saisir son mot de passe. Fonctionne sur iPhone comme sur Android, sans Bluetooth.
3. **Connexion à l'appli** : l'ESP32 affiche un code sur son écran, que l'utilisateur saisit dans l'appli pour se connecter
4. **Utilisations suivantes** : l'appareil se reconnaît tout seul au dernier réseau connu, plus besoin de reconfigurer ni de ressaisir le WiFi

### Gestion de la prise de contrôle
- Plusieurs personnes peuvent se connecter à l'appareil avec le code, mais une seule le contrôle à la fois
- Un bouton **"Reprendre la main"** permet de prendre le contrôle à la place de la personne qui l'a ; le dernier objet pointé reste visible et peut être changé
- Un appareil déjà appairé rejette toute nouvelle tentative d'appairage tant qu'il n'a pas été explicitement réinitialisé (action physique sur l'appareil)

---

## Stack technique (prévisionnelle)

- **Backend** : Django (+ Django REST Framework pour l'API)
- **Calcul astro** : Skyfield
- **Frontend** : responsive, installable en PWA, carte du ciel en canvas avec d3-celestial
- **Firmware appareil** : ESP32 (WiFi, communication avec le serveur) + STM32 (contrôle temps réel, calcul de suivi, SGP4 embarqué pour l'ISS), liaison UART
- **Sécurité API** : authentification par token pour l'appareil, code de session pour les utilisateurs, HTTPS (surtout en mode distant)

---

## Statut

Document de vision globale, l'architecture technique détaillée (modèles de données Django, format des messages API, protocole BLE précis) sera définie dans un document séparé.