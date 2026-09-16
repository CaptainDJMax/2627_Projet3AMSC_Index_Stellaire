# Projet : Index Stellaire

## 🌌 Description du Projet
AstroPointer est un bras mécanique autonome et esthétique, conçu pour pointer en temps réel vers un objet céleste défini via une application mobile ou web. Qu'il s'agisse d'une planète, d'une étoile, de la Station Spatiale Internationale (ISS) ou d'une galaxie, le bras suit l'objet en continu. 

S'il est sous l'horizon, le bras pointera vers le sol. Conçu avec des matériaux nobles, c'est autant un outil de vulgarisation scientifique qu'un objet d'art cinétique d'intérieur.

---

## 📋 Cahier des Charges & Défis Techniques

Voici la liste des exigences du projet, accompagnées des choix matériels recommandés et des défis techniques à anticiper.

### 1. Suivi (Tracking) d'un astre à 360° en continu
**Description :** Le bras doit pouvoir cibler un objet céleste de manière dynamique et compenser la rotation de la Terre en temps réel, sans limite de rotation.
- **Matériel :** Un moteur de base pour l'axe Azimut (horizontal), un moteur pour l'axe Élévation (vertical), et un **collecteur tournant (slip ring)** placé au centre de l'axe de rotation.
- **Difficulté :** La rotation infinie sur l'axe vertical demande d'intégrer ce slip ring pour faire passer les câbles (alimentation et données) du socle vers le bras sans qu'ils ne s'entortillent et se rompent.

### 2. Calibrage automatique via IMU et GNSS/GPS
**Description :** L'utilisateur pose l'objet, l'allume, et le système détermine son emplacement, l'heure exacte et son orientation spatiale (Nord, assiette) sans intervention.
- **Matériel :** Un module GPS (ex: u-blox NEO-M8N pour une fixation rapide) et une centrale inertielle 9 axes (IMU) avec processeur de fusion de données intégré (ex: BNO085 ou BNO055).
- **Difficulté :** Le magnétomètre de l'IMU (boussole) est extrêmement sensible aux métaux ferreux et aux champs magnétiques des moteurs. Il faudra placer l'IMU le plus loin possible des moteurs (au bout du bras) et prévoir un algorithme de calibration pour compenser le métal environnant (fer doux/fer dur).

### 3. Facilité de transport (Pliable)
**Description :** Le bras doit se plier pour rentrer dans un boîtier de transport dédié.
- **Matériel :** Articulations sur roulements à billes de précision et **encodeurs magnétiques absolus** (ex: AS5600) sur chaque axe critique.
- **Difficulté :** Si le bras se plie alors qu'il est éteint, le système doit savoir exactement dans quelle posture il se trouve à l'allumage. Les encodeurs absolus sont obligatoires ici, car ils gardent en mémoire la position physique exacte, contrairement aux encodeurs relatifs.

### 4. Design Élégant et Matériaux Nobles (Laiton)
**Description :** Finition haut de gamme pour s'intégrer comme un objet de décoration intérieur.
- **Matériel :** Laiton massif pour le socle, tubes en aluminium anodisé (aspect laiton) ou en fibre de carbone recouverts de laiton pour les parties mobiles. Visserie invisible.
- **Difficulté :** Le laiton est très dense et lourd. Un bras entièrement en laiton massif exigera des moteurs très puissants, donc volumineux, bruyants et gourmands en énergie. Il faut impérativement tricher sur les parties mobiles en utilisant des matériaux légers plaqués.

### 5. Silencieux
**Description :** Les mouvements du bras doivent être imperceptibles auditivement.
- **Matériel :** Pilotes de moteurs (drivers) ultra-silencieux (ex: Trinamic TMC2209 avec technologie StealthChop) pour moteurs pas-à-pas, ou contrôleurs FOC (SimpleFOC) pour moteurs Brushless. Amortisseurs de vibrations (silentblocs) entre les moteurs et le châssis.
- **Difficulté :** Isoler acoustiquement la transmission mécanique (engrenages ou courroies). Les courroies synchrones en néoprène sont généralement beaucoup plus silencieuses que les engrenages métalliques.

### 6. Alimentation : Batterie et Secteur (10h d'autonomie)
**Description :** Fonctionnement mixte, avec une batterie customisée intégrée.
- **Matériel :** Pack de cellules Lithium-Ion (ex: cellules 18650 ou 21700 haute capacité), carte BMS (Battery Management System) pour la sécurité de charge/décharge, et un circuit de bascule automatique batterie/secteur.
- **Difficulté :** Le dimensionnement de la batterie. Les moteurs en position de maintien consomment de l'énergie en permanence pour contrer la gravité. Il faudra équilibrer mécaniquement le bras (ajouter des contrepoids discrets) pour que les moteurs forcent le moins possible.

### 7. Interface et Contrôle
**Description :** Bouton ON/OFF physique premium. L'interface principale est une application connectée via API.
- **Matériel :** Microcontrôleur **ESP32** (qui intègre nativement le WiFi et le Bluetooth BLE), et un interrupteur à levier ou un bouton poussoir capacitif en métal intégré au design du socle.
- **Difficulté :** Développer le backend logiciel sur l'ESP32 pour qu'il puisse héberger une API locale (serveur Web embarqué) ou se connecter au WiFi de la maison de manière transparente via le Bluetooth du téléphone.

### 8. Fonctionnement hors-ligne prolongé (72h)
**Description :** Le bras doit pouvoir suivre une cible pendant 72 heures sans connexion réseau.
- **Matériel :** Module **RTC (Real-Time Clock)** de très haute précision compensé en température (ex: DS3231) avec sa propre pile bouton de sauvegarde (CR2032).
- **Difficulté :** La dérive temporelle. Sans internet (NTP) pour resynchroniser l'horloge, un microcontrôleur standard perd plusieurs secondes par jour. En astronomie, une erreur de quelques secondes fausse complètement le pointage, d'où l'obligation absolue d'un module RTC dédié.

### 9. Embouts Interchangeables
**Description :** La terminaison du bras accueille un "doigt mécanique", un pointeur laser, etc.
- **Matériel :** Connecteur à fixation rapide (aimants en néodyme avec détrompeur ou système à baïonnette), et connecteurs **Pogo Pins** (broches à ressort) pour transmettre le courant électrique au module laser.
- **Difficulté :** Transmettre le courant à l'embout laser sans fil apparent et s'assurer que l'embout se centre toujours parfaitement sur l'axe optique/mécanique à chaque changement.

### 10. Boucle d'asservissement 
**Description :** Le système corrige lui-même ses erreurs de position (heurt, perte de pas).
- **Matériel :** Encodeurs rotatifs haute résolution (ex: AS5048A avec 14 bits de résolution) fixés directement sur l'axe des moteurs.
- **Difficulté :** L'intégration logicielle. Il faut implémenter un correcteur PID (Proportionnel, Intégral, Dérivé) dans le code pour que le microcontrôleur compare des milliers de fois par seconde la position théorique calculée avec la position réelle lue par l'encodeur, et qu'il corrige le mouvement sans créer d'oscillations.

---

## 🛠️ Stack Électronique de Base (Résumé)
* **Cerveau :** ESP32
* **Temps & Espace :** GPS u-blox, IMU BNO085, RTC DS3231
* **Mouvement :** Moteurs + Drivers Trinamic TMC2209 + Slip Ring
* **Capteurs position :** Encodeurs magnétiques absolus (AS5600 / AS5048A)
