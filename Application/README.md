# Index Stellaire - Application

Application web/mobile responsive (Django) permettant de piloter et suivre en temps réel le bras robotique **Index Stellaire**, un instrument pointant automatiquement vers des objets célestes (étoiles, planètes, ISS, ou toute direction/position arbitraire).

> Ce document décrit la **vision globale** de l'application. Les détails techniques d'implémentation (modèles de données, endpoints API, protocole BLE) seront traités dans un document séparé.

---

##  Objectif

Permettre à l'utilisateur de :
- Visualiser le ciel et sélectionner un astre à pointer
- Suivre en continu un objet céleste (y compris rapide, comme l'ISS)
- Découvrir les événements observables à l'œil nu depuis sa position
- Contrôler l'appareil physique (Index Stellaire) via une liaison Bluetooth/WiFi
- Consulter l'état de l'appareil (batterie, position, dernière synchronisation) même sans lien temps réel permanent

---

##  Fonctionnalités principales

### Carte du ciel interactive
- Visualisation du ciel en temps réel (calcul des positions via Skyfield/Astropy côté serveur)
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

##  Deux modes d'interface

L'application fonctionne même **sans appareil connecté** :

| Sans connexion à l'appareil | Avec connexion à l'appareil |
|---|---|
| Carte du ciel, recherche, événements, planification, historique | Pointer maintenant, calibration, statut batterie/position en direct |

Les actions nécessitant l'appareil sont désactivées (ou remplacées par un bouton "Connecter l'appareil") tant qu'aucune liaison n'est établie. Ça permet de développer/démontrer toute la partie logicielle indépendamment de l'avancement du matériel.

---

##  Communication Application ↔ Appareil

### Architecture générale
- **Django** héberge la logique métier (calcul astro, événements, planification, comptes utilisateurs) sur un serveur accessible depuis internet
- **ESP32** communique avec Django en HTTP/HTTPS, que ce soit sur le WiFi domestique ou via le partage de connexion 4G/5G du téléphone en extérieur, même flux dans les deux cas
- Polling léger et espacé (l'ESP32 récupère sa consigne et remonte un statut à intervalle régulier), pas de connexion permanente nécessaire

### Cas particulier : suivi de l'ISS
L'ISS est un objet proche et rapide (contrairement aux étoiles, à distance infinie) : sa position nécessite une propagation orbitale (SGP4) à partir de données orbitales (TLE) fraîches.
- Avant un passage programmé, l'ESP32 télécharge un TLE à jour
- Le suivi pendant le passage se fait ensuite **en calcul local** sur l'ESP32, sans dépendre d'une connexion active pendant les quelques minutes du survol

### Fonctionnement autonome (72h hors-ligne)
L'appareil ne dépend jamais du réseau pour fonctionner : RTC de précision + éphémérides pré-chargées permettent un suivi continu sans connexion. Le réseau ne sert qu'à envoyer une consigne ponctuelle et récupérer un statut de temps en temps.

---

##  Appairage de l'appareil

1. **Premier démarrage** : l'ESP32 affiche un code sur son écran et est détectable en Bluetooth (BLE)
2. **Configuration** : l'appli se connecte en BLE à proximité, l'utilisateur saisit le code affiché
3. **Liaison au compte** : l'appli transmet le token de l'appareil à Django, qui crée le lien appareil ↔ compte utilisateur
4. **Utilisations suivantes** : plus besoin de ressaisir le code, l'appareil reconnaît son compte et se reconnecte automatiquement

### Gestion de la prise de contrôle
- Une seule connexion BLE active à la fois avec l'appareil (limite naturelle du protocole)
- Si l'appareil est déjà utilisé, un bouton **"Reprendre la main"** permet de forcer la déconnexion de l'autre session
- Un appareil déjà appairé rejette toute nouvelle tentative d'appairage tant qu'il n'a pas été explicitement réinitialisé (action physique sur l'appareil)

---

##  Stack technique (prévisionnelle)

- **Backend** : Django (+ Django REST Framework pour l'API)
- **Calcul astro** : Skyfield / Astropy
- **Frontend** : responsive, carte du ciel en canvas/WebGL
- **Firmware appareil** : ESP32 (WiFi + BLE natifs), calcul SGP4 embarqué pour l'ISS
- **Sécurité API** : authentification par token, HTTPS

---

##  Statut

Document de vision globale, l'architecture technique détaillée (modèles de données Django, format des messages API, protocole BLE précis) sera définie dans un document séparé.
