# Cahier des charges — Application Index Stellaire

> **Index Stellaire** : bras robotique à 2 axes (sphère armillaire) pointant en temps réel vers des astres. Ce document décrit **l'application logicielle** (web/PWA Django) et son **API**. Le matériel (PCB, moteurs, alimentation) est traité ailleurs ; il n'est repris ici que là où il contraint le logiciel.

- **Version** : 0.1 (brouillon de travail)
- **Auteur** : Maui
- **Statut** : à itérer

---

## 1. Objectif

Piloter et accompagner le bras Index Stellaire : choisir un astre, le faire pointer, découvrir ce qui est observable depuis sa position, et suivre l'état de l'appareil. L'application doit fonctionner **hors du réseau Wi-Fi domestique** (via un serveur accessible à distance) et laisser l'appareil **autonome jusqu'à 48 h** sans elle.

## 2. Périmètre et priorités

Chaque fonctionnalité est étiquetée :

- **[MVP]** — première version qui fonctionne de bout en bout
- **[v2]** — amélioration prévue après le MVP
- **[Futur]** — envisagé, non planifié

**Objectif de la v1 : une application qui marche à peu près de bout en bout**, quitte à revenir la durcir ensuite. On garde en tête pendant la conception l'endroit où brancher l'authentification / l'accès distant, sans le finaliser tout de suite.

## 3. Acteurs et plateformes

| Acteur | Rôle |
|---|---|
| Utilisateur (observateur) | Consulte le ciel, choisit et pointe des astres, contrôle l'appareil |
| Appareil (ESP32 + STM32) | Interroge le serveur, exécute le pointage, remonte sa télémétrie |
| Serveur Django | Calcule les positions, sert la carte, expose l'API, relaie les commandes |

**Plateformes cibles** : navigateur web responsive, installable en **PWA** (écran d'accueil). Contraintes à intégrer :

- **BLE navigateur = Android/Chrome (et desktop Chrome/Edge) uniquement.** Pas de Web Bluetooth sur iOS ni Firefox. → Le **contrôle principal passe par le serveur en HTTP(S)** (fonctionne partout). Le **BLE reste un mode local optionnel** pour Android.
- **Notifications push web** : nécessitent la PWA installée à l'écran d'accueil (iOS ≥ 16.4) et **HTTPS**.

## 4. Architecture logicielle

### 4.1 Projet Django, deux apps

- **`ciel`** — contenu et calculs astronomiques : catalogues, constellations, positions (Skyfield), événements, fiches objets.
- **`appareil`** — communication avec l'appareil : appairage, jetons, sessions de contrôle, file de commandes, télémétrie.

Un seul projet, une seule base, un seul serveur. Séparation logique uniquement.

### 4.2 Briques externes

| Besoin | Choix retenu | Rôle |
|---|---|---|
| Calcul astro serveur | **Skyfield** (Python) | RA/Dec, alt/az topocentrique, lever/coucher, satellites (SGP4) |
| Éphémérides planètes | **JPL DE421/DE440** (fichier `.bsp`, chargé par Skyfield) | Positions Soleil, Lune, planètes |
| TLE satellites (ISS…) | **Celestrak** | Éléments orbitaux pour SGP4 |
| Carte du ciel (navigateur) | **d3-celestial** (canvas) *(ou Aladin Lite)* | Rendu interactif étoiles/constellations/DSO |
| Catalogue d'étoiles | Données de d3-celestial / base type HYG | Alimente la carte et la recherche |
| PWA / push | Service worker + Web Push (VAPID) | Installation + notifications |

### 4.3 Répartition des calculs (serveur ↔ STM32)

- **Serveur** : calcule la position d'un astre pour l'instant et la position données (alt/az), fournit à l'appareil de quoi suivre en autonomie (identifiant + éphémérides / TLE pré-chargés). Gère la carte et les fiches.
- **STM32** : refait/affine les calculs en temps réel pour le suivi fin, et **continue seul en cas de déconnexion** à partir de la dernière cible connue, de son RTC et du GPS embarqué (jusqu'à 48 h).
- **L'application envoie une cible** (astre à suivre ou coordonnées), **pas des angles bruts** — l'appareil reste maître du suivi. *(À confirmer : voir §11.)*

## 5. Fonctionnalités

### 5.1 Carte du ciel `ciel`

- **F1 [MVP]** Carte du ciel interactive en canvas, style soigné cohérent avec l'univers du projet (fond nocturne, étoiles par magnitude, lignes de constellations, Voie lactée).
- **F2 [MVP]** Affichage centré sur la **position GPS réelle** et l'heure courante.
- **F3 [MVP]** Sélection d'un objet par clic sur la carte → ouverture de sa fiche.
- **F4 [MVP]** Bouton **Pointer** / **Arrêter** depuis la carte ou la fiche.
- **F5 [v2]** Affichage/masquage des dessins artistiques de constellations (ex. Cancer, Capricorne).
- **F6 [Futur]** Mode boussole / réalité augmentée (capteurs du téléphone) — **exclu du MVP**.

### 5.2 Objets pris en charge

- **F7 [MVP]** Étoiles (seuil de magnitude réglable), planètes, Lune, Soleil, ISS.
- **F8 [v2]** Autres satellites, comètes, objets Messier/NGC.
- **F9 [MVP]** **Sécurité Soleil** : si un embout laser/optique est présent, le pointage du Soleil est verrouillé ou soumis à confirmation explicite. *(Politique exacte à définir : §11.)*

### 5.3 Fiches objets

- **F10 [MVP]** Fiche par objet : nom, type, magnitude, coordonnées, visibilité ce soir (lever/coucher, hauteur max).
- **F11 [v2]** Contenu enrichi : description **issue de sources fiables**, mythologie, image **libre de droits**.
  - Sources images à privilégier : NASA/ESA, Wikimedia Commons (vérifier licence par image).
  - Sources texte : à choisir parmi des références fiables et citées ; import semi-manuel plutôt que génération.

### 5.4 Recherche

- **F12 [MVP]** Recherche d'un objet par nom, avec accès direct à sa fiche et au pointage.

### 5.5 Événements à l'œil nu

- **F13 [v2]** Liste des **événements observables ce soir depuis la position réelle** : conjonctions, essaims de météores, passages ISS, phases de Lune, etc.
- **F14 [v2]** Données **issues d'une source fiable** (calcul Skyfield côté serveur et/ou source externe vérifiée).
- **F15 [v2]** Chaque événement renvoie à l'objet concerné et permet de le pointer.
- **F16 [v2]** **Notifications** d'événements (via Web Push, PWA installée).

### 5.6 Pointage et contrôle de l'appareil `appareil`

- **F17 [MVP]** **Pointage simple** : l'utilisateur choisit un objet (ou une cible personnalisée), l'appareil pointe et suit. Un seul mode pour l'instant.
- **F18 [MVP]** **Cible personnalisée** : pointer des coordonnées arbitraires, y compris **sous l'horizon** (direction géométrique réelle à travers la Terre), choix fait depuis l'app.
- **F19 [MVP]** **Position de repos (parking)** quand aucune cible n'est active.
- **F20 [MVP]** L'app **ne gère pas les embouts** : elle envoie des ordres de pointage, le firmware s'occupe du reste. Le changement d'embout (changement de pin) est **détecté côté firmware** via l'encodeur d'adresse 2 bits ; côté app, aucun impact au MVP.
- **F21 [v2]** Affichage de l'embout détecté (lecture seule) et, plus tard, contrôle (laser on/off, couleur).
- **F22 [v2]** Visite guidée / file d'observation enchaînant plusieurs objets, avec horaires.

### 5.7 Calibration

- **F23 [MVP]** Bouton **« Calibrer »** lançant la procédure (alignement au démarrage). Pas de joystick virtuel au MVP.
- **F24 [Futur]** Réglage fin manuel (joystick virtuel dans l'app) — le joystick physique 5 pins reste la voie matérielle.

### 5.8 État de l'appareil (page dédiée)

- **F25 [MVP]** Page **« État »** séparée : niveau de batterie, fix GPS, connecté/déconnecté, dernière synchronisation, dernière cible pointée.
- **F26 [v2]** Télémétrie détaillée : température drivers, angles encodeurs, précision estimée, erreurs.
- **F27 [Futur]** Mise à jour firmware OTA depuis l'app.

### 5.9 Sessions et multi-utilisateur

- **F28 [MVP]** **Plusieurs personnes peuvent se connecter à l'appareil** (via un **code**), mais **une seule contrôle à la fois**.
- **F29 [MVP]** Bouton **« Prendre le contrôle »** : reprend la main sur la session en cours.
- **F30 [MVP]** À la reprise, le nouvel utilisateur **voit le dernier objet pointé** et peut le changer.
- **F31 [MVP]** **Interface connectée/déconnectée** : boutons d'action grisés quand l'appareil est hors ligne.
- **F32 [MVP]** **Heartbeat** pour détecter l'état en ligne/hors ligne.

### 5.10 Mode autonome

- **F33 [MVP]** L'appareil **suit sa cible seul jusqu'à 48 h** sans réseau ni app, à partir de la dernière cible, du RTC et du GPS.
- **F34 [MVP]** Au-delà (jusqu'à ~72 h max), puis retour à un comportement normal / parking.
- **F35 [MVP]** À la reconnexion, l'app récupère l'état réel (dernière cible, batterie, position).

## 6. API (celle que tu construis)

API REST servie par Django, consommée par l'app web **et** par l'ESP32. Esquisse à affiner :

**Côté appareil (ESP32 → serveur, polling HTTP/HTTPS)**
- `POST /api/device/heartbeat` — signale l'état (batterie, GPS, cible en cours) et récupère la prochaine commande.
- `GET  /api/device/command` — commande courante à exécuter (cible + éphémérides/TLE nécessaires au suivi autonome).
- `POST /api/device/telemetry` — remontée de télémétrie détaillée.

**Côté application (navigateur → serveur)**
- `GET  /api/sky/objects?lat=&lon=&t=` — objets visibles + positions alt/az.
- `GET  /api/objects/{id}` — fiche objet.
- `GET  /api/search?q=` — recherche.
- `GET  /api/events?lat=&lon=&date=` — événements du soir.
- `POST /api/point` — demander le pointage d'une cible (objet ou coordonnées).
- `POST /api/stop` — arrêt / retour au parking.
- `POST /api/calibrate` — lancer la calibration.
- `POST /api/control/take` — prendre le contrôle (avec code).
- `GET  /api/device/status` — état pour la page « État ».

**Authentification** : jeton par appareil (ESP32) + code de session pour la prise de contrôle. Comptes utilisateurs : *à décider (§11)*.

**Sources externes consommées** (ne sont pas ton API) : Celestrak (TLE), fichier éphémérides JPL (via Skyfield), catalogue d'étoiles, images/textes libres.

## 7. Contraintes techniques

- **C1** HTTPS obligatoire (push web, service worker, géolocalisation, sécurité API).
- **C2** Serveur : Raspberry Pi **chez toi** pour démarrer. Pour l'accès **hors du domicile** : tunnel (Cloudflare Tunnel / Tailscale) ou petit VPS. À traiter avant l'usage extérieur.
- **C3** Communication appareil : **HTTP(S) polling** (pas de WebSocket permanent). Hotspot 4G du téléphone en extérieur.
- **C4** **BLE** : mode local **Android/Chrome uniquement**, secondaire par rapport au chemin serveur.
- **C5** App conçue en **PWA** (manifest + service worker) dès le départ, pour l'installation et les notifications.

## 8. Exigences non fonctionnelles

- **N1 Latence** : après calibration, un ordre de pointage doit aboutir en **~20–30 s** maximum.
- **N2 Autonomie** : suivi seul **48 h** (jusqu'à 72 h), puis retour normal.
- **N3 Précision** : niveau télescope (arcminute) — dépend surtout du matériel/firmware ; l'app envoie des cibles cohérentes avec cet objectif.
- **N4 Langue** : **français**.
- **N5 Thème** : **mode nocturne** (fond sombre, idéalement variante rouge pour préserver la vision d'obscurité).
- **N6 Robustesse hors-ligne** : l'app gère proprement l'appareil déconnecté (état grisé, dernière donnée connue).

## 9. Ordre de développement conseillé

1. Squelette Django (`ciel`, `appareil`) + PWA + thème nocturne.
2. Carte du ciel (d3-celestial) + positions Skyfield + fiches minimales (F1–F4, F7, F10, F12).
3. **API + appareil simulé** (mock) : pointer/arrêter/état sans matériel (F17–F19, F25, F28–F32).
4. Branchement de l'appareil réel + mode autonome (F33–F35).
5. Enrichissement : événements, notifications, fiches enrichies, file d'observation (F13–F16, F11, F22).
6. Durcissement : accès distant sécurisé, auth, télémétrie détaillée.

> Développer d'abord contre un **appareil simulé** permet de finir une app fonctionnelle même sans le matériel prêt.

## 10. Décisions matérielles reprises (contexte)

Pour cohérence app/matériel, rappel de ce qui est déjà acté côté hardware : structure sphère armillaire, 2 axes (azimut + élévation), moteurs pas à pas + slip ring (rotation continue azimut), ESP32 + STM32 (UART), GPS u-blox, IMU BNO085 (mode UART via slip ring), RTC DS3231, drivers TMC2209, encodeurs AS5600/AS5048A, alimentation 24 V via USB-PD EPR. Encodeur d'adresse 2 bits pour identifier l'embout.

## 11. Points à trancher / hypothèses

- **P1** L'app envoie-t-elle une **cible** (hypothèse retenue) ou parfois des **angles bruts** ? Confirmer.
- **P2** **Comptes utilisateurs** : mono-utilisateur (toi) au début, ou multi-comptes dès le MVP ? Un seul appareil ou plusieurs par compte ?
- **P3** **Politique Soleil** : verrouillage total avec laser, ou confirmation explicite ? Extinction laser sous une certaine élévation ?
- **P4** Carte : **d3-celestial** (canvas, léger) vs **Aladin Lite** (images réelles) — trancher selon le rendu voulu.
- **P5** Autonomie : cible ferme **48 h** confirmée ; comportement exact au-delà à préciser.
- **P6** Événements : tout calculer avec Skyfield, ou combiner avec une source externe vérifiée ?
- **P7** Sources images/textes des fiches : liste de sources libres validée à figer.
