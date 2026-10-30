(function () {
  "use strict";

  const carte = document.getElementById("carte");
  const lieu = JSON.parse(document.getElementById("donnees-lieu").textContent);
  const POSITION = [lieu.latitude, lieu.longitude];

  // ===========================================================================
  // 1. Mise en page : la carte occupe toute la zone visible (la vue « fenêtre »)
  // ===========================================================================

  const MARGE = 16;
  const LARGEUR_PANNEAU = 360; // px : panneau de la fiche, à droite, sur grand écran
  const GRAND_ECRAN = window.matchMedia("(min-width: 900px)");

  // Zone réservée au disque : tout l'écran sur téléphone, à gauche du panneau sur grand écran.
  // Le panneau garde sa place même fermé : le ciel ne bouge pas quand on ouvre la fiche.
  function zone() {
    const panneau = GRAND_ECRAN.matches ? LARGEUR_PANNEAU + 3 * MARGE : 0;
    return { largeur: window.innerWidth - panneau, hauteur: window.innerHeight };
  }

  // Le canevas est un carré assez grand pour couvrir l'écran quelle que soit la direction
  // regardée ; le conteneur #carte, lui, a exactement la taille de la zone visible.
  function taille() {
    const z = zone();
    return Math.ceil(Math.hypot(z.largeur, z.hauteur)) + 2;
  }

  function placer() {
    const z = zone();
    carte.style.left = "0px";
    carte.style.top = "0px";
    carte.style.width = z.largeur + "px";
    carte.style.height = z.hauteur + "px";
    return taille();
  }

  // Remet le conteneur à la taille de la zone et centre le canevas dedans.
  // Appelée après chaque dessin : la bibliothèque redimensionne le conteneur à sa façon.
  function placerCanevas() {
    const z = zone();
    carte.style.width = z.largeur + "px";
    carte.style.height = z.hauteur + "px";
    const canevas = carte.querySelector("canvas");
    if (!canevas) return;
    const t = taille();
    // Taille d'affichage = taille du dessin. Sur un écran haute densité (téléphone : ×2, ×3), la
    // bibliothèque multiplie les pixels internes du canevas ; sans ces deux lignes, l'image
    // s'affichait 2 ou 3 fois trop grande, le centre de la vue sortait de l'écran et les touchers
    // tombaient à côté des astres.
    canevas.style.width = t + "px";
    canevas.style.height = t + "px";
    canevas.style.position = "absolute";
    canevas.style.left = Math.round((z.largeur - t) / 2) + "px";
    canevas.style.top = Math.round((z.hauteur - t) / 2) + "px";
  }

  // ===========================================================================
  // 2. L'horloge virtuelle : l'heure affichée par la carte. Elle suit le temps
  //    réel (×1) ou s'accélère / se met en pause / saute, pour voir le ciel tourner.
  // ===========================================================================

  const horloge = {
    virtuel: Date.now(), // l'instant affiché, en ms depuis 1970 (UTC)
    vitesse: 1, // 0 = pause, 1 = temps réel, 60 = 1 min par seconde...
    dernierTop: Date.now(),
  };

  const PERIODE_TIC = 100; // ms entre deux tics de l'horloge
  const PERIODE_CARTE_DIRECT = 10000; // à ×1 le ciel bouge trop peu pour redessiner plus souvent
  const PERIODE_CARTE_ACCELERE = 100;
  const OBJETS_PERIMES_APRES = 5 * 60 * 1000; // ms virtuelles avant de recalculer planètes et Lune
  const DELAI_MINI_REQUETES = 500; // ms réelles entre deux appels à l'API

  let derniereMajCarte = 0;

  function avancerHorloge() {
    const top = Date.now();
    let delta = top - horloge.dernierTop;
    // Onglet resté en arrière-plan : on ne fait pas un énorme saut en accéléré
    if (horloge.vitesse !== 1 && delta > 1000) delta = PERIODE_TIC;
    horloge.virtuel += delta * horloge.vitesse;
    horloge.dernierTop = top;
  }

  // Dit à d3-celestial de recalculer le ciel pour l'instant virtuel : la carte
  // se recentre sur le zénith, les étoiles « tournent ».
  function majCarte() {
    Celestial.skyview({ date: new Date(horloge.virtuel) });
    appliquerVue(); // la direction regardée (azimut, hauteur) tourne avec le ciel
    derniereMajCarte = Date.now();
  }

  function enDirect() {
    return horloge.vitesse === 1 && Math.abs(horloge.virtuel - Date.now()) < 2000;
  }

  function tic() {
    avancerHorloge();
    afficherHeure();
    majFiche();
    majBoussole();
    if (horloge.vitesse !== 0) {
      const periode = horloge.vitesse === 1 ? PERIODE_CARTE_DIRECT : PERIODE_CARTE_ACCELERE;
      if (Date.now() - derniereMajCarte >= periode) majCarte();
    }
    if (objetsPerimes()) chargerObjets();
    const brasBouge = animerBras(); // le réticule glisse vers sa nouvelle position
    if (brasBouge || satellitesBougent()) Celestial.redraw(); // 6.3 : l'ISS avance sur la carte
  }

  // ===========================================================================
  // 3. Affichage de l'heure et panneau de contrôle
  // ===========================================================================

  const fmtHeure = new Intl.DateTimeFormat("fr-FR", { hour: "2-digit", minute: "2-digit", timeZone: lieu.fuseau });
  const fmtHeureSec = new Intl.DateTimeFormat("fr-FR", {
    hour: "2-digit", minute: "2-digit", second: "2-digit", timeZone: lieu.fuseau,
  });
  const fmtDate = new Intl.DateTimeFormat("fr-FR", {
    weekday: "long", day: "numeric", month: "long", year: "numeric", timeZone: lieu.fuseau,
  });

  const elBouton = document.getElementById("btn-temps");
  const elHeure = document.getElementById("heure");
  const elPanneau = document.getElementById("panneau-temps");
  const elPanneauHeure = document.getElementById("panneau-heure");
  const elPanneauDate = document.getElementById("panneau-date");

  function afficherHeure() {
    const d = new Date(horloge.virtuel);
    elHeure.textContent = fmtHeure.format(d);
    elBouton.classList.toggle("decale", !enDirect());
    if (!elPanneau.hidden) {
      elPanneauHeure.textContent = fmtHeureSec.format(d);
      elPanneauDate.textContent = fmtDate.format(d);
      elPanneau.querySelectorAll("[data-vitesse]").forEach(function (b) {
        b.setAttribute("aria-pressed", String(Number(b.dataset.vitesse) === horloge.vitesse));
      });
    }
  }

  // --- Les panneaux du bas (temps, calques, recherche) : un seul ouvert à la fois.
  // La fiche d'objet, elle, passe par selectionner().
  const elBtnCalques = document.getElementById("btn-calques");
  const elPanCalques = document.getElementById("panneau-calques");
  const elBtnRecherche = document.getElementById("btn-recherche");
  const elPanRecherche = document.getElementById("panneau-recherche");
  const elChampRecherche = document.getElementById("recherche-champ");
  const elListeRecherche = document.getElementById("recherche-liste");
  const elBtnBoussole = document.getElementById("btn-boussole");
  const elBoussole = document.getElementById("boussole");
  const elBoussoleDirection = document.getElementById("boussole-direction");
  const elBoussoleHauteur = document.getElementById("boussole-hauteur");
  const elEtatBouton = document.getElementById("etat-appareil"); // la pastille, qui ouvre son panneau
  const elPanAppareil = document.getElementById("panneau-appareil");
  const elPanCode = document.getElementById("panneau-code"); // Partie 5 : code de pilotage
  const elPanPoint = document.getElementById("panneau-point"); // Partie 8.4 : point du ciel
  const elPanVisite = document.getElementById("panneau-visite"); // Partie 8.5 : visite guidée
  const elPanJournal = document.getElementById("panneau-journal"); // Partie 9 : journal
  const elPanObservation = document.getElementById("panneau-observation");
  const elBtnEvenements = document.getElementById("btn-evenements"); // Partie 7
  const elPanEvenements = document.getElementById("panneau-evenements");
  const elCodeFormulaire = document.getElementById("code-formulaire");
  const elCodeChamp = document.getElementById("code-champ");
  const elCodeValider = document.getElementById("code-valider");
  const elCodeMessage = document.getElementById("code-message");

  const calques = { constellations: true, illustrations: true, voieLactee: true, etiquettesEtoiles: true, cielProfond: true };

  // Partie 8.4 (F36) : filtres des astres de la base et magnitude limite des étoiles de fond.
  // Gardés dans ce navigateur (localStorage) ; la page marche aussi sans (navigation privée).
  const CLE_FILTRES = "index-stellaire-filtres";
  const filtres = { planetes: true, etoiles: true, satellites: true, magnitude: 6 };
  try {
    const garde = JSON.parse(localStorage.getItem(CLE_FILTRES) || "null");
    if (garde && typeof garde === "object") {
      ["planetes", "etoiles", "satellites"].forEach(function (k) {
        if (typeof garde[k] === "boolean") filtres[k] = garde[k];
      });
      if ([4, 5, 6].indexOf(garde.magnitude) !== -1) filtres.magnitude = garde.magnitude;
    }
  } catch (erreur) { /* stockage indisponible : filtres par défaut */ }

  function garderFiltres() {
    try { localStorage.setItem(CLE_FILTRES, JSON.stringify(filtres)); } catch (erreur) { /* tant pis */ }
  }

  // Un astre de la base passe-t-il les filtres ? (carte, toucher et recherche)
  const FILTRE_DE_CATEGORIE = {
    planete: "planetes", lune: "planetes", soleil: "planetes", // Partie 10 : Soleil
    etoile: "etoiles", amas: "etoiles", ciel_profond: "etoiles", // Partie 10 : ciel profond
    satellite: "satellites",
  };
  function objetAffiche(o) {
    const f = FILTRE_DE_CATEGORIE[o.categorie];
    return !f || filtres[f];
  }
  let viseurActif = false; // petit viseur au centre de la vue
  let actionEnAttente = null; // Partie 5 : l'action (Pointer, Arrêter) qui attend le code
  let ficheAvantCode = null; // la fiche ouverte avant la demande du code, rouverte ensuite

  // nom : "temps", "calques", "recherche", ou null pour tout fermer
  function ouvrir(nom) {
    [
      ["temps", elPanneau, elBouton],
      ["calques", elPanCalques, elBtnCalques],
      ["recherche", elPanRecherche, elBtnRecherche],
      ["appareil", elPanAppareil, elEtatBouton],
      ["code", elPanCode, null],
      ["evenements", elPanEvenements, elBtnEvenements],
      ["point", elPanPoint, null],
      ["visite", elPanVisite, null],
      ["journal", elPanJournal, null],
      ["observation", elPanObservation, null],
    ].forEach(function (p) {
      const ouvert = p[0] === nom;
      p[1].hidden = !ouvert;
      if (p[2]) p[2].setAttribute("aria-expanded", String(ouvert));
    });
    if (nom !== "code") actionEnAttente = null; // fermer le panneau du code annule l'action en attente
    if (nom !== "point" && pointChoisi) { // 8.4 : le repère du point disparaît avec son panneau
      pointChoisi = null;
      Celestial.redraw();
    }
    majEtatPanneaux();
  }

  // Ouvre un panneau du bas, et ferme la fiche s'il y en a une
  function ouvrirSeul(nom) {
    ouvrir(nom);
    if (selection !== null) selectionner(null);
  }

  // Sur téléphone, la pastille d'état se cache quand la fiche ou la recherche monte du bas
  function majEtatPanneaux() {
    document.body.classList.toggle("panneau-ouvert", selection !== null || !elPanRecherche.hidden);
    // N'importe quel panneau en bas de l'écran (sur téléphone, les boutons de zoom se cachent)
    document.body.classList.toggle("panneau-bas", selection !== null || !elPanneau.hidden ||
      !elPanCalques.hidden || !elPanRecherche.hidden || !elPanAppareil.hidden || !elPanCode.hidden ||
      !elPanEvenements.hidden || !elPanPoint.hidden || !elPanVisite.hidden || !elPanJournal.hidden ||
      !elPanObservation.hidden);
  }

  function basculer(nom) {
    const panneau = {
      temps: elPanneau, calques: elPanCalques, recherche: elPanRecherche, appareil: elPanAppareil,
      evenements: elPanEvenements,
    }[nom];
    if (panneau.hidden) ouvrirSeul(nom);
    else ouvrir(null);
  }

  function basculerPanneau() {
    basculer("temps");
    afficherHeure();
  }

  elBouton.addEventListener("click", basculerPanneau);
  elBtnCalques.addEventListener("click", function () {
    basculer("calques");
  });
  elEtatBouton.addEventListener("click", function () {
    basculer("appareil");
    majPanneauAppareil();
  });
  elBtnRecherche.addEventListener("click", function () {
    basculer("recherche");
    if (!elPanRecherche.hidden) {
      filtrerRecherche();
      elChampRecherche.focus();
    }
  });

  // Toucher le ciel ou la barre referme les panneaux du bas (sauf leurs propres boutons)
  document.addEventListener("pointerdown", function (e) {
    if (e.target.closest("#panneau-temps, #panneau-calques, #panneau-recherche, #panneau-appareil, #panneau-code, #panneau-evenements, #panneau-point, #panneau-visite, #panneau-journal, #panneau-observation, #btn-temps, #btn-calques, #btn-recherche, #btn-evenements, #etat-appareil")) return;
    if (!elPanneau.hidden || !elPanCalques.hidden || !elPanRecherche.hidden || !elPanAppareil.hidden || !elPanCode.hidden ||
      !elPanEvenements.hidden || !elPanPoint.hidden || !elPanVisite.hidden || !elPanJournal.hidden ||
      !elPanObservation.hidden) ouvrir(null);
  });

  // --- Calques : chaque case recharge la carte avec la nouvelle configuration -----
  document.querySelectorAll("#panneau-calques [data-calque]").forEach(function (bouton) {
    bouton.addEventListener("click", function () {
      const nom = bouton.dataset.calque;
      calques[nom] = !calques[nom];
      bouton.setAttribute("aria-pressed", String(calques[nom]));
      rechargerCarte();
    });
  });

  // --- Filtres des astres et magnitude limite (8.4, F36) -------------------------------------
  function majBoutonsFiltres() {
    document.querySelectorAll("#panneau-calques [data-filtre]").forEach(function (b) {
      b.setAttribute("aria-pressed", String(filtres[b.dataset.filtre]));
    });
    document.querySelectorAll("#panneau-calques [data-magnitude]").forEach(function (b) {
      b.setAttribute("aria-pressed", String(Number(b.dataset.magnitude) === filtres.magnitude));
    });
  }
  majBoutonsFiltres();
  document.querySelectorAll("#panneau-calques [data-filtre]").forEach(function (bouton) {
    bouton.addEventListener("click", function () {
      const nom = bouton.dataset.filtre;
      filtres[nom] = !filtres[nom];
      garderFiltres();
      majBoutonsFiltres();
      if (selection !== null) {
        const o = objets.find(function (obj) { return obj.id === selection; });
        if (o && !objetAffiche(o)) selectionner(null); // l'astre ouvert vient d'être masqué
      }
      Celestial.redraw();
    });
  });
  document.querySelectorAll("#panneau-calques [data-magnitude]").forEach(function (bouton) {
    bouton.addEventListener("click", function () {
      filtres.magnitude = Number(bouton.dataset.magnitude);
      garderFiltres();
      majBoutonsFiltres();
      rechargerCarte(); // la bibliothèque relit la limite des étoiles
    });
  });

  // Redessine la carte avec la configuration courante, sans changer sa taille
  function rechargerCarte() {
    Celestial.reload(configCarte(tailleAffichee));
    d3.select(window).on("resize", null); // la bibliothèque remet son gestionnaire : on le retire
    appliquerVue(); // remet l'horizon droit après le rechargement
    placerCanevas();
  }

  // --- Recherche d'un astre parmi ceux qui sont chargés ----------------------------
  function normaliser(texte) {
    return texte.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
  }

  function filtrerRecherche() {
    const cherche = normaliser(elChampRecherche.value.trim());
    const resultats = objets
      .filter(function (o) { return objetAffiche(o) && normaliser(o.nom).indexOf(cherche) !== -1; }) // F12 : suit les filtres
      .sort(function (a, b) { return a.nom.localeCompare(b.nom, "fr"); })
      .slice(0, 50);
    elListeRecherche.replaceChildren();
    if (resultats.length === 0) {
      const vide = document.createElement("li");
      vide.className = "vide";
      vide.textContent = objets.length ? "Aucun astre ne correspond." : "Chargement…";
      elListeRecherche.appendChild(vide);
      return;
    }
    // Construit avec createElement / textContent, jamais innerHTML
    resultats.forEach(function (o) {
      const li = document.createElement("li");
      const bouton = document.createElement("button");
      bouton.type = "button";
      bouton.dataset.id = String(o.id);
      const nom = document.createElement("span");
      nom.textContent = o.nom;
      const etat = document.createElement("span");
      etat.className = "etat";
      const h = ici(o).elevation;
      etat.textContent = h > 0 ? fmtNombre.format(h) + "°" : "sous l'horizon";
      bouton.append(nom, etat);
      li.appendChild(bouton);
      elListeRecherche.appendChild(li);
    });
  }

  elChampRecherche.addEventListener("input", filtrerRecherche);
  elListeRecherche.addEventListener("click", function (e) {
    const bouton = e.target.closest("button[data-id]");
    if (!bouton) return;
    const o = objets.find(function (obj) { return String(obj.id) === bouton.dataset.id; });
    if (o) allerVers(o);
  });

  // Tourne la vue vers l'objet, puis le sélectionne (sa fiche s'ouvre)
  function allerVers(o) {
    const p = ici(o);
    viser(p.azimut, p.elevation, true);
    selectionner(o.id); // ferme les autres panneaux et redessine (halo)
  }

  // Tourne la vue vers une direction. Avec une fiche ouverte sur téléphone (elle couvre la moitié
  // basse de l'écran), on vise un peu en dessous pour que la cible apparaisse au quart supérieur.
  function viser(azimut, elevation, avecFiche) {
    const decalage = GRAND_ECRAN.matches || !avecFiche ? 0 : (window.innerHeight * 0.25) / (echelleVue() * vue.zoom);
    fixerDirection(azimut, elevation - decalage);
    appliquerVue();
    majBoussole();
  }

  // --- Partie 8.4 : cible personnalisée (un point quelconque du ciel) -----------------------
  let pointChoisi = null; // {ra, dec, infos} : le point montré dans son panneau
  const elPoint = {
    hauteur: document.getElementById("point-hauteur"),
    direction: document.getElementById("point-direction"),
    coordonnees: document.getElementById("point-coordonnees"),
    soir: document.getElementById("point-soir"),
    bouton: document.getElementById("btn-pointer-point"),
    note: document.getElementById("point-note"),
  };

  // Le point du ciel sous le doigt (x, y : coordonnées dans la fenêtre)
  function choisirPoint(x, y) {
    const canvas = carte.querySelector("canvas");
    if (!canvas || !Celestial.mapProjection.invert) return;
    const zone = canvas.getBoundingClientRect();
    const p = Celestial.mapProjection.invert([x - zone.left, y - zone.top]);
    if (!p || !isFinite(p[0]) || !isFinite(p[1])) return;
    if (navigator.vibrate) {
      try { navigator.vibrate(15); } catch (erreur) { /* sans vibreur : rien */ }
    }
    montrerPoint(((p[0] % 360) + 360) % 360, Math.max(-90, Math.min(90, p[1])));
  }

  function montrerPoint(ra, dec) {
    if (selection !== null) selectionner(null);
    ouvrir("point");
    pointChoisi = { ra: ra, dec: dec, infos: null };
    majPanneauPoint();
    Celestial.redraw();
    const demande = pointChoisi;
    fetch(carte.dataset.urlPoint + "?ra=" + ra.toFixed(4) + "&dec=" + dec.toFixed(4) +
      "&instant=" + encodeURIComponent(new Date(horloge.virtuel).toISOString()))
      .then(function (reponse) {
        if (!reponse.ok) throw new Error("HTTP " + reponse.status);
        return reponse.json();
      })
      .then(function (donnees) {
        if (pointChoisi !== demande) return; // un autre point a été choisi entre-temps
        pointChoisi.infos = donnees;
        majPanneauPoint();
      })
      .catch(function (erreur) {
        console.warn("Point du ciel indisponible :", erreur);
      });
  }

  // Le point visé par le bras est-il celui qu'on montre ? (à 0,01° près)
  function pointEstVise() {
    const c = pointage && pointage.commande;
    return Boolean(pointChoisi && c && c.coordonnees &&
      Math.abs(c.coordonnees.ra - pointChoisi.ra) < 0.01 && Math.abs(c.coordonnees.dec - pointChoisi.dec) < 0.01);
  }

  function majPanneauPoint() {
    if (elPanPoint.hidden || !pointChoisi) return;
    const i = pointChoisi.infos;
    elPoint.coordonnees.textContent = texteCoordonnees(pointChoisi.ra, pointChoisi.dec) +
      (i && nomsConstellations[i.constellation_iau] ? " · " + nomsConstellations[i.constellation_iau] : "");
    elPoint.hauteur.textContent = i ? fmtNombre.format(i.elevation) + "°" : "…";
    elPoint.direction.textContent = i ? POINTS_CARDINAUX[Math.round(i.azimut / 22.5) % 16] + " · " + Math.round(i.azimut) % 360 + "°" : "…";
    elPoint.soir.textContent = i ? texteCeSoir(i.ce_soir, "Ce point") : "";
    const vise = pointEstVise();
    const a = pointage && pointage.appareil;
    elPoint.bouton.textContent = vise ? "Arrêter le pointage" : "Pointer ici";
    elPoint.bouton.classList.toggle("arreter", vise);
    elPoint.bouton.disabled = !a || envoiEnCours;
    const p = pointage && pointage.pilotage;
    const phrases = [];
    if (Date.now() < finMessageErreur) phrases.push(messageErreur);
    else if (!a) phrases.push("Aucun appareil enregistré.");
    else if (vise) phrases.push("Le bras suit ce point, qui tourne avec le ciel comme une étoile.");
    if (i && i.elevation <= 0) phrases.push("Sous l'horizon : le bras pointera à travers la Terre.");
    if (a && p && !p.autorise) phrases.push("Le code de pilotage sera demandé.");
    elPoint.note.textContent = phrases.join(" ");
    majBoutonsVisite();
  }

  elPoint.bouton.addEventListener("click", function () {
    if (!pointChoisi || envoiEnCours) return;
    if (pointEstVise()) envoyer(carte.dataset.urlArret, null);
    else envoyer(carte.dataset.urlCommande, { ra: Number(pointChoisi.ra.toFixed(4)), dec: Number(pointChoisi.dec.toFixed(4)) });
  });
  document.getElementById("point-fermer").addEventListener("click", function () {
    ouvrir(null);
  });

  // Repères sur la carte : le point montré (croix dorée) et le point visé par le bras (anneau vert)
  function dessinerPoints(ctx) {
    const c = pointage && pointage.commande;
    if (c && c.coordonnees) dessinerRepere(ctx, [c.coordonnees.ra, c.coordonnees.dec], COULEUR_BRAS, c.objet.nom, false);
    if (pointChoisi) dessinerRepere(ctx, [pointChoisi.ra, pointChoisi.dec], "#ffd479", null, true);
  }

  function dessinerRepere(ctx, position, couleur, nom, croix) {
    if (!Celestial.clip(position)) return;
    const pt = Celestial.mapProjection(position);
    ctx.save();
    ctx.strokeStyle = couleur;
    ctx.lineWidth = 1.8;
    ctx.beginPath();
    ctx.arc(pt[0], pt[1], 9, 0, 2 * Math.PI);
    ctx.stroke();
    if (croix) {
      ctx.beginPath();
      [[-16, 0, -11, 0], [11, 0, 16, 0], [0, -16, 0, -11], [0, 11, 0, 16]].forEach(function (s) {
        ctx.moveTo(pt[0] + s[0], pt[1] + s[1]);
        ctx.lineTo(pt[0] + s[2], pt[1] + s[3]);
      });
      ctx.stroke();
    }
    if (nom) {
      ctx.font = "600 13px Helvetica, Arial, sans-serif";
      ctx.textBaseline = "bottom";
      ctx.lineJoin = "round";
      ctx.lineWidth = 3;
      ctx.strokeStyle = "rgba(5, 7, 13, 0.85)";
      ctx.strokeText(nom, pt[0] + 13, pt[1] - 6);
      ctx.fillStyle = couleur;
      ctx.fillText(nom, pt[0] + 13, pt[1] - 6);
    }
    ctx.restore();
  }

  // --- Partie 9 : journal d'observation ---------------------------------------------------------
  // Lire est libre ; noter ou effacer demande le code de pilotage (le carnet du propriétaire).
  const elJournal = {
    liste: document.getElementById("journal-liste"),
    etat: document.getElementById("journal-etat"),
    filtre: document.getElementById("journal-filtre"),
    filtreNom: document.getElementById("journal-filtre-nom"),
    tout: document.getElementById("journal-tout"),
    exporter: document.getElementById("journal-export"),
    astre: document.getElementById("btn-journal-astre"),
    noter: document.getElementById("btn-noter"),
  };
  const elObs = {
    nom: document.getElementById("observation-nom"),
    quand: document.getElementById("observation-quand"),
    note: document.getElementById("observation-note"),
    enregistrer: document.getElementById("observation-enregistrer"),
    message: document.getElementById("observation-message"),
  };
  const NOMS_CIEL = { clair: "ciel clair", voile: "ciel voilé", nuageux: "nuageux", inconnu: "" };
  const NOMS_INSTRUMENT = { oeil: "à l'œil nu", jumelles: "aux jumelles", telescope: "au télescope", bras: "avec le bras" };
  let filtreJournal = null; // {id, nom} : le journal d'un seul astre, ou null pour tout
  let observationEnCours = null; // {objet_id, nom} : ce qu'on note
  let comptesJournal = {}; // objet_id -> nombre d'observations (pour le lien de la fiche)
  elJournal.exporter.href = carte.dataset.urlJournalExport;

  function chargerJournal() {
    elJournal.etat.textContent = "Chargement…";
    const url = carte.dataset.urlJournal + (filtreJournal ? "?objet=" + filtreJournal.id : "");
    return fetch(url)
      .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
      .then(afficherJournal)
      .catch(function () { elJournal.etat.textContent = "Journal indisponible pour le moment."; });
  }

  function afficherJournal(d) {
    elJournal.filtre.hidden = !filtreJournal;
    if (filtreJournal) elJournal.filtreNom.textContent = "Seulement : " + filtreJournal.nom;
    const lignes = d.observations.map(function (o) { return { sorte: "observation", quand: o.quand, d: o }; })
      .concat(d.pointages.map(function (p) { return { sorte: "pointage", quand: p.quand, d: p }; }))
      .sort(function (a, b) { return Date.parse(b.quand) - Date.parse(a.quand); });
    elJournal.liste.replaceChildren();
    let jourPrecedent = "";
    lignes.forEach(function (l) {
      const jour = fmtJourLong.format(new Date(l.quand));
      if (jour !== jourPrecedent) {
        jourPrecedent = jour;
        const titre = document.createElement("li");
        titre.className = "jour";
        titre.textContent = jour;
        elJournal.liste.appendChild(titre);
      }
      const x = l.d;
      let li;
      if (l.sorte === "observation") {
        const detail = [fmtHeure.format(new Date(x.quand)), NOMS_INSTRUMENT[x.instrument], NOMS_CIEL[x.ciel]].filter(Boolean).join(" · ");
        li = ligneEvenement("lune", x.nom, detail, function () { voirMoment(x.quand, x.direction, x.objet_id); }, false);
        if (x.note) {
          const note = document.createElement("span");
          note.className = "note-texte";
          note.textContent = x.note; // texte libre : textContent, jamais innerHTML
          li.querySelector("button").appendChild(note);
        }
        li.appendChild(boutonEffacer(x));
      } else {
        const detail = "Bras : " + fmtHeure.format(new Date(x.quand)) + (x.fin ? " → " + fmtHeure.format(new Date(x.fin)) : "") +
          (x.visite ? " · visite guidée" : "");
        li = ligneEvenement("passage", x.nom, detail, function () { voirMoment(x.quand, x.direction, x.objet_id); }, false);
      }
      elJournal.liste.appendChild(li);
    });
    elJournal.etat.textContent = lignes.length ? "" : "Rien dans le journal pour l'instant : note une observation depuis la fiche d'un astre.";
  }

  function boutonEffacer(o) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "effacer";
    b.textContent = "effacer";
    b.addEventListener("click", function () { effacerObservation(o); }); // pas de boîte de dialogue (Partie 5)
    return b;
  }

  function effacerObservation(o) {
    posterJson(carte.dataset.urlJournal + o.id + "/effacer/", null).then(function (r) {
      if (r.statut === 403 && r.donnees.code_requis) {
        const filtre = filtreJournal;
        demanderCode({ relancer: function () { ouvrirJournal(filtre); effacerObservation(o); } });
        return;
      }
      comptesJournal = {};
      chargerJournal();
    }).catch(function () { elJournal.etat.textContent = "Serveur injoignable."; });
  }

  function ouvrirJournal(filtre) {
    filtreJournal = filtre || null;
    if (selection !== null) selectionner(null);
    ouvrir("journal");
    chargerJournal();
  }

  // Dans la fiche : « Noter une observation » et « Journal de cet astre (n) »
  function majJournalFiche() {
    elJournal.noter.hidden = selection === null;
    if (selection === null) return;
    const id = selection;
    if (comptesJournal[id] === undefined) {
      comptesJournal[id] = null; // demande en cours
      fetch(carte.dataset.urlJournal + "?objet=" + id + "&limite=500")
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (d) {
          comptesJournal[id] = d ? d.observations.length : 0;
          if (selection === id) majJournalFiche();
        })
        .catch(function () { comptesJournal[id] = 0; });
    }
    const n = comptesJournal[id];
    elJournal.astre.hidden = !n;
    if (n) elJournal.astre.textContent = n + " observation" + (n > 1 ? "s" : "") + " de cet astre dans le journal";
  }

  elJournal.noter.addEventListener("click", function () {
    if (selection === null) return;
    const nom = fiche ? fiche.nom : (objets.find(function (o) { return o.id === selection; }) || {}).nom || "Astre";
    ouvrirObservation({ objet_id: selection, nom: nom });
  });
  elJournal.astre.addEventListener("click", function () {
    if (selection === null) return;
    ouvrirJournal({ id: selection, nom: fiche ? fiche.nom : "" });
  });
  elJournal.tout.addEventListener("click", function () { ouvrirJournal(null); });
  document.getElementById("btn-journal").addEventListener("click", function () { ouvrirJournal(null); });
  document.getElementById("journal-fermer").addEventListener("click", function () { ouvrir(null); });
  document.getElementById("observation-fermer").addEventListener("click", function () { ouvrir(null); });

  function choisir(groupe, valeur) {
    document.querySelectorAll("#panneau-observation [data-" + groupe + "]").forEach(function (b) {
      b.setAttribute("aria-pressed", String(b.dataset[groupe] === valeur));
    });
  }
  function choisi(groupe, defaut) {
    const b = document.querySelector("#panneau-observation [data-" + groupe + '][aria-pressed="true"]');
    return b ? b.dataset[groupe] : defaut;
  }
  document.querySelectorAll("#panneau-observation [data-ciel], #panneau-observation [data-instrument]").forEach(function (b) {
    b.addEventListener("click", function () {
      const groupe = b.dataset.ciel !== undefined ? "ciel" : "instrument";
      const deja = b.getAttribute("aria-pressed") === "true";
      choisir(groupe, deja && groupe === "ciel" ? "" : b.dataset[groupe]); // le ciel peut rester « non précisé »
    });
  });

  // Date et heure locales pour <input type="datetime-local"> (AAAA-MM-JJTHH:MM)
  function dateLocale(d) {
    const z = function (n) { return String(n).padStart(2, "0"); };
    return d.getFullYear() + "-" + z(d.getMonth() + 1) + "-" + z(d.getDate()) + "T" + z(d.getHours()) + ":" + z(d.getMinutes());
  }

  function ouvrirObservation(cible) {
    observationEnCours = cible;
    if (selection !== null) selectionner(null);
    ouvrir("observation");
    elObs.nom.textContent = cible.nom;
    elObs.quand.value = dateLocale(new Date());
    elObs.quand.max = dateLocale(new Date(Date.now() + 5 * 60000));
    elObs.note.value = "";
    elObs.message.textContent = "";
    choisir("ciel", "");
    choisir("instrument", pointage && pointage.commande && pointage.commande.objet.id === cible.objet_id ? "bras" : "oeil");
  }

  function enregistrerObservation() {
    if (!observationEnCours) return;
    const quand = elObs.quand.value ? new Date(elObs.quand.value) : new Date();
    const corps = {
      objet_id: observationEnCours.objet_id,
      quand: isNaN(quand.getTime()) ? null : quand.toISOString(),
      ciel: choisi("ciel", "inconnu") || "inconnu",
      instrument: choisi("instrument", "oeil"),
      note: elObs.note.value,
    };
    elObs.enregistrer.disabled = true;
    posterJson(carte.dataset.urlJournalNoter, corps).then(function (r) {
      elObs.enregistrer.disabled = false;
      if (r.statut === 403 && r.donnees.code_requis) {
        const garde = observationEnCours;
        demanderCode({ relancer: function () {
          // Le panneau a été fermé par la demande de code : on le rouvre tel quel, puis on enregistre
          observationEnCours = garde;
          ouvrir("observation");
          enregistrerObservation();
        } });
        return;
      }
      if (r.statut !== 201) {
        elObs.message.textContent = (r.donnees && r.donnees.erreur) || "Erreur " + r.statut;
        return;
      }
      delete comptesJournal[corps.objet_id];
      ouvrirJournal({ id: corps.objet_id, nom: observationEnCours.nom });
    }).catch(function () {
      elObs.enregistrer.disabled = false;
      elObs.message.textContent = "Serveur injoignable.";
    });
  }
  elObs.enregistrer.addEventListener("click", enregistrerObservation);

  // --- Partie 8.5 (F22) : visite guidée --------------------------------------------------------
  // Le brouillon (la liste qu'on prépare) reste dans ce navigateur ; la visite lancée est sur le
  // serveur (et dans la trajectoire du robot, qui l'enchaîne même sans réseau).
  const CLE_VISITE = "index-stellaire-visite";
  const DUREES_ETAPE = [5, 10, 15, 20, 30, 45, 60];
  let brouillon = [];
  try {
    const garde = JSON.parse(localStorage.getItem(CLE_VISITE) || "[]");
    if (Array.isArray(garde)) {
      brouillon = garde.filter(function (e) {
        return e && typeof e.nom === "string" && DUREES_ETAPE.indexOf(e.duree_min) !== -1 &&
          (Number.isInteger(e.objet_id) || (typeof e.ra === "number" && typeof e.dec === "number"));
      }).slice(0, 20);
    }
  } catch (erreur) { /* stockage indisponible : liste vide */ }

  const elVisite = {
    enCours: document.getElementById("visite-en-cours"),
    etapesEnCours: document.getElementById("visite-etapes-en-cours"),
    arreter: document.getElementById("visite-arreter"),
    titreBrouillon: document.getElementById("visite-titre-brouillon"),
    etapes: document.getElementById("visite-etapes"),
    vide: document.getElementById("visite-vide"),
    proposer: document.getElementById("visite-proposer"),
    depart: document.getElementById("visite-depart"),
    heure: document.getElementById("visite-heure"),
    resume: document.getElementById("visite-resume"),
    lancer: document.getElementById("visite-lancer"),
    vider: document.getElementById("visite-vider"),
    note: document.getElementById("visite-note"),
  };
  const elAjouterVisite = document.getElementById("btn-ajouter-visite");
  const elPointVisite = document.getElementById("btn-point-visite");

  function garderBrouillon() {
    try { localStorage.setItem(CLE_VISITE, JSON.stringify(brouillon)); } catch (erreur) { /* tant pis */ }
  }

  function cleEtape(e) {
    return e.objet_id !== undefined && e.objet_id !== null ? "o" + e.objet_id : "p" + e.ra.toFixed(3) + "," + e.dec.toFixed(3);
  }

  function basculerEtape(etape) {
    const cle = cleEtape(etape);
    const i = brouillon.findIndex(function (e) { return cleEtape(e) === cle; });
    if (i !== -1) brouillon.splice(i, 1);
    else if (brouillon.length < 20) brouillon.push(etape);
    garderBrouillon();
    majBoutonsVisite();
    afficherVisite();
  }

  function dansBrouillon(etape) {
    const cle = cleEtape(etape);
    return brouillon.some(function (e) { return cleEtape(e) === cle; });
  }

  // Boutons « Ajouter à la visite » de la fiche et du point du ciel
  function majBoutonsVisite() {
    const o = selection !== null ? objets.find(function (obj) { return obj.id === selection; }) : null;
    const categorie = fiche ? fiche.categorie : o && o.categorie;
    // un satellite passe trop vite ; le Soleil ne se vise jamais (Partie 14)
    elAjouterVisite.hidden = selection === null || categorie === "satellite" || categorie === "soleil";
    if (selection !== null) {
      elAjouterVisite.textContent = dansBrouillon({ objet_id: selection })
        ? "Retirer de la visite (" + brouillon.length + ")" : "Ajouter à la visite" + (brouillon.length ? " (" + brouillon.length + ")" : "");
    }
    if (pointChoisi) {
      elPointVisite.textContent = dansBrouillon({ objet_id: null, ra: pointChoisi.ra, dec: pointChoisi.dec })
        ? "Retirer de la visite" : "Ajouter à la visite";
    }
  }

  elAjouterVisite.addEventListener("click", function () {
    if (selection === null) return;
    const nom = fiche ? fiche.nom : (objets.find(function (o) { return o.id === selection; }) || {}).nom || "Astre";
    basculerEtape({ objet_id: selection, nom: nom, duree_min: 10 });
  });
  elPointVisite.addEventListener("click", function () {
    if (!pointChoisi) return;
    basculerEtape({ objet_id: null, ra: Number(pointChoisi.ra.toFixed(4)), dec: Number(pointChoisi.dec.toFixed(4)),
      nom: "Point du ciel " + (brouillon.length + 1), duree_min: 10 });
  });

  // Début choisi : maintenant, ou la prochaine fois qu'il sera HH:MM (aujourd'hui ou demain)
  function debutVisite() {
    const choix = elVisite.depart.querySelector("input[name=visite-debut]:checked").value;
    if (choix === "maintenant") return null;
    const morceaux = (elVisite.heure.value || "21:00").split(":").map(Number);
    const d = new Date();
    d.setHours(morceaux[0], morceaux[1], 0, 0);
    if (d.getTime() < Date.now() - 5 * 60000) d.setDate(d.getDate() + 1);
    return d;
  }

  function boutonPetit(texte, titre, action) {
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = texte;
    b.setAttribute("aria-label", titre);
    b.addEventListener("click", action);
    return b;
  }

  function afficherVisite() {
    if (elPanVisite.hidden) return;
    // La visite en cours (côté serveur)
    const prog = pointage && pointage.commande && pointage.commande.programme;
    elVisite.enCours.hidden = !prog;
    elVisite.etapesEnCours.replaceChildren();
    if (prog) {
      prog.etapes.forEach(function (e, i) {
        const li = document.createElement("li");
        if (i + 1 === prog.etape) li.className = "courante";
        const nom = document.createElement("span");
        nom.className = "nom";
        nom.textContent = e.nom;
        const h = document.createElement("span");
        h.className = "horaire";
        h.textContent = fmtHeure.format(new Date(e.debut)) + (e.fin ? " → " + fmtHeure.format(new Date(e.fin)) : " → …");
        li.append(nom, h);
        elVisite.etapesEnCours.appendChild(li);
      });
    }
    elVisite.titreBrouillon.textContent = prog ? "Prochaine visite (remplacera celle en cours) :" : "Prochaine visite :";
    // Le brouillon : durée réglable, monter, descendre, retirer. Toujours textContent.
    elVisite.etapes.replaceChildren();
    brouillon.forEach(function (e, i) {
      const li = document.createElement("li");
      const nom = document.createElement("span");
      nom.className = "nom";
      nom.textContent = e.nom;
      const duree = document.createElement("select");
      duree.setAttribute("aria-label", "Durée de l'étape");
      DUREES_ETAPE.forEach(function (m) {
        const opt = document.createElement("option");
        opt.value = String(m);
        opt.textContent = m + " min";
        if (m === e.duree_min) opt.selected = true;
        duree.appendChild(opt);
      });
      duree.addEventListener("change", function () {
        e.duree_min = Number(duree.value);
        garderBrouillon();
        afficherVisite();
      });
      li.append(nom, duree,
        boutonPetit("↑", "Monter", function () {
          if (i > 0) { brouillon.splice(i - 1, 0, brouillon.splice(i, 1)[0]); garderBrouillon(); afficherVisite(); }
        }),
        boutonPetit("↓", "Descendre", function () {
          if (i < brouillon.length - 1) { brouillon.splice(i + 1, 0, brouillon.splice(i, 1)[0]); garderBrouillon(); afficherVisite(); }
        }),
        boutonPetit("×", "Retirer", function () {
          brouillon.splice(i, 1); garderBrouillon(); majBoutonsVisite(); afficherVisite();
        }));
      elVisite.etapes.appendChild(li);
    });
    const vide = brouillon.length === 0;
    elVisite.vide.hidden = !vide;
    elVisite.depart.hidden = vide;
    elVisite.lancer.hidden = vide;
    elVisite.vider.hidden = vide;
    const total = brouillon.reduce(function (s, e) { return s + e.duree_min; }, 0);
    const debut = debutVisite() || new Date();
    elVisite.resume.textContent = vide ? "" : brouillon.length + " étape" + (brouillon.length > 1 ? "s" : "") + " · " + total +
      " min · de " + fmtHeure.format(debut) + " à " + fmtHeure.format(new Date(debut.getTime() + total * 60000)) +
      " (le bras reste ensuite sur la dernière).";
    const a = pointage && pointage.appareil;
    elVisite.lancer.disabled = !a || envoiEnCours;
    elVisite.arreter.disabled = envoiEnCours;
    const p = pointage && pointage.pilotage;
    const phrases = [];
    if (Date.now() < finMessageErreur) phrases.push(messageErreur);
    else if (!a) phrases.push("Aucun appareil enregistré.");
    if (!vide && a && p && !p.autorise) phrases.push("Le code de pilotage sera demandé.");
    if (!vide) phrases.push("Le bras enchaîne les étapes même si le réseau tombe.");
    elVisite.note.textContent = phrases.join(" ");
  }

  elVisite.lancer.addEventListener("click", function () {
    if (!brouillon.length || envoiEnCours) return;
    const debut = debutVisite();
    envoyer(carte.dataset.urlVisite, {
      debut: debut ? debut.toISOString() : null,
      etapes: brouillon.map(function (e) {
        return e.objet_id !== null && e.objet_id !== undefined
          ? { objet_id: e.objet_id, duree_min: e.duree_min }
          : { ra: e.ra, dec: e.dec, nom: e.nom, duree_min: e.duree_min };
      }),
    });
  });
  elVisite.arreter.addEventListener("click", function () {
    if (!envoiEnCours) envoyer(carte.dataset.urlArret, null);
  });
  elVisite.vider.addEventListener("click", function () {
    brouillon = [];
    garderBrouillon();
    majBoutonsVisite();
    afficherVisite();
  });
  elVisite.depart.addEventListener("change", afficherVisite);
  document.getElementById("visite-fermer").addEventListener("click", function () { ouvrir(null); });
  document.getElementById("app-visite").addEventListener("click", function () { ouvrirVisite(); });

  function ouvrirVisite() {
    if (selection !== null) selectionner(null);
    ouvrir("visite");
    afficherVisite();
  }

  // « Proposer une visite de ce soir » : les astres visibles cette nuit, 10 min chacun, dans
  // l'ordre où ils sont observables (un astre n'est pris que s'il est levé pendant son étape)
  function proposerVisite() {
    function construire(soir) {
      if (!soir || !soir.debut_nuit) {
        elVisite.note.textContent = "Pas de nuit dans les 24 prochaines heures : rien à proposer.";
        return;
      }
      let t = Math.max(Date.parse(soir.debut_nuit), Date.now());
      const debutPropose = t;
      const etapes = [];
      // Les étapes s'enchaînent sans pause : un astre n'est pris que s'il est déjà levé (à 10° ou
      // plus) au début de son étape et le reste jusqu'à la fin
      soir.astres.slice().sort(function (a, b) { return Date.parse(a.de) - Date.parse(b.de); }).forEach(function (a) {
        if (Date.parse(a.de) <= t && Date.parse(a.a) >= t + 10 * 60000) {
          etapes.push({ objet_id: a.objet_id, nom: a.nom, duree_min: 10 });
          t += 10 * 60000;
        }
      });
      if (!etapes.length) {
        elVisite.note.textContent = "Aucun astre de la base n'est assez haut à ce moment-là.";
        return;
      }
      brouillon = etapes;
      garderBrouillon();
      const d = new Date(debutPropose);
      const maintenant = debutPropose <= Date.now() + 60000;
      elVisite.depart.querySelector("input[value=" + (maintenant ? "maintenant" : "heure") + "]").checked = true;
      if (!maintenant) elVisite.heure.value = String(d.getHours()).padStart(2, "0") + ":" + String(d.getMinutes()).padStart(2, "0");
      ouvrirVisite();
    }
    if (evenements && Math.abs(Date.now() - instantEvenements) < EVENEMENTS_PERIMES_APRES) {
      construire(evenements.ce_soir);
      return;
    }
    fetch(carte.dataset.urlEvenements + "?jours=1")
      .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
      .then(function (d) { construire(d.ce_soir); })
      .catch(function () { elVisite.note.textContent = "Impossible de calculer la nuit pour le moment."; });
  }
  elVisite.proposer.addEventListener("click", proposerVisite);
  document.getElementById("btn-proposer-visite").addEventListener("click", proposerVisite);

  // --- Partie 7 : événements visibles à l'œil nu -------------------------------------------
  const elSoirNuit = document.getElementById("soir-nuit");
  const elSoirAstres = document.getElementById("soir-astres");
  const elListeEvenements = document.getElementById("evenements-liste");
  const elEtatEvenements = document.getElementById("evenements-etat");
  const EVENEMENTS_PERIMES_APRES = 10 * 60 * 1000; // ms virtuelles
  let evenements = null; // dernière réponse de /api/ciel/evenements/
  let instantEvenements = null;
  let evenementsEnCours = false;

  function chargerEvenements() {
    if (evenementsEnCours) return;
    if (evenements && Math.abs(horloge.virtuel - instantEvenements) < EVENEMENTS_PERIMES_APRES) return;
    evenementsEnCours = true;
    const cible = horloge.virtuel;
    elEtatEvenements.hidden = false;
    elEtatEvenements.textContent = "Calcul en cours…";
    fetch(carte.dataset.urlEvenements + "?jours=30&instant=" + encodeURIComponent(new Date(cible).toISOString()))
      .then(function (reponse) {
        if (!reponse.ok) throw new Error("HTTP " + reponse.status);
        return reponse.json();
      })
      .then(function (donnees) {
        evenements = donnees;
        instantEvenements = cible;
        afficherEvenements();
      })
      .catch(function (erreur) {
        console.warn("Événements indisponibles :", erreur);
        elEtatEvenements.textContent = "Événements indisponibles pour le moment.";
      })
      .finally(function () {
        evenementsEnCours = false;
      });
  }

  function versOu(direction) {
    if (!direction) return "";
    return direction.elevation > 0
      ? "vers " + POINTS_CARDINAUX[Math.round(direction.azimut / 22.5) % 16] + ", à " + Math.round(direction.elevation) + "°"
      : "sous l'horizon";
  }

  function detailEvenement(e) {
    const morceaux = [fmtHeure.format(new Date(e.instant))]; // le jour est dans l'intertitre
    if (e.type === "eclipse_soleil") {
      morceaux.push("de " + fmtHeure.format(new Date(e.debut)) + " à " + fmtHeure.format(new Date(e.fin)),
        "Soleil couvert à " + Math.round(e.magnitude * 100) + " %", "lunettes d'éclipse obligatoires");
    } else if (e.type === "opposition") {
      morceaux.push("visible toute la nuit", "au plus haut " + versOu(e.direction));
    } else if (e.type === "occultation") {
      morceaux.push("disparaît derrière la Lune, réapparaît vers " + fmtHeure.format(new Date(e.fin)));
    } else if (e.type === "saison") {
      return fmtHeure.format(new Date(e.instant));
    } else if (e.type === "aurore") {
      morceaux.push("bas sur l'horizon " + (e.direction.azimut === 0 ? "nord" : "sud"),
        "Kp " + fmtNombre.format(e.kp) + " prévu (il en faut " + fmtNombre.format(e.kp_necessaire) + " ici)",
        "source " + e.source);
    } else if (e.type === "comete") {
      morceaux.push(versOu(e.direction), "source " + e.source);
    } else if (e.type === "passage") {
      morceaux.push("max " + Math.round(e.hauteur_max) + "°",
        pointCardinal(e.azimut_lever) + " → " + pointCardinal(e.azimut_coucher));
    } else if (e.type === "essaim") {
      morceaux.push("jusqu'à " + e.zhr + " par heure", "radiant " + versOu(e.direction));
      if (e.lune_genante) morceaux.push("Lune gênante");
    } else {
      morceaux.push(versOu(e.direction));
    }
    return morceaux.join(" · ");
  }

  // Une ligne cliquable : pastille de couleur, titre, détail. Toujours textContent, jamais innerHTML.
  function ligneEvenement(classe, titre, detail, action, important) {
    const li = document.createElement("li");
    if (important) li.className = "important";
    const bouton = document.createElement("button");
    bouton.type = "button";
    const pastille = document.createElement("span");
    pastille.className = "pastille " + classe;
    const t = document.createElement("span");
    t.className = "titre";
    t.textContent = titre;
    if (important) {
      const badge = document.createElement("span");
      badge.className = "badge-important";
      badge.textContent = "à ne pas manquer";
      t.append(badge);
    }
    const d = document.createElement("span");
    d.className = "detail";
    d.textContent = detail;
    bouton.append(pastille, t, d);
    bouton.addEventListener("click", action);
    li.appendChild(bouton);
    return li;
  }

  function afficherEvenements() {
    const soir = evenements.ce_soir;
    elSoirNuit.textContent = !soir.debut_nuit ? "Pas de nuit dans les 24 prochaines heures."
      : dejaCommence(soir.debut_nuit) ? "Nuit en cours, jusqu'à " + fmtHeure.format(new Date(soir.fin_nuit)) + "."
        : "Nuit de " + fmtHeure.format(new Date(soir.debut_nuit)) + " à " + fmtHeure.format(new Date(soir.fin_nuit)) + ".";
    elSoirAstres.replaceChildren();
    soir.astres.forEach(function (a) {
      const o = objets.find(function (obj) { return obj.id === a.objet_id; });
      const detail = (dejaCommence(a.de) ? "maintenant" : fmtHeure.format(new Date(a.de))) + " → " + fmtHeure.format(new Date(a.a)) +
        " · max " + Math.round(a.hauteur_max) + "° " + versOu(a.direction).replace(/, à .*/, "");
      elSoirAstres.appendChild(ligneEvenement(o ? o.categorie : "planete", a.nom, detail, function () {
        voirMoment(a.instant, a.direction, a.objet_id);
      }, false));
    });
    elListeEvenements.replaceChildren();
    let jourPrecedent = "";
    evenements.evenements.forEach(function (e) {
      const jour = fmtJourLong.format(new Date(e.instant));
      if (jour !== jourPrecedent) { // un intertitre par jour
        jourPrecedent = jour;
        const titreJour = document.createElement("li");
        titreJour.className = "jour";
        titreJour.textContent = jour;
        elListeEvenements.appendChild(titreJour);
      }
      elListeEvenements.appendChild(ligneEvenement(e.type, e.titre, detailEvenement(e), function () {
        voirMoment(e.instant, e.direction, e.objet_id);
      }, e.important));
    });
    document.getElementById("btn-proposer-visite").hidden = soir.astres.length === 0;
    elEtatEvenements.hidden = evenements.evenements.length > 0;
    elEtatEvenements.textContent = "Rien de remarquable ces 30 prochains jours.";
    afficherSources(evenements.sources || []);
  }

  // Partie 8.3 : d'où viennent les événements, et si chaque source est à jour
  const ETATS_SOURCE = { ok: "à jour", cache: "copie locale", indisponible: "indisponible" };
  function afficherSources(sources) {
    const el2 = document.getElementById("evenements-sources");
    el2.replaceChildren("Sources : ");
    sources.forEach(function (s, i) {
      if (i > 0) el2.append(" · ");
      const lien = lienExterne(s.page, s.nom);
      el2.append(lien || s.nom);
      const precisions = [s.licence, i > 0 ? ETATS_SOURCE[s.etat] + (s.etat === "cache" && s.age_h !== null ? ", il y a " + Math.round(s.age_h) + " h" : "") : ""]
        .filter(Boolean).join(", ");
      if (precisions) el2.append(" (" + precisions + ")");
    });
  }

  const fmtJourLong = new Intl.DateTimeFormat("fr-FR", {
    weekday: "long", day: "numeric", month: "long", timeZone: lieu.fuseau,
  });

  // Aller au moment de l'événement : l'heure de la carte saute, la vue se tourne vers lui et la
  // fiche de l'astre s'ouvre. « Revenir à maintenant » (panneau du temps) ramène au direct.
  function voirMoment(instantIso, direction, objetId) {
    horloge.virtuel = Date.parse(instantIso);
    horloge.vitesse = 1;
    horloge.dernierTop = Date.now();
    instantObjets = null; // positions à recalculer pour ce moment
    majCarte();
    afficherHeure();
    if (direction) viser(direction.azimut, direction.elevation, objetId !== null);
    if (objetId !== null) selectionner(objetId);
    else ouvrir(null);
    chargerObjets();
  }

  elBtnEvenements.addEventListener("click", function () {
    basculer("evenements");
    if (!elPanEvenements.hidden) {
      if (evenements) afficherEvenements();
      chargerEvenements();
    }
  });

  // --- Direction regardée et viseur ------------------------------------------------
  function majBoussole() {
    const point = POINTS_CARDINAUX[Math.round(vue.azimut / 22.5) % 16];
    elBoussoleDirection.textContent = point + " · " + (Math.round(vue.azimut) % 360) + "°";
    elBoussoleHauteur.textContent = "hauteur " + Math.round(vue.hauteur) + "° · zoom ×" + vue.zoom.toFixed(1);
  }

  elBtnBoussole.addEventListener("click", function () {
    viseurActif = !viseurActif;
    elBtnBoussole.setAttribute("aria-pressed", String(viseurActif));
    elBoussole.hidden = !viseurActif;
    Celestial.redraw();
  });

  // Un toucher sur la direction recentre la vue sur le sud, face à l'horizon (la vue de départ)
  elBoussole.addEventListener("click", function () {
    vue.azimut = 180;
    vue.hauteur = 0; // face à l'horizon
    appliquerVue();
    majBoussole();
    Celestial.redraw();
  });

  elPanneau.addEventListener("click", function (e) {
    const bouton = e.target.closest("button");
    if (!bouton) return;
    if (bouton.dataset.vitesse !== undefined) {
      horloge.vitesse = Number(bouton.dataset.vitesse);
      horloge.dernierTop = Date.now();
    } else if (bouton.dataset.saut !== undefined) {
      horloge.virtuel += Number(bouton.dataset.saut);
      majCarte();
    } else if (bouton.id === "btn-maintenant") {
      horloge.virtuel = Date.now();
      horloge.vitesse = 1;
      horloge.dernierTop = Date.now();
      majCarte();
    }
    afficherHeure();
  });

  // ===========================================================================
  // 4. Nos objets (positions calculées par Skyfield côté serveur)
  // ===========================================================================

  let objets = [];
  let instantObjets = null; // instant virtuel auquel les positions ont été calculées
  let chargementEnCours = false;
  let dernierChargement = 0;

  // Style de dessin par catégorie. Les étoiles sont déjà sur la carte (et déjà
  // nommées par la bibliothèque) : on se contente de les entourer.
  const STYLES = {
    planete: { forme: "disque", rayon: 5, couleur: "#ffd479", texte: "#ffe6ad", nom: true },
    lune: { forme: "disque", rayon: 7, couleur: "#e8ecf5", texte: "#ffffff", nom: true },
    etoile: { forme: "anneau", rayon: 8, couleur: "#7fb0ff", texte: "#a9c8ff", nom: false },
    amas: { forme: "anneau", rayon: 8, couleur: "#b79cff", texte: "#cdbcff", nom: true },
    satellite: { forme: "disque", rayon: 4, couleur: "#ff5a5a", texte: "#ff9a9a", nom: true },
    // Partie 10
    soleil: { forme: "disque", rayon: 10, couleur: "#ffcc33", texte: "#ffe08a", nom: true },
    ciel_profond: { forme: "anneau", rayon: 9, couleur: "#ff9fd6", texte: "#ffc4e6", nom: true },
  };

  // Partie 6.3 : position d'un objet à l'instant affiché. Un satellite arrive avec son trajet
  // (`trace` : 12 min, un point toutes les 15 s) ; on interpole : il avance sur la carte sans
  // redemander sa position au serveur. Les autres astres bougent trop peu pour cela.
  function ici(o) {
    const tr = o.trace;
    if (tr && tr.points.length > 1) {
      const x = (horloge.virtuel - Date.parse(tr.debut)) / (tr.pas_s * 1000);
      const i = Math.floor(x);
      if (i >= 0 && i < tr.points.length - 1) {
        const f = x - i;
        const a = tr.points[i];
        const b = tr.points[i + 1];
        const angle = function (u, v) { return (u + (((v - u + 540) % 360) - 180) * f + 360) % 360; };
        return { ra: angle(a[0], b[0]), dec: a[1] + (b[1] - a[1]) * f, elevation: a[2] + (b[2] - a[2]) * f, azimut: angle(a[3], b[3]) };
      }
    }
    return o;
  }

  // Le trajet d'un satellite sélectionné ou visé : pointillés vers l'avant (où il va),
  // trait fin vers l'arrière (d'où il vient), atténué sous l'horizon.
  function dessinerTrace(ctx, o, couleur) {
    const tr = o.trace;
    const maintenant = (horloge.virtuel - Date.parse(tr.debut)) / (tr.pas_s * 1000);
    ctx.save();
    ctx.lineWidth = 1.5;
    ctx.strokeStyle = couleur;
    let precedent = null;
    tr.points.forEach(function (p, i) {
      const position = [p[0], p[1]];
      const pt = Celestial.clip(position) ? Celestial.mapProjection(position) : null;
      if (pt && precedent) {
        ctx.beginPath();
        ctx.setLineDash(i > maintenant ? [5, 5] : []);
        ctx.globalAlpha = (p[2] > 0 ? 0.9 : 0.35) * (i > maintenant ? 1 : 0.45);
        ctx.moveTo(precedent[0], precedent[1]);
        ctx.lineTo(pt[0], pt[1]);
        ctx.stroke();
      }
      precedent = pt;
    });
    ctx.restore();
  }

  // Appelée à chaque tic : faut-il redessiner pour faire avancer un satellite ?
  // Seulement s'il s'est déplacé d'au moins 1,5 px à l'écran (le redessin coûte cher sur téléphone).
  const DEPLACEMENT_MINI_PX = 1.5;
  function satellitesBougent() {
    return objets.some(function (o) {
      if (!o.trace || !o.ecran) return false;
      const p = ici(o);
      const position = [p.ra, p.dec];
      if (!Celestial.clip(position)) return false;
      const pt = Celestial.mapProjection(position);
      return Math.hypot(pt[0] - o.ecran[0], pt[1] - o.ecran[1]) >= DEPLACEMENT_MINI_PX;
    });
  }

  function objetsPerimes() {
    if (chargementEnCours || Date.now() - dernierChargement < DELAI_MINI_REQUETES) return false;
    if (instantObjets === null) return true;
    return Math.abs(horloge.virtuel - instantObjets) > OBJETS_PERIMES_APRES;
  }

  function chargerObjets() {
    chargementEnCours = true;
    dernierChargement = Date.now();
    const cible = horloge.virtuel;
    const url = carte.dataset.urlObjets + "?instant=" + encodeURIComponent(new Date(cible).toISOString());
    fetch(url)
      .then(function (reponse) {
        if (!reponse.ok) throw new Error("HTTP " + reponse.status);
        return reponse.json();
      })
      .then(function (donnees) {
        objets = donnees.objets;
        instantObjets = cible;
        if (!elPanRecherche.hidden) filtrerRecherche(); // la liste de recherche suit les objets
        Celestial.redraw();
      })
      .catch(function (erreur) {
        console.warn("Objets indisponibles :", erreur);
      })
      .finally(function () {
        chargementEnCours = false;
      });
  }

  // Appelée par d3-celestial à chaque rafraîchissement de la carte.
  // Les objets sous l'horizon sont dessinés AVANT le sol : celui-ci est translucide,
  // donc on les voit faiblement à travers la terre (comme dans Sky Guide).
  function dessinerObjets() {
    const ctx = Celestial.context;
    dessinerIllustrations(ctx); // la figure de la constellation regardée, en fond
    dessinerConstellations(ctx); // avant le sol : atténués sous l'horizon, comme le reste
    objets.forEach(function (o) {
      if (objetAffiche(o) && ici(o).elevation <= 0) dessinerObjet(ctx, o);
    });
    dessinerSol(ctx);
    objets.forEach(function (o) {
      if (objetAffiche(o) && ici(o).elevation > 0) dessinerObjet(ctx, o);
    });
    dessinerHorizon(ctx);
    dessinerPoints(ctx); // 8.4 : point du ciel choisi, point visé par le bras
    if (viseurActif) dessinerViseur(ctx);
    dessinerAppareil(ctx);
  }

  // --- Illustrations des constellations -------------------------------------------------
  // Images de Johan Meuris (Stellarium, Licence Art Libre : mention dans le panneau des calques).
  // Seule la constellation regardée apparaît : pleine opacité quand le centre de l'écran est près du
  // centre de la figure, puis fondu jusqu'à son rayon (« centre » et « rayon » de illustrations.json,
  // calculés à partir de l'image elle-même : taille de la figure dans le ciel).
  // Chaque image est collée sur le ciel par 3 étoiles d'ancrage (transformation affine).
  const OPACITE_ILLUSTRATION = 0.75;
  const PART_PLEINE_OPACITE = 0.4; // en dessous de 40 % du rayon : opacité maximale
  let illustrations = [];
  fetch(carte.dataset.urlIllustrations)
    .then(function (reponse) {
      if (!reponse.ok) throw new Error("HTTP " + reponse.status);
      return reponse.json();
    })
    .then(function (donnees) {
      illustrations = donnees.illustrations.map(function (il) {
        il.image = null; // chargée seulement quand on regarde la constellation
        return il;
      });
      if (horlogeDemarree) Celestial.redraw();
    })
    .catch(function (erreur) {
      console.warn("Illustrations indisponibles :", erreur);
    });

  // Distance angulaire (degrés) entre deux points [ascension droite, déclinaison]
  function distanceAngulaire(a, b) {
    const r = Math.PI / 180;
    const c = Math.sin(a[1] * r) * Math.sin(b[1] * r) + Math.cos(a[1] * r) * Math.cos(b[1] * r) * Math.cos((a[0] - b[0]) * r);
    return Math.acos(Math.max(-1, Math.min(1, c))) / r;
  }

  // Transformation affine qui envoie les 3 points de l'image {x, y} sur les 3 points de l'écran [u, v].
  // Renvoie [a, b, c, d, e, f] pour ctx.transform (règle de Cramer sur deux systèmes 3×3).
  function transformationAffine(src, dst) {
    const p = src[0], q = src[1], r = src[2];
    const det = p.x * (q.y - r.y) - q.x * (p.y - r.y) + r.x * (p.y - q.y);
    if (Math.abs(det) < 1e-9) return null;
    function resoudre(w0, w1, w2) { // w = A x + C y + E
      const A = (w0 * (q.y - r.y) - w1 * (p.y - r.y) + w2 * (p.y - q.y)) / det;
      const C = (p.x * (w1 - w2) - q.x * (w0 - w2) + r.x * (w0 - w1)) / det;
      return [A, C, w0 - A * p.x - C * p.y];
    }
    const u = resoudre(dst[0][0], dst[1][0], dst[2][0]);
    const v = resoudre(dst[0][1], dst[1][1], dst[2][1]);
    return [u[0], v[0], u[1], v[1], u[2], v[2]];
  }

  function dessinerIllustrations(ctx) {
    if (!calques.illustrations || illustrations.length === 0) return;
    const centre = centreVue();
    illustrations.forEach(function (il) {
      const d = distanceAngulaire(centre, il.centre);
      if (d >= il.rayon) return;
      if (!il.image) {
        il.image = new Image();
        il.image.onload = function () { Celestial.redraw(); };
        il.image.src = carte.dataset.dossierIllustrations + il.fichier;
        return;
      }
      if (!il.image.complete || !il.image.naturalWidth) return;
      const ecran = [];
      for (let i = 0; i < 3; i++) {
        const position = [il.ancrages[i].ra, il.ancrages[i].dec];
        if (!Celestial.clip(position)) return; // une étoile d'ancrage hors de la vue
        ecran.push(Celestial.mapProjection(position));
      }
      const t = transformationAffine(il.ancrages, ecran);
      if (!t) return;
      const proximite = Math.min(1, (1 - d / il.rayon) / (1 - PART_PLEINE_OPACITE));
      ctx.save();
      ctx.globalCompositeOperation = "lighter"; // fond noir de l'image = transparent
      ctx.globalAlpha = OPACITE_ILLUSTRATION * proximite;
      ctx.transform(t[0], t[1], t[2], t[3], t[4], t[5]);
      // Taille de référence des ancrages (le fichier peut être 2 ou 4 fois plus grand ou plus petit).
      // Dessinée deux fois : en mode additif, la luminosité double (les images sont assez sombres).
      ctx.drawImage(il.image, 0, 0, il.taille[0], il.taille[1]);
      ctx.drawImage(il.image, 0, 0, il.taille[0], il.taille[1]);
      ctx.restore();
    });
  }

  // --- Noms des constellations : majuscules espacées, comme dans Sky Guide -----------
  // Positions et noms français : constellations.json de d3-celestial (licence BSD), chargé une fois.
  // Rang 1 et 2 : toujours affichés ; rang 3 (petites constellations) : à partir du zoom ×1,5.
  let etiquettesConstellations = [];
  const nomsConstellations = {}; // abréviation UAI -> nom français
  const ESPACE_LETTRES = 3.2; // px entre deux lettres
  fetch(carte.dataset.datapath + "constellations.json")
    .then(function (reponse) {
      if (!reponse.ok) throw new Error("HTTP " + reponse.status);
      return reponse.json();
    })
    .then(function (donnees) {
      etiquettesConstellations = donnees.features.map(function (f) {
        return {
          texte: (f.properties.fr || f.properties.name).toLocaleUpperCase("fr"),
          position: f.geometry.coordinates, // [ascension droite entre -180° et 180°, déclinaison]
          rang: Number(f.properties.rank),
          largeurs: null, // largeur de chaque lettre, mesurée au premier dessin
        };
      });
      // Partie 8.1 : nom français d'après l'abréviation officielle (« Tau » -> « Taureau »)
      donnees.features.forEach(function (f) {
        nomsConstellations[f.id] = f.properties.fr || f.properties.name;
      });
      if (horlogeDemarree) Celestial.redraw();
    })
    .catch(function (erreur) {
      console.warn("Noms des constellations indisponibles :", erreur);
    });

  function dessinerConstellations(ctx) {
    if (!calques.constellations || etiquettesConstellations.length === 0) return;
    ctx.save();
    ctx.font = "500 12px Helvetica, Arial, sans-serif";
    ctx.textAlign = "left";
    ctx.textBaseline = "middle";
    ctx.fillStyle = "rgba(170, 186, 220, 0.78)";
    etiquettesConstellations.forEach(function (e) {
      if (e.rang === 3 && vue.zoom < 1.5) return;
      if (!Celestial.clip(e.position)) return;
      const pt = Celestial.mapProjection(e.position);
      const lettres = Array.from(e.texte);
      if (!e.largeurs) e.largeurs = lettres.map(function (l) { return ctx.measureText(l).width; });
      const total = e.largeurs.reduce(function (a, b) { return a + b; }, 0) + ESPACE_LETTRES * (lettres.length - 1);
      let x = pt[0] - total / 2;
      lettres.forEach(function (l, i) {
        ctx.fillText(l, x, pt[1]);
        x += e.largeurs[i] + ESPACE_LETTRES;
      });
    });
    ctx.restore();
  }

  // --- Partie 10 bis : astres étendus à leur vraie taille ---------------------------------------
  // Le serveur donne `apparence` (taille en degrés, forme, phase de la Lune). Le ciel profond et les
  // amas sont des VOILES : lumière additive, très transparente, bords flous. Ils éclaircissent le fond
  // sans jamais cacher une étoile (les étoiles de la bibliothèque restent visibles au travers).
  // Le Soleil et la Lune sont pleins : en vrai aussi, ils cachent ce qui est derrière eux.
  // De loin (forme de moins de TAILLE_MINI_FORME px), on garde le symbole habituel et le nom.
  const TEINTES = {
    galaxie: "255, 232, 200", // blanc chaud (vieilles étoiles)
    nebuleuse: "255, 120, 175", // rose (hydrogène)
    amas: "140, 180, 255", // bleuté (jeunes étoiles chaudes, gaz qui les éclaire)
  };
  const TAILLE_MINI_FORME = 7; // px
  const TAILLE_MINI_DISQUE = { soleil: 6, lune: 6 }; // px : rayon minimum du Soleil et de la Lune

  // Point à `distance` degrés de (ra, dec), dans la direction `angle` (0 = nord, 90 = est).
  function decaler(ra, dec, angle, distance) {
    const r = Math.PI / 180;
    const d = distance * r, a = angle * r, d0 = dec * r;
    const dec2 = Math.asin(Math.sin(d0) * Math.cos(d) + Math.cos(d0) * Math.sin(d) * Math.cos(a));
    const ra2 = ra * r + Math.atan2(Math.sin(a) * Math.sin(d) * Math.cos(d0), Math.cos(d) - Math.sin(d0) * Math.sin(dec2));
    return [(((ra2 / r) % 360) + 360) % 360, dec2 / r];
  }

  // Vecteur à l'écran (px) qui correspond à `distance` degrés dans la direction `angle` :
  // tient compte de la projection, du zoom et de la rotation de la vue.
  function vecteurEcran(p, pt, angle, distance) {
    const q = Celestial.mapProjection(decaler(p.ra, p.dec, angle, distance));
    return [q[0] - pt[0], q[1] - pt[1]];
  }

  // Voile flou en forme d'ellipse de demi-axes u et v (vecteurs à l'écran), en lumière additive.
  function dessinerVoile(ctx, pt, u, v, teinte, alpha) {
    if (Math.abs(u[0] * v[1] - u[1] * v[0]) < 0.5) return; // ellipse aplatie : rien à dessiner
    ctx.save();
    ctx.globalCompositeOperation = "lighter";
    ctx.transform(u[0], u[1], v[0], v[1], pt[0], pt[1]); // cercle de rayon 1 -> l'ellipse
    const g = ctx.createRadialGradient(0, 0, 0, 0, 0, 1);
    g.addColorStop(0, "rgba(" + teinte + "," + alpha + ")");
    g.addColorStop(0.4, "rgba(" + teinte + "," + (alpha * 0.5).toFixed(3) + ")");
    g.addColorStop(1, "rgba(" + teinte + ",0)");
    ctx.fillStyle = g;
    ctx.beginPath();
    ctx.arc(0, 0, 1, 0, 2 * Math.PI);
    ctx.fill();
    ctx.restore();
  }

  // Contour fin en pointillés : on sait où est l'objet même quand le voile est à peine visible.
  function contourEllipse(ctx, pt, u, v, teinte, alpha) {
    ctx.save();
    ctx.beginPath();
    for (let i = 0; i <= 64; i++) {
      const t = (i / 64) * 2 * Math.PI;
      const x = pt[0] + Math.cos(t) * u[0] + Math.sin(t) * v[0];
      const y = pt[1] + Math.cos(t) * u[1] + Math.sin(t) * v[1];
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.setLineDash([3, 4]);
    ctx.lineWidth = 1;
    ctx.strokeStyle = "rgba(" + teinte + "," + alpha + ")";
    ctx.stroke();
    ctx.restore();
  }

  // Dessine la forme ; renvoie son rayon à l'écran (px), ou 0 si elle est trop petite (symbole habituel).
  function dessinerApparence(ctx, o, p, pt) {
    const a = o.apparence;
    if (a.type === "soleil" || a.type === "lune") {
      const u = vecteurEcran(p, pt, 0, a.diametre / 2);
      const rayon = Math.max(Math.hypot(u[0], u[1]), TAILLE_MINI_DISQUE[a.type]);
      if (a.type === "soleil") dessinerSoleil(ctx, pt, rayon);
      else dessinerLune(ctx, p, pt, rayon, a);
      return rayon;
    }
    if (!calques.cielProfond) return 0;
    let u, v, teinte;
    if (a.type === "amas") {
      u = vecteurEcran(p, pt, 0, a.diametre / 2);
      v = vecteurEcran(p, pt, 90, a.diametre / 2);
      teinte = TEINTES.amas;
    } else {
      u = vecteurEcran(p, pt, a.angle, a.grand_axe / 2);
      v = vecteurEcran(p, pt, a.angle + 90, a.petit_axe / 2);
      teinte = TEINTES[a.teinte] || TEINTES.galaxie;
    }
    const taille = Math.max(Math.hypot(u[0], u[1]), Math.hypot(v[0], v[1]));
    if (taille < TAILLE_MINI_FORME) return 0;
    // Plus l'objet est grand à l'écran, plus le voile s'efface : on voit les étoiles dedans
    const alpha = Math.max(0.08, Math.min(0.22, (0.22 * 40) / taille));
    dessinerVoile(ctx, pt, u, v, teinte, alpha);
    if (a.type === "ellipse") {
      // noyau plus lumineux (centre de la galaxie, cœur de la nébuleuse)
      const k = a.teinte === "nebuleuse" ? 0.35 : 0.18;
      dessinerVoile(ctx, pt, [u[0] * k, u[1] * k], [v[0] * k, v[1] * k], teinte, Math.min(0.35, alpha * 1.6));
    }
    contourEllipse(ctx, pt, u, v, teinte, 0.45);
    return taille;
  }

  function dessinerSoleil(ctx, pt, rayon) {
    ctx.save();
    ctx.globalCompositeOperation = "lighter"; // halo
    const h = ctx.createRadialGradient(pt[0], pt[1], rayon * 0.8, pt[0], pt[1], rayon * 4);
    h.addColorStop(0, "rgba(255, 210, 110, 0.45)");
    h.addColorStop(1, "rgba(255, 210, 110, 0)");
    ctx.fillStyle = h;
    ctx.beginPath();
    ctx.arc(pt[0], pt[1], rayon * 4, 0, 2 * Math.PI);
    ctx.fill();
    ctx.globalCompositeOperation = "source-over"; // disque plein, bord plus sombre (assombrissement centre-bord)
    const d = ctx.createRadialGradient(pt[0], pt[1], 0, pt[0], pt[1], rayon);
    d.addColorStop(0, "#fffbea");
    d.addColorStop(0.7, "#ffe9a8");
    d.addColorStop(1, "#ffc94d");
    ctx.fillStyle = d;
    ctx.beginPath();
    ctx.arc(pt[0], pt[1], rayon, 0, 2 * Math.PI);
    ctx.fill();
    ctx.restore();
  }

  // La Lune avec sa phase : côté éclairé tourné vers le Soleil (angle_soleil), partie sombre
  // légèrement visible (lumière cendrée).
  function dessinerLune(ctx, p, pt, rayon, a) {
    const s = vecteurEcran(p, pt, a.angle_soleil, 1);
    const k = Math.max(0, Math.min(1, a.eclairement));
    ctx.save();
    ctx.globalCompositeOperation = "lighter"; // halo, plus fort près de la pleine Lune
    const h = ctx.createRadialGradient(pt[0], pt[1], rayon, pt[0], pt[1], rayon * 3);
    h.addColorStop(0, "rgba(200, 215, 255, " + (0.25 * k).toFixed(3) + ")");
    h.addColorStop(1, "rgba(200, 215, 255, 0)");
    ctx.fillStyle = h;
    ctx.beginPath();
    ctx.arc(pt[0], pt[1], rayon * 3, 0, 2 * Math.PI);
    ctx.fill();
    ctx.globalCompositeOperation = "source-over";
    ctx.translate(pt[0], pt[1]);
    ctx.rotate(Math.atan2(s[1], s[0])); // l'axe x pointe maintenant vers le Soleil
    ctx.beginPath();
    ctx.arc(0, 0, rayon, 0, 2 * Math.PI);
    ctx.fillStyle = "#2a303d"; // lumière cendrée
    ctx.fill();
    // Partie éclairée : demi-disque côté Soleil, fermé par le terminateur (demi-ellipse)
    const w = rayon * (2 * k - 1); // > 0 : gibbeuse, < 0 : croissant
    ctx.beginPath();
    ctx.arc(0, 0, rayon, -Math.PI / 2, Math.PI / 2, false);
    ctx.ellipse(0, 0, Math.abs(w), rayon, 0, Math.PI / 2, -Math.PI / 2, w < 0);
    ctx.closePath();
    ctx.fillStyle = "#eef1f7";
    ctx.fill();
    ctx.restore();
  }

  function dessinerObjet(ctx, o) {
    const p = ici(o);
    const position = [p.ra, p.dec]; // ascension droite, déclinaison (degrés)
    const vise = pointage && pointage.commande && pointage.commande.objet.id === o.id;
    const style = STYLES[o.categorie] || STYLES.etoile;
    if (o.trace && (o.id === selection || vise)) dessinerTrace(ctx, o, style.couleur);
    o.ecran = null;
    if (!Celestial.clip(position)) return;
    const pt = Celestial.mapProjection(position);
    o.ecran = pt; // dernière position dessinée (pour savoir quand un satellite a bougé)
    // Partie 10 bis : Soleil, Lune, amas et ciel profond à leur vraie taille (0 = trop petit)
    const etendu = o.apparence ? dessinerApparence(ctx, o, p, pt) : 0;
    o.rayonEcran = etendu; // pour toucher l'objet n'importe où dans sa forme
    const rayon = Math.max(style.rayon, etendu);

    ctx.save();
    ctx.lineWidth = 1.5;
    if (!etendu) {
      ctx.beginPath();
      ctx.arc(pt[0], pt[1], style.rayon, 0, 2 * Math.PI);
      if (style.forme === "disque") {
        ctx.fillStyle = style.couleur;
        ctx.fill();
        ctx.strokeStyle = "#05070d";
      } else {
        ctx.strokeStyle = style.couleur;
      }
      ctx.stroke();
    }
    if (o.id === selection) {
      // halo autour de l'objet sélectionné
      ctx.beginPath();
      ctx.arc(pt[0], pt[1], rayon + 7, 0, 2 * Math.PI);
      ctx.strokeStyle = "#ffffff";
      ctx.stroke();
    }
    if (vise) {
      // l'objet que le bras vise : un anneau de la couleur du réticule
      ctx.beginPath();
      ctx.arc(pt[0], pt[1], rayon + 4, 0, 2 * Math.PI);
      ctx.strokeStyle = COULEUR_BRAS;
      ctx.stroke();
    }
    if (style.nom) {
      ctx.font = "600 14px Helvetica, Arial, sans-serif";
      ctx.textAlign = "left";
      ctx.textBaseline = "bottom";
      // nom en haut à droite de la forme (au plus 40 px du centre : un grand objet zoomé garde son nom près de lui)
      const ecart = etendu ? Math.max(style.rayon, Math.min(etendu, 40) * 0.75) : style.rayon;
      const x = pt[0] + ecart + 4;
      const y = pt[1] - ecart + 2;
      ctx.lineJoin = "round";
      ctx.lineWidth = 3;
      ctx.strokeStyle = "rgba(5, 7, 13, 0.85)"; // contour sombre : le nom se lit sur les étoiles
      ctx.strokeText(o.nom, x, y);
      ctx.fillStyle = style.texte;
      ctx.fillText(o.nom, x, y);
    }
    ctx.restore();
  }

  // Quand la carte est prête : premier chargement des objets, puis l'horloge démarre
  let horlogeDemarree = false;
  function carteprete() {
    placerCanevas();
    if (instantObjets === null) chargerObjets(); // un zoom redessine la carte sans refaire la requête
    chargerPointage();
    if (horlogeDemarree) return; // la carte peut être redessinée au redimensionnement
    horlogeDemarree = true;
    setInterval(chargerPointage, PERIODE_POINTAGE);
    setInterval(tic, PERIODE_TIC);
  }

  // À déclarer AVANT Celestial.display : le callback est lancé quand la carte est prête
  Celestial.add({ type: "raw", callback: carteprete, redraw: dessinerObjets });

  // ===========================================================================
  // 5. Sélection d'un objet et fiche
  // ===========================================================================

  const NOMS_CATEGORIES = {
    etoile: "Étoile", planete: "Planète", lune: "Lune", amas: "Amas", satellite: "Satellite",
    soleil: "Notre étoile", ciel_profond: "Ciel profond",
  };
  const POINTS_CARDINAUX = [
    "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSO", "SO", "OSO", "O", "ONO", "NO", "NNO",
  ];
  const RAYON_TOUCHE = 24; // px : distance maxi entre la souris et un objet pour le sélectionner
  const RAYON_TOUCHE_DOIGT = 36; // px : un doigt est plus large qu'un curseur
  const FICHE_PERIMEE_APRES = 6 * 3600 * 1000; // ms virtuelles

  const fmtNombre = new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 1 });
  const fmtJour = new Intl.DateTimeFormat("en-CA", { timeZone: lieu.fuseau }); // AAAA-MM-JJ

  const elFiche = document.getElementById("fiche");
  const el = {
    image: document.getElementById("fiche-image"),
    nom: document.getElementById("fiche-nom"),
    sousTitre: document.getElementById("fiche-sous-titre"),
    hauteur: document.getElementById("fiche-hauteur"),
    direction: document.getElementById("fiche-direction"),
    lever: document.getElementById("fiche-lever"),
    coucher: document.getElementById("fiche-coucher"),
    noteHorizon: document.getElementById("fiche-note-horizon"),
    courbe: document.getElementById("fiche-courbe"),
    passages: document.getElementById("fiche-passages"),
    listePassages: document.getElementById("fiche-liste-passages"),
    aucunPassage: document.getElementById("fiche-aucun-passage"),
    description: document.getElementById("fiche-description"),
    alerte: document.getElementById("fiche-alerte"),
    credit: document.getElementById("fiche-credit"),
    sources: document.getElementById("fiche-sources"),
    magnitude: document.getElementById("fiche-magnitude"),
    distance: document.getElementById("fiche-distance"),
    ligneEclairement: document.getElementById("ligne-eclairement"),
    eclairement: document.getElementById("fiche-eclairement"),
    coordonnees: document.getElementById("fiche-coordonnees"),
    ceSoir: document.getElementById("fiche-ce-soir"),
  };

  let selection = null; // id de l'objet sélectionné (ou null)
  let fiche = null; // réponse de /api/ciel/objets/<id>/
  let instantFiche = null; // instant virtuel auquel la fiche a été calculée
  let ficheEnCours = false;
  let derniereDemandeFiche = 0;
  let dernierRafraichissementFiche = 0;

  // --- Toucher la carte : sélectionner l'objet le plus proche du doigt --------

  function objetProche(px, py, rayon) {
    let meilleur = null;
    let dmin = rayon;
    objets.forEach(function (o) {
      if (!objetAffiche(o)) return; // 8.4 : un astre masqué ne se touche pas
      const p = ici(o);
      const position = [p.ra, p.dec];
      if (!Celestial.clip(position)) return;
      const pt = Celestial.mapProjection(position);
      // Partie 10 bis : un astre étendu se touche dans toute sa forme (le plus proche du centre l'emporte)
      const centre = Math.hypot(pt[0] - px, pt[1] - py);
      const d = o.rayonEcran ? Math.max(0, centre - o.rayonEcran) + centre * 0.01 : centre;
      if (d < dmin) {
        dmin = d;
        meilleur = o;
      }
    });
    return meilleur;
  }

  // On distingue un « toucher » d'un « glisser » (qui déplace la carte).
  // On écoute tout le document : toucher le ciel vide, hors du disque, désélectionne.
  const INTERFACE = "#fiche, #panneau-temps, #panneau-calques, #panneau-recherche, #panneau-appareil, #panneau-code, #panneau-evenements, #panneau-point, #panneau-visite, #panneau-journal, #panneau-observation, #etat-appareil, #boussole, #zoom, #barre";
  let depart = null;
  // Partie 8.4 : un appui long (0,6 s sans bouger) sur le ciel choisit ce point (cible personnalisée)
  const DUREE_APPUI_LONG = 600;
  let minuteurAppuiLong = null;
  let appuiLongFait = false;
  function annulerAppuiLong() {
    clearTimeout(minuteurAppuiLong);
    minuteurAppuiLong = null;
  }
  document.addEventListener("pointerdown", function (e) {
    if (e.isPrimary && !e.target.closest(INTERFACE)) {
      depart = { x: e.clientX, y: e.clientY, t: Date.now() };
      appuiLongFait = false;
      annulerAppuiLong();
      const x = e.clientX, y = e.clientY;
      minuteurAppuiLong = setTimeout(function () {
        minuteurAppuiLong = null;
        if (!depart || glisse || pointeurs.size > 1) return;
        appuiLongFait = true;
        choisirPoint(x, y);
      }, DUREE_APPUI_LONG);
    } else if (!e.isPrimary) {
      annulerAppuiLong(); // un deuxième doigt : pincement
    }
  });
  document.addEventListener("pointermove", function (e) {
    if (minuteurAppuiLong && depart && Math.hypot(e.clientX - depart.x, e.clientY - depart.y) > 10) annulerAppuiLong();
  });
  carte.addEventListener("contextmenu", function (e) {
    e.preventDefault(); // le clic droit ou l'appui long ne doit pas ouvrir un menu
  });
  document.addEventListener("pointerup", function (e) {
    annulerAppuiLong();
    if (appuiLongFait) { // l'appui long a déjà choisi un point : ce n'est pas un toucher
      appuiLongFait = false;
      depart = null;
      return;
    }
    if (!e.isPrimary || !depart) return;
    const deplacement = Math.hypot(e.clientX - depart.x, e.clientY - depart.y);
    const duree = Date.now() - depart.t;
    depart = null;
    // Un toucher bref et immobile. Le délai est large : le téléphone peut tarder à traiter le geste.
    if (deplacement > (e.pointerType === "touch" ? 10 : 6) || duree > 800) return; // c'était un glisser
    const canvas = carte.querySelector("canvas");
    if (!canvas) return;
    const zone = canvas.getBoundingClientRect();
    const rayon = e.pointerType === "touch" ? RAYON_TOUCHE_DOIGT : RAYON_TOUCHE;
    const o = objetProche(e.clientX - zone.left, e.clientY - zone.top, rayon);
    selectionner(o ? o.id : null);
  });

  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") {
      selectionner(null);
      ouvrir(null);
    }
  });
  document.getElementById("fiche-fermer").addEventListener("click", function () {
    selectionner(null);
  });

  // La fiche cache le bas de l'écran : on remonte la carte pour que tout le disque
  // reste visible et touchable au-dessus. (getBoundingClientRect tient compte du décalage.)

  // --- Ouvrir / fermer la fiche ------------------------------------------------

  function selectionner(id) {
    selection = id;
    fiche = null;
    elFiche.hidden = id === null;
    document.body.classList.toggle("fiche-ouverte", id !== null);
    if (id !== null) {
      ouvrir(null); // un seul panneau à la fois
      remplirFiche();
      chargerFiche();
    }
    majEtatPanneaux();
    Celestial.redraw(); // le halo autour de l'objet apparaît / disparaît
  }

  function chargerFiche() {
    ficheEnCours = true;
    derniereDemandeFiche = Date.now();
    const id = selection;
    const cible = horloge.virtuel;
    const url = carte.dataset.urlObjets + id + "/?instant=" + encodeURIComponent(new Date(cible).toISOString());
    fetch(url)
      .then(function (reponse) {
        if (!reponse.ok) throw new Error("HTTP " + reponse.status);
        return reponse.json();
      })
      .then(function (donnees) {
        if (selection !== id) return; // l'utilisateur a changé d'objet entre-temps
        fiche = donnees;
        instantFiche = cible;
        remplirFiche();
      })
      .catch(function (erreur) {
        console.warn("Fiche indisponible :", erreur);
      })
      .finally(function () {
        ficheEnCours = false;
      });
  }

  // La fiche est calculée pour 24 h : on la recalcule quand elle est dépassée
  function fichePerimee() {
    if (!fiche || ficheEnCours || Date.now() - derniereDemandeFiche < DELAI_MINI_REQUETES) return false;
    return (
      Math.abs(horloge.virtuel - instantFiche) > FICHE_PERIMEE_APRES ||
      fiche.levers_couchers.some(function (e) { return Date.parse(e.instant) < horloge.virtuel; })
    );
  }

  // Appelée à chaque tic de l'horloge
  function majFiche() {
    if (selection === null) return;
    if (fichePerimee()) chargerFiche();
    if (Date.now() - dernierRafraichissementFiche >= 1000) remplirFiche();
  }

  // --- Contenu de la fiche -------------------------------------------------------

  // Position à l'instant virtuel, interpolée entre les points de la trajectoire
  function positionActuelle() {
    const sat = objets.find(function (obj) { return obj.id === selection && obj.trace; });
    if (sat) return ici(sat); // 6.3 : un satellite va trop vite pour la courbe à 10 min
    const pts = fiche && fiche.trajectoire;
    if (pts && pts.length > 1) {
      const t0 = Date.parse(pts[0].instant);
      const pas = Date.parse(pts[1].instant) - t0;
      const x = (horloge.virtuel - t0) / pas;
      const i = Math.floor(x);
      if (i >= 0 && i < pts.length - 1) {
        const f = x - i;
        const a = pts[i];
        const b = pts[i + 1];
        const ecartAzimut = ((b.azimut - a.azimut + 540) % 360) - 180; // plus court chemin
        return {
          elevation: a.elevation + (b.elevation - a.elevation) * f,
          azimut: (a.azimut + ecartAzimut * f + 360) % 360,
        };
      }
    }
    const o = objets.find(function (obj) { return obj.id === selection; });
    return o ? { elevation: o.elevation, azimut: o.azimut } : null;
  }

  function heureEvenement(type) {
    const evt = fiche && fiche.levers_couchers.find(function (e) { return e.evenement === type; });
    if (!evt) return "—";
    const d = new Date(evt.instant);
    const demain = fmtJour.format(d) !== fmtJour.format(new Date(horloge.virtuel));
    return fmtHeure.format(d) + (demain ? " (demain)" : "");
  }

  function remplirFiche() {
    dernierRafraichissementFiche = Date.now();
    const o = objets.find(function (obj) { return obj.id === selection; });
    const nom = fiche ? fiche.nom : o ? o.nom : "";
    const categorie = NOMS_CATEGORIES[fiche ? fiche.categorie : o && o.categorie] || "";
    el.nom.textContent = nom;
    // Constellations saisies dans l'administration, sinon celle où se trouve l'astre (8.1)
    const dansConstellation = fiche && fiche.constellation_iau && nomsConstellations[fiche.constellation_iau];
    const constellations = fiche && fiche.constellations.length ? " · " + fiche.constellations.join(", ")
      : dansConstellation ? " · " + dansConstellation : "";
    el.sousTitre.textContent = categorie + constellations;

    const pos = positionActuelle();
    if (pos) {
      el.hauteur.textContent = fmtNombre.format(pos.elevation) + "°";
      const point = POINTS_CARDINAUX[Math.round(pos.azimut / 22.5) % 16];
      el.direction.textContent = point + " · " + (Math.round(pos.azimut) % 360) + "°";
    }

    el.lever.textContent = heureEvenement("lever");
    el.coucher.textContent = heureEvenement("coucher");
    const sansEvenement = fiche && fiche.levers_couchers.length === 0 && pos;
    el.noteHorizon.hidden = !sansEvenement;
    if (sansEvenement) {
      el.noteHorizon.textContent =
        pos.elevation > 0 ? "Reste au-dessus de l'horizon pendant 24 h." : "Reste sous l'horizon pendant 24 h.";
    } else if (pos && pos.elevation <= 0) {
      el.noteHorizon.hidden = false;
      el.noteHorizon.textContent = "Sous l'horizon en ce moment.";
    }

    // Texte et image : toujours via textContent / src, jamais innerHTML
    // (le contenu vient de l'admin, on ne le traite jamais comme du HTML)
    // Partie 10 : avertissement de sécurité dans la fiche du Soleil
    el.alerte.hidden = !(fiche && fiche.categorie === "soleil");
    el.description.textContent = fiche
      ? fiche.description || "Description à venir."
      : "";
    if (fiche && fiche.image) {
      el.image.src = fiche.image;
      el.image.alt = fiche.nom;
      el.image.hidden = false;
    } else {
      el.image.hidden = true;
    }
    remplirCredits();
    remplirInfosPlus();
    majBoutonsVisite();
    majJournalFiche();
    const passages = fiche && fiche.passages;
    // 6.3 : pour un satellite, la liste des passages remplace la courbe (style : `hidden` ne marche pas sur un SVG)
    el.courbe.style.display = passages ? "none" : "";
    if (passages) remplirPassages(passages); else el.passages.hidden = true;
    tracerCourbe();
    majBoutonPointer();
  }

  // Un instant déjà atteint par l'heure de la carte (à une minute près)
  function dejaCommence(iso) {
    return Date.parse(iso) <= horloge.virtuel + 60000;
  }

  // Partie 8.1 : magnitude, distance, éclairement de la Lune, coordonnées, visibilité ce soir
  const fmtEntier = new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 0 });

  function texteDistance(f) {
    if (f.distance_al !== null && f.distance_al !== undefined) {
      return fmtNombre.format(f.distance_al) + " années-lumière";
    }
    if (f.distance_km === null || f.distance_km === undefined) return "—";
    if (f.distance_km >= 1e9) return fmtNombre.format(f.distance_km / 149597870.7) + " UA"; // unité astronomique
    if (f.distance_km >= 1e6) return fmtNombre.format(f.distance_km / 1e6) + " millions de km";
    return fmtEntier.format(f.distance_km) + " km";
  }

  // 88.79° -> « 5 h 55 min 10 s », +7.41° -> « +7° 24′ »
  function texteCoordonnees(ra, dec) {
    const h = ra / 15;
    const hh = Math.floor(h);
    const mm = Math.floor((h - hh) * 60);
    const ss = Math.round(((h - hh) * 60 - mm) * 60);
    const signe = dec < 0 ? "−" : "+";
    const d = Math.abs(dec);
    const dd = Math.floor(d);
    const dm = Math.round((d - dd) * 60);
    return "AD " + hh + " h " + mm + " min " + Math.min(ss, 59) + " s · Déc " + signe + dd + "° " + Math.min(dm, 59) + "′";
  }

  function remplirInfosPlus() {
    if (!fiche) {
      [el.magnitude, el.distance, el.coordonnees].forEach(function (e) { e.textContent = "—"; });
      el.ligneEclairement.hidden = true;
      el.ceSoir.hidden = true;
      return;
    }
    el.magnitude.textContent = fiche.magnitude === null ? "—" : fmtNombre.format(fiche.magnitude);
    el.distance.textContent = texteDistance(fiche);
    el.ligneEclairement.hidden = fiche.eclairement === null;
    if (fiche.eclairement !== null) el.eclairement.textContent = Math.round(fiche.eclairement * 100) + " %";
    el.coordonnees.textContent = texteCoordonnees(fiche.ra, fiche.dec);
    const soir = fiche.ce_soir;
    el.ceSoir.hidden = !soir || Boolean(fiche.passages); // un satellite a sa liste de passages
    if (soir) el.ceSoir.textContent = texteCeSoir(soir, null);
  }

  // « Ce soir : visible de … à …, au plus haut vers … » (fiche et point du ciel)
  function texteCeSoir(soir, sujet) {
    if (!soir.debut_nuit) return "Pas de nuit dans les 24 prochaines heures.";
    const v = soir.visible;
    if (!v) return (sujet ? sujet + " ne monte" : "Pas visible ce soir (ne monte") + " pas à 10° pendant la nuit" + (sujet ? " ce soir." : ").");
    return (dejaCommence(v.de) ? "Ce soir : visible dès maintenant jusqu'à " + fmtHeure.format(new Date(v.a))
      : "Ce soir : visible de " + fmtHeure.format(new Date(v.de)) + " à " + fmtHeure.format(new Date(v.a))) +
      (dejaCommence(v.instant) ? "." : ", au plus haut (" + Math.round(v.hauteur_max) + "°) vers " + fmtHeure.format(new Date(v.instant)) + ".");
  }

  // Partie 6.3 : prochains passages d'un satellite (au moins 10° de hauteur, 48 h)
  const fmtJourCourt = new Intl.DateTimeFormat("fr-FR", {
    weekday: "short", day: "numeric", month: "short", timeZone: lieu.fuseau,
  });
  const NB_PASSAGES_AFFICHES = 6;
  let signaturePassages = "";

  function pointCardinal(azimut) {
    return azimut === null ? "?" : POINTS_CARDINAUX[Math.round(azimut / 22.5) % 16];
  }

  function remplirPassages(passages) {
    const avenir = passages.filter(function (p) {
      return !p.coucher || Date.parse(p.coucher) > horloge.virtuel;
    }).slice(0, NB_PASSAGES_AFFICHES);
    el.passages.hidden = false;
    const signature = avenir.map(function (p) { return p.culmination; }).join("|");
    if (signature === signaturePassages) return; // rien de nouveau : on ne reconstruit pas la liste
    signaturePassages = signature;
    el.listePassages.replaceChildren();
    el.aucunPassage.hidden = avenir.length > 0;
    // Construit avec createElement / textContent, jamais innerHTML
    avenir.forEach(function (p) {
      const li = document.createElement("li");
      const debut = p.lever && Date.parse(p.lever) > horloge.virtuel ? new Date(p.lever) : null; // null : en cours
      const quand = document.createElement("span");
      quand.className = "quand";
      quand.textContent = debut
        ? fmtJourCourt.format(debut) + " · " + fmtHeure.format(debut) + (p.coucher ? " → " + fmtHeure.format(new Date(p.coucher)) : "")
        : "En cours" + (p.coucher ? " · jusqu'à " + fmtHeure.format(new Date(p.coucher)) : "");
      const detail = document.createElement("span");
      detail.className = "detail";
      detail.textContent = "max " + Math.round(p.hauteur_max) + "° · " +
        pointCardinal(p.azimut_lever) + " → " + pointCardinal(p.azimut_coucher);
      li.append(quand, detail);
      if (p.visible) {
        const badge = document.createElement("span");
        badge.className = "badge";
        badge.textContent = "visible à l'œil nu";
        li.append(badge);
      }
      el.listePassages.appendChild(li);
    });
  }

  // Un lien seulement vers une adresse web (jamais « javascript: » ou autre) ; le texte via textContent
  function lienExterne(adresse, texte) {
    let url;
    try {
      url = new URL(adresse);
    } catch (erreur) {
      return null;
    }
    if (url.protocol !== "https:" && url.protocol !== "http:") return null;
    const a = document.createElement("a");
    a.href = url.href;
    a.target = "_blank";
    a.rel = "noopener";
    a.textContent = texte || url.hostname.replace(/^www\./, "");
    return a;
  }

  // Crédit de l'image (obligatoire pour une image sous licence libre) et sources de la description
  function remplirCredits() {
    const credit = fiche && fiche.image && fiche.image_credit;
    el.credit.replaceChildren();
    el.credit.hidden = !credit;
    if (credit) {
      const morceaux = [credit.auteur, credit.licence].filter(Boolean).join(" · ");
      el.credit.append("Image : " + morceaux);
      const lien = lienExterne(credit.source, "source");
      if (lien) el.credit.append(" · ", lien);
    }
    const sources = (fiche && fiche.sources) || [];
    el.sources.replaceChildren();
    el.sources.hidden = sources.length === 0;
    if (sources.length) {
      el.sources.append("Sources : ");
      sources.forEach(function (adresse, i) {
        const lien = lienExterne(adresse);
        if (!lien) return;
        if (el.sources.childNodes.length > 1) el.sources.append(", ");
        el.sources.append(lien);
      });
    }
  }

  // Petite courbe « hauteur sur 24 h », avec un point pour l'instant actuel
  function tracerCourbe() {
    const NS = "http://www.w3.org/2000/svg";
    const L = 300, H = 64, MARGE = 5;
    el.courbe.replaceChildren();
    const pts = fiche && fiche.trajectoire;
    if (!pts || pts.length < 2) return;

    const hauteurs = pts.map(function (p) { return p.elevation; });
    const mini = Math.min(-10, Math.min.apply(null, hauteurs));
    const maxi = Math.max(10, Math.max.apply(null, hauteurs));
    const y = function (e) { return H - MARGE - ((e - mini) / (maxi - mini)) * (H - 2 * MARGE); };
    const t0 = Date.parse(pts[0].instant);
    const duree = Date.parse(pts[pts.length - 1].instant) - t0;
    const x = function (ms) { return MARGE + Math.min(1, Math.max(0, (ms - t0) / duree)) * (L - 2 * MARGE); };

    function ajouter(nom, attributs) {
      const n = document.createElementNS(NS, nom);
      Object.keys(attributs).forEach(function (k) { n.setAttribute(k, attributs[k]); });
      el.courbe.appendChild(n);
    }
    ajouter("rect", { class: "sous-horizon", x: 0, y: y(0), width: L, height: H - y(0) });
    ajouter("line", { class: "horizon", x1: 0, x2: L, y1: y(0), y2: y(0) });
    ajouter("polyline", {
      class: "courbe",
      points: pts.map(function (p) { return x(Date.parse(p.instant)).toFixed(1) + "," + y(p.elevation).toFixed(1); }).join(" "),
    });
    const pos = positionActuelle();
    if (pos) ajouter("circle", { class: "maintenant", cx: x(horloge.virtuel), cy: y(pos.elevation), r: 4 });
  }

  // ===========================================================================
  // 6. L'appareil : pastille d'état, bouton « Pointer » et réticule sur la carte
  // ===========================================================================

  const PERIODE_POINTAGE = 1000; // ms entre deux lectures de l'état de l'appareil
  const COULEUR_BRAS = "#5dffb0";
  const NOMS_MODES = {
    repos: "Au repos", deplacement: "En déplacement", suivi: "En suivi", erreur: "Erreur",
  };

  const elEtat = {
    point: document.getElementById("etat-point"),
    titre: document.getElementById("etat-titre"),
    detail: document.getElementById("etat-detail"),
  };
  const elPointer = document.getElementById("btn-pointer");
  const elNoteAppareil = document.getElementById("fiche-note-appareil");

  let pointage = null; // dernière réponse de /api/pointage/
  let injoignable = false; // le serveur ne répond pas
  let pointageEnCours = false;
  let envoiEnCours = false;
  let messageErreur = "";
  let finMessageErreur = 0;

  // Position du réticule : la position affichée glisse vers la dernière position reçue,
  // sinon il avancerait par bonds d'une seconde.
  let bras = null; // { ra, dec } affichés
  let brasDepart = null;
  let brasArrivee = null;
  let brasT0 = 0;

  // --- Lecture de l'état -------------------------------------------------------

  function chargerPointage() {
    if (pointageEnCours || document.hidden) return;
    pointageEnCours = true;
    fetch(carte.dataset.urlPointage)
      .then(function (reponse) {
        if (!reponse.ok) throw new Error("HTTP " + reponse.status);
        return reponse.json();
      })
      .then(recevoirPointage)
      .catch(function (erreur) {
        console.warn("État de l'appareil indisponible :", erreur);
        injoignable = true;
        bras = brasDepart = brasArrivee = null;
        afficherEtat();
        majBoutonPointer();
        Celestial.redraw();
      })
      .finally(function () {
        pointageEnCours = false;
      });
  }

  // Ce qui change l'image de la carte (position du bras, cible). Sans changement, pas de redessin :
  // sur téléphone, un redessin coûte cher et retarde les touchers.
  function signaturePointage() {
    const c = pointage && pointage.commande;
    return (bras ? "bras" : "-") + "/" + (!c ? "-" : c.objet.id !== null ? c.objet.id : JSON.stringify(c.coordonnees));
  }

  function recevoirPointage(donnees) {
    const avant = signaturePointage();
    pointage = donnees;
    injoignable = false;
    const a = donnees.appareil;
    if (a && a.connecte && a.ra !== null) {
      const arrivee = { ra: a.ra, dec: a.dec };
      brasDepart = bras ? { ra: bras.ra, dec: bras.dec } : arrivee;
      brasArrivee = arrivee;
      brasT0 = Date.now();
      if (!bras) bras = arrivee;
    } else {
      bras = brasDepart = brasArrivee = null; // hors ligne : pas de réticule
    }
    afficherEtat();
    majBoutonPointer();
    majPanneauPoint();
    afficherVisite();
    if (signaturePointage() !== avant) Celestial.redraw();
  }

  // Appelée à chaque tic : fait avancer le réticule. Renvoie true s'il a bougé.
  function animerBras() {
    if (!bras || !brasArrivee) return false;
    const f = Math.min(1, (Date.now() - brasT0) / PERIODE_POINTAGE);
    const dra = ((brasArrivee.ra - brasDepart.ra + 540) % 360) - 180; // plus court chemin en ra
    const nouveau = {
      ra: (brasDepart.ra + dra * f + 360) % 360,
      dec: brasDepart.dec + (brasArrivee.dec - brasDepart.dec) * f,
    };
    const bouge = Math.abs(nouveau.ra - bras.ra) > 1e-4 || Math.abs(nouveau.dec - bras.dec) > 1e-4;
    bras = nouveau;
    return bouge;
  }

  // --- Pastille d'état (en haut de l'écran) ------------------------------------

  function afficherEtat() {
    const a = pointage && pointage.appareil;
    const c = pointage && pointage.commande;
    let niveau = "hors";
    let titre;
    const details = [];

    if (injoignable) {
      titre = "Serveur injoignable";
    } else if (!pointage) {
      titre = "Appareil…";
    } else if (!a) {
      titre = "Aucun appareil";
    } else if (!a.connecte) {
      titre = "Appareil hors ligne";
      if (c) details.push("Cible : " + c.objet.nom);
    } else {
      niveau = a.mode === "erreur" ? "erreur" : "ok";
      titre = "Appareil connecté";
      details.push(NOMS_MODES[a.mode] || a.mode);
      if (c) details.push(c.objet.nom);
      if (c && pointage.ecart_deg !== null) details.push("écart " + fmtNombre.format(pointage.ecart_deg) + "°");
      if (a.elevation !== null && a.elevation < 0) details.push("sous l'horizon");
      if (a.batterie !== null) details.push(a.batterie + " %");
    }

    majPanneauAppareil();
    elEtat.point.className = niveau === "hors" ? "" : niveau;
    elEtat.titre.textContent = titre;
    elEtat.detail.textContent = details.join(" · ");
    elEtat.detail.hidden = details.length === 0;
  }

  // --- Panneau de l'appareil (ouvert en touchant la pastille) ---------------------

  const elApp = {
    etat: document.getElementById("app-etat"),
    mode: document.getElementById("app-mode"),
    batterie: document.getElementById("app-batterie"),
    vu: document.getElementById("app-vu"),
    cible: document.getElementById("app-cible"),
    ecart: document.getElementById("app-ecart"),
    note: document.getElementById("app-note"),
    voir: document.getElementById("app-voir"),
    arreter: document.getElementById("app-arreter"),
    pilotage: document.getElementById("app-pilotage"),
    verrou: document.getElementById("app-verrou"),
  };

  function depuis(iso) {
    if (!iso) return "jamais";
    const s = Math.max(0, Math.round((Date.now() - Date.parse(iso)) / 1000));
    if (s < 60) return "il y a " + s + " s";
    if (s < 3600) return "il y a " + Math.round(s / 60) + " min";
    return "il y a " + Math.round(s / 3600) + " h";
  }

  function majPanneauAppareil() {
    if (elPanAppareil.hidden) return; // rien à mettre à jour s'il est fermé
    const a = pointage && pointage.appareil;
    const c = pointage && pointage.commande;
    elApp.etat.textContent = injoignable ? "Serveur injoignable" : !pointage ? "…" : !a ? "Aucun appareil" : a.connecte ? "Connecté" : "Hors ligne";
    elApp.mode.textContent = a && a.mode ? NOMS_MODES[a.mode] || a.mode : "—";
    elApp.batterie.textContent = a && a.batterie !== null ? a.batterie + " %" : "—";
    elApp.vu.textContent = a ? depuis(a.derniere_vue) : "—";
    const prog = c && c.programme;
    elApp.cible.textContent = !c ? "Aucune" : c.objet.nom + (prog ? " (visite " + prog.etape + "/" + prog.etapes.length + ")" : "");
    elApp.ecart.textContent = c && pointage.ecart_deg !== null ? fmtNombre.format(pointage.ecart_deg) + "°" : "—";
    elApp.voir.hidden = !c;
    elApp.arreter.hidden = !c;
    elApp.arreter.disabled = envoiEnCours;
    let note = "";
    if (Date.now() < finMessageErreur) note = messageErreur;
    else if (c && a && !a.connecte) note = "La commande attend que l'appareil soit en ligne.";
    else if (!c && a) note = "Touche un astre puis « Pointer » pour viser.";
    elApp.note.textContent = note;
    elApp.note.hidden = note === "";

    const p = pointage && pointage.pilotage;
    elApp.pilotage.textContent = !p ? "" : !p.configure
      ? "Pilotage impossible : aucun code n'est configuré sur le serveur (code_pilotage.txt)."
      : p.autorise ? "Pilotage autorisé sur ce navigateur." : "Pilotage verrouillé : le code sera demandé.";
    elApp.verrou.hidden = !p || !p.configure;
    elApp.verrou.textContent = p && p.autorise ? "Verrouiller" : "Entrer le code";
  }

  // « Verrouiller » retire l'autorisation de ce navigateur ; « Entrer le code » la demande
  elApp.verrou.addEventListener("click", function () {
    const p = pointage && pointage.pilotage;
    if (!p || !p.autorise) {
      demanderCode(null);
      return;
    }
    posterJson(carte.dataset.urlPilotageFin, null).then(function (r) {
      if (r.statut === 200 && pointage) pointage.pilotage = r.donnees.pilotage;
      majPanneauAppareil();
      majBoutonPointer();
    }).catch(function () {});
  });

  // --- Partie 5 : le panneau du code de pilotage ----------------------------------
  // Ouvert quand le serveur répond « code requis » (ou par « Entrer le code ») ; après un bon
  // code, l'action en attente est relancée et la fiche qui était ouverte revient.

  let codeEnCours = false;

  function demanderCode(action) {
    ficheAvantCode = selection;
    if (selection !== null) selectionner(null);
    ouvrir("code");
    actionEnAttente = action; // après ouvrir(), qui annule l'action en attente précédente
    elCodeChamp.value = "";
    const p = pointage && pointage.pilotage;
    if (p && !p.configure) afficherMessageCode("Aucun code n'est configuré sur le serveur : crée le fichier code_pilotage.txt.");
    else elCodeMessage.hidden = true;
    elCodeChamp.focus();
  }

  function afficherMessageCode(texte) {
    elCodeMessage.textContent = texte;
    elCodeMessage.hidden = false;
  }

  // POST JSON avec le jeton CSRF ; renvoie {statut, donnees} sans lever d'erreur sur un refus
  function posterJson(url, corps) {
    return fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRFToken": cookie("csrftoken") },
      body: corps ? JSON.stringify(corps) : undefined,
    }).then(function (reponse) {
      return reponse.json().catch(function () { return {}; }).then(function (donnees) {
        return { statut: reponse.status, donnees: donnees };
      });
    });
  }

  elCodeFormulaire.addEventListener("submit", function (e) {
    e.preventDefault();
    if (codeEnCours) return;
    codeEnCours = true;
    elCodeValider.disabled = true;
    posterJson(carte.dataset.urlPilotage, { code: elCodeChamp.value })
      .then(function (r) {
        if (r.statut === 200) {
          if (pointage) pointage.pilotage = r.donnees.pilotage;
          const action = actionEnAttente;
          const fiche = ficheAvantCode;
          elCodeChamp.value = "";
          ouvrir(null);
          if (fiche !== null) selectionner(fiche);
          if (action && action.relancer) action.relancer(); // Partie 9 : une action autre qu'un pointage
          else if (action) envoyer(action.url, action.corps);
          majPanneauAppareil();
          majBoutonPointer();
          return;
        }
        const d = r.donnees;
        let message = d.erreur || "Erreur " + r.statut;
        if (r.statut === 403 && d.essais_restants !== undefined) {
          message = "Code incorrect. " + d.essais_restants + (d.essais_restants > 1 ? " essais restants." : " essai restant.");
        } else if (r.statut === 403) {
          message = "Session expirée : recharge la page.";
        } else if (r.statut === 429) {
          message = "Trop d'essais. Réessaie dans " + Math.max(1, Math.ceil((d.attente_s || 60) / 60)) + " min.";
        }
        afficherMessageCode(message);
        elCodeChamp.select();
      })
      .catch(function () {
        afficherMessageCode("Serveur injoignable.");
      })
      .finally(function () {
        codeEnCours = false;
        elCodeValider.disabled = false;
      });
  });

  // « Voir la cible » : la vue se tourne vers l'astre visé et sa fiche s'ouvre
  elApp.voir.addEventListener("click", function () {
    const c = pointage && pointage.commande;
    if (c && c.coordonnees) { // 8.4 : un point du ciel
      montrerPoint(c.coordonnees.ra, c.coordonnees.dec);
      const cible = c.cible;
      if (cible) viser(cible.azimut, cible.elevation, false);
      return;
    }
    const o = c && objets.find(function (obj) { return obj.id === c.objet.id; });
    if (o) allerVers(o);
  });
  elApp.arreter.addEventListener("click", function () {
    if (!envoiEnCours) envoyer(carte.dataset.urlArret, null);
  });

  // --- Bouton « Pointer » de la fiche --------------------------------------------

  function cookie(nom) {
    const trouve = document.cookie.split("; ").find(function (c) { return c.startsWith(nom + "="); });
    return trouve ? decodeURIComponent(trouve.split("=")[1]) : "";
  }

  // Les requêtes POST doivent présenter le jeton CSRF (cookie « csrftoken », déposé par la page)
  function envoyer(url, corps) {
    envoiEnCours = true;
    majBoutonPointer();
    majPanneauAppareil();
    fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRFToken": cookie("csrftoken") },
      body: corps ? JSON.stringify(corps) : undefined,
    })
      .then(function (reponse) {
        return reponse.json().catch(function () { return {}; }).then(function (donnees) {
          if (reponse.status === 403 && donnees.code_requis) {
            const erreur = new Error(donnees.erreur);
            erreur.codeRequis = true;
            erreur.pilotage = donnees.pilotage;
            throw erreur;
          }
          if (reponse.status === 403) throw new Error("Session expirée : recharge la page.");
          if (!reponse.ok) throw new Error(donnees.erreur || "Erreur " + reponse.status);
          return donnees;
        });
      })
      .then(recevoirPointage)
      .catch(function (erreur) {
        if (erreur.codeRequis) {
          if (pointage && erreur.pilotage) pointage.pilotage = erreur.pilotage;
          demanderCode({ url: url, corps: corps }); // l'action sera relancée après le code
          return;
        }
        messageErreur = erreur instanceof TypeError ? "Serveur injoignable." : erreur.message;
        finMessageErreur = Date.now() + 5000;
      })
      .finally(function () {
        envoiEnCours = false;
        majBoutonPointer();
        majPanneauAppareil();
        majPanneauPoint();
        afficherVisite();
      });
  }

  elPointer.addEventListener("click", function () {
    if (selection === null || envoiEnCours) return;
    const c = pointage && pointage.commande;
    if (c && c.objet.id === selection) {
      envoyer(carte.dataset.urlArret, null);
    } else {
      envoyer(carte.dataset.urlCommande, { objet_id: selection });
    }
  });

  function majBoutonPointer() {
    if (selection === null) return;
    const a = pointage && pointage.appareil;
    const c = pointage && pointage.commande;
    const surSelection = Boolean(c && c.objet.id === selection);

    elPointer.textContent = surSelection ? "Arrêter le pointage" : c ? "Pointer celui-ci à la place" : "Pointer";
    elPointer.classList.toggle("arreter", surSelection);
    elPointer.disabled = !a || envoiEnCours; // sans appareil enregistré, rien à commander
    // Partie 14 : jamais vers le Soleil (le serveur refuse aussi, et tout point trop proche de lui)
    const choisi = objets.find(function (o) { return o.id === selection; });
    if (choisi && choisi.categorie === "soleil" && !surSelection) {
      elPointer.textContent = "Pointage interdit (Soleil)";
      elPointer.disabled = true;
    }

    const phrases = [];
    if (Date.now() < finMessageErreur) {
      phrases.push(messageErreur);
    } else if (injoignable) {
      phrases.push("Serveur injoignable.");
    } else if (!a) {
      phrases.push("Aucun appareil enregistré (à créer dans l'administration).");
    } else if (surSelection) {
      let phrase = "Le bras suit cet objet";
      if (!a.connecte) phrase += " dès que l'appareil est en ligne";
      else if (pointage.ecart_deg !== null) phrase += " (écart " + fmtNombre.format(pointage.ecart_deg) + "°)";
      phrases.push(phrase + ".");
    } else if (c) {
      phrases.push("Le bras pointe actuellement : " + c.objet.nom + ".");
    } else {
      phrases.push(a.connecte ? "Appareil connecté." : "Appareil hors ligne : la commande l'attendra.");
    }
    if (a && a.connecte) {
      phrases.push(NOMS_MODES[a.mode] + (a.batterie !== null ? " · " + a.batterie + " %" : "") + ".");
    }
    const pos = positionActuelle();
    if (pos && pos.elevation <= 0) phrases.push("Sous l'horizon : le bras pointera à travers la Terre.");
    if (!enDirect()) phrases.push("Le bras suit le ciel en temps réel, pas l'heure affichée.");
    const p = pointage && pointage.pilotage;
    if (a && p && !p.autorise) phrases.push("Le code de pilotage sera demandé.");
    elNoteAppareil.textContent = phrases.join(" ");
  }

  // --- Dessin sur la carte --------------------------------------------------------

  // Petit viseur au centre de la vue : là où l'on regarde (le centre du disque, toujours)
  function dessinerViseur(ctx) {
    const pt = Celestial.mapProjection(centreVue());
    ctx.save();
    ctx.strokeStyle = "rgba(255, 255, 255, 0.75)";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.arc(pt[0], pt[1], 5, 0, 2 * Math.PI);
    [[1, 0], [-1, 0], [0, 1], [0, -1]].forEach(function (d) {
      ctx.moveTo(pt[0] + d[0] * 9, pt[1] + d[1] * 9);
      ctx.lineTo(pt[0] + d[0] * 14, pt[1] + d[1] * 14);
    });
    ctx.stroke();
    ctx.restore();
  }

  // Réticule à l'endroit où pointe le bras, et trait pointillé vers sa cible.
  // Seulement en direct : le bras suit le ciel réel, pas l'heure virtuelle.
  function dessinerAppareil(ctx) {
    if (!bras || !enDirect() || !Celestial.clip([bras.ra, bras.dec])) return;
    const pt = Celestial.mapProjection([bras.ra, bras.dec]);

    const c = pointage && pointage.commande;
    const cible = c && objets.find(function (o) { return o.id === c.objet.id; });
    ctx.save();
    ctx.strokeStyle = COULEUR_BRAS;
    ctx.lineWidth = 2;

    if (cible && Celestial.clip([cible.ra, cible.dec])) {
      const t = Celestial.mapProjection([cible.ra, cible.dec]);
      if (Math.hypot(t[0] - pt[0], t[1] - pt[1]) > 22) {
        ctx.save();
        ctx.globalAlpha = 0.6;
        ctx.lineWidth = 1.5;
        ctx.setLineDash([4, 5]);
        ctx.beginPath();
        ctx.moveTo(pt[0], pt[1]);
        ctx.lineTo(t[0], t[1]);
        ctx.stroke();
        ctx.restore();
      }
    }

    // Cercle et quatre repères, comme un viseur
    ctx.beginPath();
    ctx.arc(pt[0], pt[1], 11, 0, 2 * Math.PI);
    ctx.stroke();
    ctx.beginPath();
    [[1, 0], [-1, 0], [0, 1], [0, -1]].forEach(function (d) {
      ctx.moveTo(pt[0] + d[0] * 15, pt[1] + d[1] * 15);
      ctx.lineTo(pt[0] + d[0] * 21, pt[1] + d[1] * 21);
    });
    ctx.stroke();
    ctx.restore();
  }

  // ===========================================================================
  // 7. La carte elle-même
  // ===========================================================================

  // ---------------------------------------------------------------------------
  // La vue « fenêtre » : on regarde une direction du ciel, définie par son azimut
  // (0 = nord, sens horaire) et sa hauteur au-dessus de l'horizon. Le ciel tourne,
  // mais la direction reste fixe par rapport à l'horizon, comme quand on regarde par la fenêtre.
  // ---------------------------------------------------------------------------

  // Le regard est au centre de la sphère céleste : il peut tourner dans toutes les directions
  // et zoomer. zoom = 1 : l'échelle de base (voir echelleVue).
  const vue = { azimut: 180, hauteur: 0, zoom: 1 }; // vers le sud, face à l'horizon
  const SENSIBILITE_VUE = 0.25; // degrés de vue par pixel glissé, à zoom 1
  const ZOOM_MINI = 0.7;
  const ZOOM_MAXI = 8;

  // Fixe la direction regardée. L'azimut tourne sans limite ; la hauteur s'arrête juste avant
  // le zénith et le nadir (au-delà, l'image se retournerait et l'horizon ne serait plus en bas).
  const HAUTEUR_LIMITE = 89.5;
  function fixerDirection(azimut, hauteur) {
    vue.azimut = ((azimut % 360) + 360) % 360;
    vue.hauteur = Math.max(-HAUTEUR_LIMITE, Math.min(HAUTEUR_LIMITE, hauteur));
  }

  // Temps sidéral local (degrés) : relie l'heure à la position du ciel
  function tempsSideralLocal(ms) {
    const jours = ms / 86400000 + 2440587.5 - 2451545.0; // jours depuis J2000
    const tempsSideralGreenwich = 280.46061837 + 360.98564736629 * jours;
    return (((tempsSideralGreenwich + lieu.longitude) % 360) + 360) % 360;
  }

  // Direction (azimut, hauteur) -> (ascension droite, déclinaison), en degrés, pour l'instant ms.
  // Même calcul que ciel/astro.py (Skyfield), à 0,4° près : la différence vient de la précession
  // depuis J2000, et elle est la même pour tous les objets, donc la vue reste cohérente avec eux.
  function equatorialDepuis(azimut, hauteur, ms) {
    const rad = Math.PI / 180;
    const A = azimut * rad;
    const h = hauteur * rad;
    const phi = lieu.latitude * rad;
    const sinDec = Math.sin(phi) * Math.sin(h) + Math.cos(phi) * Math.cos(h) * Math.cos(A);
    const dec = Math.asin(Math.max(-1, Math.min(1, sinDec)));
    const angleHoraire = Math.atan2(
      -Math.sin(A) * Math.cos(h),
      Math.cos(phi) * Math.sin(h) - Math.sin(phi) * Math.cos(h) * Math.cos(A)
    );
    const ra = (tempsSideralLocal(ms) - angleHoraire / rad + 720) % 360;
    return [ra, dec / rad];
  }

  function centreVue() {
    return equatorialDepuis(vue.azimut, vue.hauteur, horloge.virtuel);
  }

  // Angle parallactique (degrés) : l'angle entre la direction du pôle céleste et celle du zénith,
  // vu depuis un point du ciel. La bibliothèque met toujours le pôle en haut de l'écran ; on tourne
  // l'image de cet angle pour mettre le zénith en haut : l'horizon reste droit dans toutes les
  // directions. Signe vérifié dans le navigateur (pente de l'horizon mesurée à 0° sur 8 directions).
  function angleParallactique(ra, dec, ms) {
    const rad = Math.PI / 180;
    const H = (tempsSideralLocal(ms) - ra) * rad; // angle horaire
    const d = dec * rad;
    const phi = lieu.latitude * rad;
    return Math.atan2(Math.sin(H), Math.tan(phi) * Math.cos(d) - Math.sin(d) * Math.cos(H)) / rad;
  }

  // Centre de la vue pour la bibliothèque : [ascension droite, déclinaison, rotation de l'image]
  function centreEtRoulis() {
    const c = centreVue();
    return [c[0], c[1], angleParallactique(c[0], c[1], horloge.virtuel)];
  }

  function appliquerVue() {
    Celestial.rotate({ center: centreEtRoulis() });
  }

  // Glisser le doigt (ou la souris) sur le ciel fait tourner la vue. Un simple toucher
  // ne bouge rien (c'est la sélection). Le redessin est regroupé par image (requestAnimationFrame).
  let glisse = false;
  let derniere = null;
  let redessinPrevu = false;
  document.addEventListener("pointermove", function (e) {
    if (!depart || !e.isPrimary || pointeurs.size > 1) return; // deux doigts : pincement, pas glissement
    if (!glisse) {
      if (Math.hypot(e.clientX - depart.x, e.clientY - depart.y) <= 6) return;
      glisse = true;
      derniere = { x: depart.x, y: depart.y };
    }
    const sensibilite = SENSIBILITE_VUE / vue.zoom; // à fort zoom, un glissement tourne moins
    // Axe vertical inversé (demandé) : glisser vers le bas fait regarder vers le haut, et inversement.
    fixerDirection(vue.azimut - (e.clientX - derniere.x) * sensibilite, vue.hauteur + (e.clientY - derniere.y) * sensibilite);
    derniere = { x: e.clientX, y: e.clientY };
    if (!redessinPrevu) {
      redessinPrevu = true;
      requestAnimationFrame(function () {
        redessinPrevu = false;
        appliquerVue();
        Celestial.redraw();
      });
    }
  });
  document.addEventListener("pointerup", function () {
    glisse = false;
  });

  // --- Zoom : deux doigts (pincement), molette de souris, touches + et - -----------
  const pointeurs = new Map(); // doigts posés sur l'écran : pointerId -> position
  let pincement = null; // { distance, zoom } au début du pincement

  function distancePointeurs() {
    const [a, b] = Array.from(pointeurs.values());
    return Math.hypot(a.x - b.x, a.y - b.y);
  }

  document.addEventListener("pointerdown", function (e) {
    pointeurs.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pointeurs.size === 2) {
      depart = null; // le premier doigt ne doit plus faire tourner la vue
      glisse = false;
      pincement = { distance: distancePointeurs(), zoom: vue.zoom };
    }
  });
  document.addEventListener("pointermove", function (e) {
    if (!pointeurs.has(e.pointerId)) return;
    pointeurs.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pointeurs.size === 2 && pincement) {
      changerZoom(pincement.zoom * distancePointeurs() / pincement.distance);
    }
  });
  function finPointeur(e) {
    pointeurs.delete(e.pointerId);
    if (pointeurs.size < 2) pincement = null;
  }
  document.addEventListener("pointerup", finPointeur);
  document.addEventListener("pointercancel", finPointeur);

  carte.addEventListener("wheel", function (e) {
    e.preventDefault(); // la molette zoome, elle ne fait pas défiler la page
    changerZoom(vue.zoom * Math.exp(-e.deltaY * 0.0015));
  }, { passive: false });

  document.getElementById("zoom-plus").addEventListener("click", function () {
    changerZoom(vue.zoom * 1.25);
  });
  document.getElementById("zoom-moins").addEventListener("click", function () {
    changerZoom(vue.zoom / 1.25);
  });
  // Safari (iPhone) zoome la page entière sur un pincement : on le laisse à la carte
  document.addEventListener("gesturestart", function (e) { e.preventDefault(); }, { passive: false });

  document.addEventListener("keydown", function (e) {
    if (e.key === "+" || e.key === "=") changerZoom(vue.zoom * 1.25);
    if (e.key === "-") changerZoom(vue.zoom / 1.25);
  });

  // Le zoom passe par la bibliothèque : Celestial.zoomBy(facteur) multiplie l'échelle et redessine
  // (rapide, et l'échelle survit aux rechargements). Le réglage « zoomlevel » de la configuration,
  // lui, n'est lu qu'au premier affichage : le changer ensuite ne faisait rien.
  let zoomPrevu = false;
  function changerZoom(z) {
    const nouveau = Math.max(ZOOM_MINI, Math.min(ZOOM_MAXI, z));
    if (nouveau === vue.zoom) return;
    vue.zoom = nouveau;
    majBoussole();
    if (zoomPrevu) return; // un seul redessin par image, même si le pincement envoie plus d'événements
    zoomPrevu = true;
    requestAnimationFrame(function () {
      zoomPrevu = false;
      Celestial.zoomBy(vue.zoom / Celestial.zoomBy()); // zoomBy() sans argument = zoom actuel
      placerCanevas();
    });
  }

  // Le sol : l'hémisphère centré sur le nadir (tout ce qui est sous l'horizon). La bibliothèque
  // dessine son propre horizon dans un calque SVG caché sous le canevas, donc on le dessine nous-mêmes.
  // d3 trace le cercle sur la sphère et le découpe à la limite de l'hémisphère visible : le tracé
  // reste juste dans toutes les directions, y compris quand l'horizon passe par le centre de l'écran.
  function dessinerSol(ctx) {
    // 89,9° et pas 90° : un cercle de 90° coupe la sphère en deux moitiés égales, et d3 ne sait
    // pas laquelle remplir. 0,1° d'écart, c'est moins d'un pixel.
    const cercle = d3.geo.circle().origin(equatorialDepuis(0, -90, horloge.virtuel)).angle(89.9)();
    const chemin = d3.geo.path().projection(Celestial.mapProjection).context(ctx);

    ctx.save();
    ctx.beginPath();
    chemin(cercle);
    ctx.fillStyle = "rgba(40, 50, 74, 0.62)"; // translucide : les astres sous l'horizon restent visibles
    ctx.fill();

    // Ligne d'horizon (le bord du cercle seulement, pas la limite de l'écran)
    ctx.beginPath();
    chemin({ type: "LineString", coordinates: cercle.coordinates[0] });
    ctx.lineWidth = 1.5;
    ctx.strokeStyle = "#56658a";
    ctx.stroke();
    ctx.restore();
  }

  // Points cardinaux sur l'horizon (N, E, S, O), là où l'horizon coupe le cercle de l'azimut
  const POINTS_CARDINAUX_HORIZON = [["N", 0], ["E", 90], ["S", 180], ["O", 270]];
  function dessinerHorizon(ctx) {
    ctx.save();
    ctx.font = "600 15px Helvetica, Arial, sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.lineJoin = "round";
    ctx.lineWidth = 3;
    ctx.strokeStyle = "rgba(5, 7, 13, 0.9)";
    ctx.fillStyle = "#d5dcec";
    POINTS_CARDINAUX_HORIZON.forEach(function (point) {
      const position = equatorialDepuis(point[1], 0, horloge.virtuel);
      if (!Celestial.clip(position)) return;
      const pt = Celestial.mapProjection(position);
      ctx.strokeText(point[0], pt[0], pt[1]);
      ctx.fillText(point[0], pt[0], pt[1]);
    });
    ctx.restore();
  }

  // La bibliothèque règle l'échelle sur la largeur du canevas (environ 0,00447 px par degré et
  // par pixel de canevas, mesuré sur d3-celestial 0,7.35). On fixe plutôt l'échelle angulaire
  // (pixels par degré) : le même champ de vision sur téléphone et sur bureau.
  // Sur téléphone, le champ est plus serré (environ 70° de large) : les noms se lisent.
  const PIXELS_PAR_DEGRE_VUE_BUREAU = 3.5;
  const PIXELS_PAR_DEGRE_VUE_TELEPHONE = 5.5;
  function echelleVue() {
    return GRAND_ECRAN.matches ? PIXELS_PAR_DEGRE_VUE_BUREAU : PIXELS_PAR_DEGRE_VUE_TELEPHONE;
  }
  const ECHELLE_BIBLIOTHEQUE = 0.00447;
  function configCarte(largeur) {
    return {
    zoomlevel: echelleVue() / (ECHELLE_BIBLIOTHEQUE * largeur), // échelle de base ; le zoom passe par zoomBy
    // Sans cela, la bibliothèque grossit les étoiles et affiche de plus en plus de noms (souvent
    // obscurs, qui se chevauchent) à mesure qu'on zoome.
    adaptable: false,
    container: "carte",
    datapath: carte.dataset.datapath,
    width: largeur,
    projection: "stereographic", // vue « fenêtre » centrée sur la direction regardée
    interactive: false, // on fait tourner la vue nous-mêmes (voir glisser, plus haut)
    controls: false,
    disableAnimations: true, // sinon chaque mise à jour du temps est « animée » et saccade

    // Ciel vu du lieu d'observation, centré sur le zénith
    location: true,
    geopos: POSITION,
    follow: "center",
    center: centreEtRoulis(),
    settimezone: false, // sinon la bibliothèque interroge un service externe

    // Formulaire interne : présent mais caché (voir carte.css)
    form: true,

    stars: {
      limit: filtres.magnitude, // 8.4 (F36) : 4, 5 ou 6 selon le ciel de l'observateur
      size: 10, // disques plus gros : lisibles sur un petit écran
      colors: true,
      designation: false,
      propername: calques.etiquettesEtoiles,
      propernameType: "fr",
      propernameLimit: 2.2,
      propernameStyle: {
        fill: "#e3e9f6",
        font: "13px Helvetica, Arial, sans-serif",
        align: "left",
        baseline: "top",
      },
    },
    dsos: { show: false },
    planets: { show: false }, // on dessine les nôtres (calculées par Skyfield)
    constellations: {
      names: false, // nos propres noms, en majuscules espacées (voir dessinerConstellations)
      namesType: "fr",
      lines: calques.constellations,
      nameStyle: {
        fill: "#a3b2d6",
        align: "center",
        baseline: "middle",
        font: [
          "13px Helvetica, Arial, sans-serif",
          "12px Helvetica, Arial, sans-serif",
          "12px Helvetica, Arial, sans-serif",
        ],
      },
      lineStyle: { stroke: "#8593b8", width: 1, opacity: 0.45 }, // discrètes : les étoiles d'abord
    },
    mw: { show: calques.voieLactee, style: { fill: "#aab4d4", opacity: 0.06 } },
    lines: {
      graticule: { show: false },
      equatorial: { show: false },
      ecliptic: { show: false },
    },
    background: { fill: "#05070d", opacity: 1, stroke: "#05070d", width: 0 },
    horizon: { show: false }, // dessiné par nous-mêmes (voir dessinerSol)
    daylight: { show: false },
    };
  }

  // Dessine la carte à la taille de la zone, puis retire le gestionnaire de redimensionnement
  // que la bibliothèque installe elle-même (on gère le redimensionnement nous-mêmes).
  function afficherCarte() {
    Celestial.display(configCarte(placer()));
    d3.select(window).on("resize", null);
    placerCanevas();
  }

  afficherCarte();

  // ===========================================================================
  // Partie 6.4 : partager la position du navigateur
  // (secours tant que le robot n'a pas encore de GPS à lui, ou qu'aucun robot n'est connecté)
  // ===========================================================================

  const elBtnPosition = document.getElementById("btn-position");
  const elMessageEclair = document.getElementById("message-eclair");
  let messageEclairMinuteur = null;

  function messageEclair(texte, duree_ms) {
    clearTimeout(messageEclairMinuteur);
    elMessageEclair.textContent = texte;
    elMessageEclair.hidden = false;
    messageEclairMinuteur = setTimeout(function () { elMessageEclair.hidden = true; }, duree_ms || 5000);
  }

  elBtnPosition.addEventListener("click", function () {
    if (elBtnPosition.getAttribute("aria-pressed") === "true") {
      // Déjà partagée : un deuxième clic la retire
      posterJson(carte.dataset.urlLieu, { partager: false })
        .then(function (r) {
          if (r.statut !== 200) { messageEclair("Serveur injoignable."); return; }
          messageEclair("Position du navigateur retirée.");
          window.location.reload(); // reprend le lieu par défaut (ou le GPS du robot)
        })
        .catch(function () { messageEclair("Serveur injoignable."); });
      return;
    }
    if (!("geolocation" in navigator)) {
      messageEclair("La géolocalisation n'est pas proposée par ce navigateur.");
      return;
    }
    messageEclair("Localisation en cours…", 15000);
    navigator.geolocation.getCurrentPosition(
      function (position) {
        const corps = {
          latitude: position.coords.latitude,
          longitude: position.coords.longitude,
          altitude_m: position.coords.altitude || 0,
        };
        posterJson(carte.dataset.urlLieu, corps)
          .then(function (r) {
            if (r.statut !== 200) {
              messageEclair((r.donnees && r.donnees.erreur) || "Position refusée par le serveur.");
              return;
            }
            messageEclair("Position partagée : la carte se recharge…");
            window.location.reload(); // tout le calcul (vue, objets, fuseau) repart du bon lieu
          })
          .catch(function () { messageEclair("Serveur injoignable."); });
      },
      function (erreur) {
        const messages = {
          1: "Permission refusée : autorise la localisation dans les réglages du navigateur.",
          2: "Position indisponible.",
          3: "Délai dépassé.",
        };
        messageEclair(messages[erreur.code] || "Impossible d'obtenir la position.");
      },
      { enableHighAccuracy: true, timeout: 10000, maximumAge: 0 }
    );
  });

  // ===========================================================================
  // 8. Changement de taille / rotation de l'écran
  // ===========================================================================

  // Pas de rechargement de la page : on redessine la carte à la nouvelle taille,
  // après une courte pause (le temps que la rotation de l'écran se termine).
  let tailleAffichee = taille();
  let minuteur = null;
  window.addEventListener("resize", function () {
    clearTimeout(minuteur);
    minuteur = setTimeout(redessiner, 200);
  });

  function redessiner() {
    const t = placer();
    if (t === tailleAffichee) {
      placerCanevas();
      return;
    }
    tailleAffichee = t;
    Celestial.resize({ width: t }); // nouvelle taille du canvas
    Celestial.reload(configCarte(t)); // puis redessin complet, sans recharger la page
    d3.select(window).on("resize", null);
    placerCanevas();
  }
})();
