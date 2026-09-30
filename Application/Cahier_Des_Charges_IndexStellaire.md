# Cahier des charges - Application Index Stellaire

> **Index Stellaire** : bras robotique à 2 axes (sphère armillaire) pointant en temps réel vers des astres. Ce document décrit **l'application logicielle** (web/PWA Django) et son **API**.

- **Version** : 0.2 

---

## 1. Objectif

Piloter et accompagner le bras Index Stellaire : choisir un astre, le faire pointer, découvrir ce qui est observable depuis sa position, et suivre l'état de l'appareil.

L'application fonctionne d'abord **en local sur le réseau wifi domestique** (mode 1), et pourra plus tard être rendue accessible **depuis n'importe où** via un serveur exposé sur internet (mode 2, voir §7). L'appareil, lui, reste **autonome jusqu'à 48 h** sans l'application.

## 2. Périmètre et priorités

Chaque fonctionnalité est étiquetée :

- **[MVP]** — première version qui fonctionne de bout en bout
- **[v2]** — amélioration prévue après le MVP
- **[Futur]** — envisagé, non planifié

**Objectif de la v1 : une application qui marche à peu près de bout en bout**, quitte à revenir la durcir ensuite. On garde en tête pendant la conception l'endroit où brancher l'authentification et l'accès distant, sans le finaliser tout de suite.

## 3. Acteurs et plateformes

| Acteur | Rôle |
|---|---|
| Utilisateur (observateur) | Consulte le ciel, choisit et pointe des astres, contrôle l'appareil |
| Appareil (ESP32 + STM32) | Interroge le serveur, exécute le pointage, remonte sa télémétrie |
| Serveur Django | Calcule les positions, sert la carte, expose l'API, relaie les commandes |

**Plateformes cibles** : navigateur web responsive, installable en **PWA** (icône sur l'écran d'accueil, plein écran). Points à intégrer :

- **Contrôle principal via le serveur en HTTP(S)** : fonctionne sur tous les téléphones (iPhone comme Android).
- **BLE (pointage local direct) = Android/Chrome uniquement.** Pas de Web Bluetooth sur iOS ni Firefox. C'est donc un mode secondaire, réservé au cas où il n'y a aucun réseau du tout.
- **Notifications push web** : nécessitent la PWA installée à l'écran d'accueil (iOS ≥ 16.4) et **HTTPS**.

## 4. Architecture logicielle

### 4.1 Projet Django, deux apps

- **`ciel`** : contenu et calculs astronomiques : catalogues, constellations, positions (Skyfield), événements, fiches objets.
- **`appareil`** : communication avec l'appareil : appairage, jetons, sessions de contrôle, file de commandes, télémétrie.

Un seul projet, une seule base, un seul serveur. Séparation logique uniquement.

### 4.2 Briques externes

| Besoin | Choix retenu | Rôle |
|---|---|---|
| Calcul astro serveur | **Skyfield** (Python) | RA/Dec, alt/az topocentrique, lever/coucher, satellites (SGP4) |
| Éphémérides planètes | **JPL DE421/DE440** (fichier `.bsp`, chargé par Skyfield) | Positions Soleil, Lune, planètes |
| TLE satellites (ISS…) | **Celestrak** | Éléments orbitaux pour SGP4 |
| Carte du ciel (navigateur) | **d3-celestial** (canvas) | Rendu interactif étoiles/constellations/DSO |
| Catalogue d'étoiles | Données de d3-celestial / base type HYG | Alimente la carte et la recherche |
| PWA / push | Service worker + Web Push (VAPID) | Installation + notifications |

### 4.3 Répartition des calculs (serveur ↔ STM32)

- **Serveur** : calcule la position des astres (alt/az pour la position et l'heure données) pour l'affichage et le pointage, et fournit à l'appareil de quoi suivre en autonomie (identifiant de cible + éphémérides / TLE nécessaires). Gère la carte et les fiches.
- **STM32** : refait et affine les calculs en temps réel pour le suivi fin, et **continue seul en cas de déconnexion** à partir de la dernière cible connue et de son **GPS embarqué** (position et heure), jusqu'à 48 h.
- **L'application envoie une cible** (astre à suivre ou coordonnées), **pas des angles bruts** : l'appareil reste maître du suivi (décision D1).

## 5. Fonctionnalités

### 5.1 Carte du ciel `ciel`

- **F1 [MVP]** Carte du ciel interactive en canvas, style soigné cohérent avec l'univers du projet (fond nocturne, étoiles par magnitude, lignes de constellations, Voie lactée).
- **F2 [MVP]** Affichage centré sur la **position GPS réelle** et l'heure courante.
- **F3 [MVP]** Sélection d'un objet par clic sur la carte → ouverture de sa fiche.
- **F4 [MVP]** Bouton **Pointer** / **Arrêter** depuis la carte ou la fiche.
- **F36 [MVP]** **Filtres d'affichage** : choisir les types d'objets visibles (étoiles seules, planètes, Lune/Soleil, satellites, ciel profond, comètes) en plus du seuil de magnitude. Les filtres s'appliquent aussi à la recherche.
- **F5 [v2]** Affichage/masquage des dessins artistiques de constellations (ex. Cancer, Capricorne).
- **F6 [Futur]** Mode boussole / réalité augmentée (capteurs du téléphone), **exclu du MVP**.

### 5.2 Objets pris en charge

- **F7 [MVP]** Étoiles (seuil de magnitude réglable), planètes, Lune, Soleil, ISS.
- **F8 [v2]** Autres satellites, comètes, objets Messier/NGC.
- **F9** *(Sans objet.)* Le laser est à **usage intérieur uniquement** (décision D3) ; aucun verrouillage Soleil n'est nécessaire au MVP. À revoir si un embout optique est un jour utilisé en extérieur.

### 5.3 Fiches objets

- **F10 [MVP]** Fiche par objet : nom, type, magnitude, coordonnées, visibilité ce soir (lever/coucher, hauteur max).
- **F11 [v2]** Contenu enrichi : description **issue de sources fiables**, mythologie, image **libre de droits**.
  - Règle transverse (D7) : chaque contenu ajouté (fiche, événement, image) est **recherché et vérifié à la source au moment de l'ajout**, avec sa source et sa licence notées.
  - Sources images à privilégier : NASA/ESA, Wikimedia Commons (licence vérifiée par image).

### 5.4 Recherche

- **F12 [MVP]** Recherche d'un objet par nom, avec accès direct à sa fiche et au pointage. Respecte les filtres (F36).

### 5.5 Événements à l'œil nu

- **F13 [v2]** Liste des **événements observables ce soir depuis la position réelle** : conjonctions, essaims de météores, passages ISS, phases de Lune, etc.
- **F14 [v2]** Événements **calculés en interne** avec Skyfield (D6). Si le serveur a accès à internet, une **source externe spécialisée et vérifiée** peut compléter la liste.
- **F15 [v2]** Chaque événement renvoie à l'objet concerné et permet de le pointer.
- **F16 [v2]** **Notifications** d'événements (via Web Push, PWA installée).

### 5.6 Pointage et contrôle de l'appareil `appareil`

- **F17 [MVP]** **Pointage simple** : l'utilisateur choisit un objet (ou une cible personnalisée), l'appareil pointe et suit. Un seul mode pour l'instant.
- **F18 [MVP]** **Cible personnalisée** : pointer des coordonnées arbitraires, y compris **sous l'horizon** (direction géométrique réelle à travers la Terre), choix fait depuis l'app.
- **F19 [MVP]** **Position de repos (parking)** quand aucune cible n'est active.
- **F20 [MVP]** L'app **ne gère pas les embouts** : elle envoie uniquement des ordres de pointage, et le firmware s'occupe de l'embout monté (y compris le changement de pin). Aucun impact côté app au MVP ; la détection de l'embout reste à définir côté matériel (voir P8).
- **F37 [MVP]** **Configuration wifi de l'appareil** : point d'accès temporaire au démarrage + page de configuration minimaliste servie par l'ESP32 (choix du réseau, mot de passe), voir §7.3.
- **F21 [v2]** Affichage de l'embout détecté (lecture seule) et, plus tard, contrôle (laser on/off, couleur).
- **F22 [v2]** Visite guidée / file d'observation enchaînant plusieurs objets, avec horaires.

### 5.7 Calibration

- **F23 [MVP]** Bouton **« Calibrer »** lançant la procédure (alignement au démarrage). Pas de joystick virtuel au MVP.
- **F24 [Futur]** Réglage fin manuel (joystick virtuel dans l'app), le joystick physique reste la voie matérielle.

### 5.8 État de l'appareil (page dédiée)

- **F25 [MVP]** Page **« État »** séparée : niveau de batterie, fix GPS, connecté/déconnecté, dernière synchronisation, dernière cible pointée.
- **F26 [v2]** Télémétrie détaillée : température drivers, angles encodeurs, précision estimée, erreurs.
- **F27 [Futur]** Mise à jour firmware OTA depuis l'app.

### 5.9 Sessions et multi-utilisateur

- **F28 [MVP]** **Plusieurs personnes peuvent se connecter à l'appareil** (via un **code de session**), mais **une seule contrôle à la fois**. Pas de comptes utilisateurs au départ (D2).
- **F29 [MVP]** Bouton **« Prendre le contrôle »** : reprend la main sur la session en cours.
- **F30 [MVP]** À la reprise, le nouvel utilisateur **voit le dernier objet pointé** et peut le changer.
- **F31 [MVP]** **Interface connectée/déconnectée** : boutons d'action grisés quand l'appareil est hors ligne.
- **F32 [MVP]** **Heartbeat** pour détecter l'état en ligne/hors ligne.

### 5.10 Mode autonome

- **F33 [MVP]** L'appareil **suit sa cible seul jusqu'à 48 h** sans réseau ni app, à partir de la dernière cible et de son GPS embarqué. Le STM32 doit embarquer les données nécessaires (éphémérides Soleil/Lune/planètes, catalogue d'étoiles) pour couvrir cette durée.
- **F34 [MVP]** Au-delà (jusqu'à ~72 h max), retour à un comportement normal / parking.
- **F35 [MVP]** À la reconnexion, l'app récupère l'état réel (dernière cible, batterie, position).

> **Limite connue** : pour étoiles, planètes et Lune, les calculs restent précis sur 48 h. Pour l'ISS et les satellites, les TLE se dégradent en quelques jours et l'objet passe vite : le suivi autonome n'a de sens que peu après une mise à jour des TLE.

## 6. API (celle que tu construis)

API REST servie par Django, consommée par l'app web **et** par l'ESP32. Esquisse à affiner :

**Côté appareil (ESP32 → serveur, polling HTTP/HTTPS)**
- `POST /api/device/heartbeat` — signale l'état (batterie, GPS, cible en cours) et récupère la prochaine commande.
- `GET  /api/device/command` — commande courante à exécuter (cible + éphémérides/TLE nécessaires au suivi autonome).
- `POST /api/device/telemetry` — remontée de télémétrie détaillée.

**Côté application (navigateur → serveur)**
- `GET  /api/sky/objects?lat=&lon=&t=` — objets visibles + positions alt/az (filtrables).
- `GET  /api/objects/{id}` — fiche objet.
- `GET  /api/search?q=` — recherche.
- `GET  /api/events?lat=&lon=&date=` — événements du soir.
- `POST /api/point` — demander le pointage d'une cible (objet ou coordonnées).
- `POST /api/stop` — arrêt / retour au parking.
- `POST /api/calibrate` — lancer la calibration.
- `POST /api/control/take` — prendre le contrôle (avec code de session).
- `GET  /api/device/status` — état pour la page « État ».

**Authentification** : jeton par appareil (ESP32) + code de session pour la prise de contrôle. Pas de comptes utilisateurs au départ (D2).

**Sources externes consommées** (ne sont pas ton API) : Celestrak (TLE), fichier éphémérides JPL (via Skyfield), catalogue d'étoiles, images/textes libres.

## 7. Contraintes techniques et modes de déploiement

### 7.1 Mode 1 - Local (maintenant, développement et tests)

Téléphone, ESP32 et serveur Django (Raspberry Pi) sont **tous sur le même réseau wifi** (ta box). Le téléphone accède au serveur via son adresse locale, l'ESP32 l'interroge sur ce même réseau. Fonctionne uniquement à portée de ce wifi. C'est le mode de départ.

### 7.2 Mode 2 - Distant (plus tard, usage en extérieur)

Le serveur est rendu accessible depuis internet via un **tunnel** (Cloudflare Tunnel, ou Tailscale), sans exposer directement la box.

- **Principe du tunnel** : le Raspberry Pi ouvre lui-même une connexion sortante permanente vers un service intermédiaire public (ex. Cloudflare). Cette connexion sortante n'est pas bloquée par la box. Le service fournit une adresse web publique ; les requêtes venues de l'extérieur transitent par ce « tuyau » jusqu'au Pi. La box n'a jamais à accepter de connexion entrante.
- Le téléphone accède alors au serveur en 4G ou sur n'importe quel wifi.
- L'ESP32 y accède via le **hotspot 4G du téléphone** : c'est le seul réseau qui suit l'utilisateur partout sans reconfiguration.

### 7.3 Configuration wifi de l'ESP32 depuis un autre endroit

Au démarrage, si l'ESP32 ne reconnaît aucun réseau enregistré, il **crée son propre point d'accès wifi temporaire** (ex. `IndexStellaire-Setup`).

1. Le téléphone se connecte à ce point d'accès comme à un routeur classique (via les réglages wifi du téléphone, pas via l'app).
2. Une **page de configuration minimaliste**, servie directement par l'ESP32 (pas par le serveur Django, il n'a pas encore internet à ce stade), s'ouvre automatiquement ou via une adresse fixe (ex. `192.168.4.1`).
3. Cette page liste les réseaux wifi détectés à proximité (+ option hotspot du téléphone), avec un champ mot de passe.
4. Une fois validé, l'ESP32 redémarre connecté à ce réseau et devient joignable normalement par le serveur.

**Deux interfaces distinctes** : la page de configuration (servie par l'ESP32, minimaliste, utilisée une fois par nouveau réseau) et l'app Index Stellaire (servie par le serveur Django, usage courant). Elles ne partagent ni code ni hébergement. Ce mécanisme fonctionne sur Android **et** iPhone (pas de Bluetooth requis).

### 7.4 Autres contraintes

- **C1** HTTPS obligatoire (push web, service worker, géolocalisation, sécurité API), pertinent surtout en mode 2.
- **C3** Communication appareil : **HTTP(S) polling** (pas de WebSocket permanent).
- **C4** BLE (pointage local direct) : mode Android/Chrome uniquement, secondaire, indépendant de la configuration wifi (7.3).
- **C5** App conçue en **PWA** (manifest + service worker) dès le départ.

## 8. Exigences non fonctionnelles

- **N1 Latence** : après calibration, un ordre de pointage doit aboutir en **~20–30 s** maximum.
- **N2 Autonomie** : suivi seul **48 h** (jusqu'à 72 h), puis retour normal.
- **N3 Précision** : niveau télescope (arcminute), dépend surtout du matériel/firmware ; l'app envoie des cibles cohérentes avec cet objectif.
- **N4 Langue** : **français**.
- **N5 Thème** : **mode nocturne** (fond sombre, idéalement variante rouge pour préserver la vision d'obscurité).
- **N6 Robustesse hors-ligne** : l'app gère proprement l'appareil déconnecté (état grisé, dernière donnée connue).

## 9. Ordre de développement conseillé

1. Squelette Django (`ciel`, `appareil`) + PWA + thème nocturne.
2. Carte du ciel (d3-celestial) + positions Skyfield + filtres + fiches minimales (F1–F4, F36, F7, F10, F12).
3. **API + appareil simulé** (mock) : pointer/arrêter/état sans matériel (F17–F19, F25, F28–F32).
4. Branchement de l'appareil réel + configuration wifi + mode autonome (F37, F33–F35).
5. Enrichissement : événements, notifications, fiches enrichies, file d'observation (F13–F16, F11, F22).
6. Durcissement : accès distant sécurisé (mode 2, tunnel), sécurité du code de session, télémétrie détaillée.

> Développer d'abord contre un **appareil simulé** permet de finir une app fonctionnelle même sans le matériel prêt.

## 10. Décisions matérielles reprises (contexte)

Pour cohérence app/matériel, rappel de ce qui est déjà acté côté hardware : structure sphère armillaire, 2 axes (azimut + élévation), moteurs pas à pas + slip ring (rotation continue azimut), ESP32 + STM32 (liaison UART).

*(Le reste du matériel, capteurs, drivers, alimentation, sera précisé plus tard et n'est pas figé ici.)*

## 11. Décisions prises et points ouverts

### Décisions prises

- **D1 Cible plutôt qu'angles** : l'app envoie une **cible** (objet ou coordonnées) ; le STM32 fait les calculs de suivi.
- **D2 Utilisateurs** : mono-utilisateur au départ (Maui), sans comptes. D'autres personnes utilisent leur téléphone en se connectant avec le **code de session** (F28).
- **D3 Laser** : usage **en intérieur uniquement**. Pas de verrouillage Soleil au MVP (F9 sans objet).
- **D4 Carte** : **d3-celestial** (canvas).
- **D5 Autonomie** : **48 h** de suivi autonome, l'appareil calculant seul avec son **propre GPS**.
- **D6 Événements** : **calculés en interne** (Skyfield) ; complétés par une source externe vérifiée si internet est disponible (v2).
- **D7 Sources** : chaque contenu ajouté (fiche, événement, image) est **recherché et vérifié à la source au moment de l'ajout**, source et licence notées.
- **D8 Déploiement** : **mode 1 (local, même wifi)** maintenant ; **mode 2 (serveur exposé via tunnel + hotspot 4G)** plus tard.
- **D9 Configuration wifi** : via **point d'accès temporaire de l'ESP32** et page de configuration servie par l'appareil (pas de Bluetooth requis).

### Points encore ouverts

- **P8** Détection de l'embout côté matériel (comment l'appareil identifie l'embout monté), nécessaire seulement pour F21.
- Comportement exact du **code de session** : durée de validité, régénération, nombre d'essais (surtout en mode 2, serveur exposé).
- Protection de l'accès quand le serveur sera exposé hors du domicile (mode 2).
- Comportement précis au-delà de 48 h (F34).