"""Partie 7 : ce qu'on peut voir à l'œil nu, ce soir et les jours suivants.

Tout est calculé pour un lieu et une fenêtre de temps (Skyfield, éphéméride DE421) :
- « ce soir » : la nuit (Soleil à plus de 6° sous l'horizon) et les astres de la base qu'on y voit ;
- phases de la Lune ;
- rapprochements (« conjonctions ») entre la Lune et les planètes, ou entre deux planètes,
  seulement s'ils sont observables (de nuit, les deux astres au-dessus de 5°) ;
- essaims d'étoiles filantes (tableau de l'IMO, ci-dessous) ;
- éclipses de Lune partielles ou totales, si la Lune est levée ;
- passages visibles des satellites de la base (ISS), calculés en Partie 6.3.

Chaque événement : {type, titre, instant, objet_id, direction{azimut, elevation}} plus des champs
propres à son type. `instant` est le meilleur moment pour regarder ; `direction` où regarder.
"""

import math

import numpy as np
from skyfield import almanac, eclipselib
from skyfield.searchlib import find_maxima
from skyfield.api import Star, wgs84
from skyfield.framelib import ecliptic_J2000_frame

from . import astro, satellites

SOLEIL_NUIT = -6.0  # degrés : en dessous, le ciel est assez sombre pour les planètes et l'ISS
SOLEIL_NUIT_NOIRE = -12.0  # pour les étoiles filantes
HAUTEUR_MINI = 10.0  # « ce soir » : un astre plus bas se perd dans les obstacles et la brume
HAUTEUR_MINI_CONJONCTION = 5.0
ECART_LUNE_PLANETE = 5.0  # degrés : rapprochement remarquable
ECART_PLANETES = 3.0
PAS_MIN = 10  # minutes, pour « ce soir », les essaims et les rapprochements affinés
DUREE_PASSAGES_MAX_J = 7  # au-delà de 7 jours de l'époque du TLE, un passage annoncé serait faux
HAUTEUR_MINI_PASSAGE = 20.0  # dans la liste des événements : les beaux passages seulement

# Les « principaux » : mis en avant dans l'appli (badge « à ne pas manquer »)
IMPORTANTS = {"eclipse_lune", "eclipse_soleil", "opposition"}

NOMS_PHASES = ["Nouvelle Lune", "Premier quartier", "Pleine Lune", "Dernier quartier"]
NOMS_ECLIPSES = {1: "partielle", 2: "totale"}  # 0 = par la pénombre : à peine visible, ignorée

# Essaims d'étoiles filantes : tableau 5 du calendrier 2026 de l'IMO (International Meteor
# Organization, https://www.imo.net/files/meteor-shower/cal2026.pdf), essaims dont le taux
# horaire zénithal (ZHR) atteint 10. Le maximum est donné en longitude du Soleil (J2000) : il
# revient chaque année au même point de l'orbite, la date se calcule pour n'importe quelle année.
# (nom, longitude du Soleil au maximum, radiant : ascension droite et déclinaison, ZHR)
ESSAIMS = [
    ("Quadrantides", 283.15, 230.0, 49.0, 80),
    ("Lyrides", 32.32, 271.0, 34.0, 18),
    ("Êta Aquarides", 45.5, 338.0, -1.0, 50),
    ("Delta Aquarides du Sud", 128.0, 340.0, -16.0, 25),
    ("Perséides", 140.0, 48.0, 58.0, 100),
    ("Orionides", 208.0, 95.0, 16.0, 20),
    ("Léonides", 235.27, 152.0, 22.0, 15),
    ("Géminides", 262.2, 112.0, 33.0, 150),
    ("Ursides", 270.7, 217.0, 76.0, 10),
]


def _eph():
    return astro._ephemerides()


def _ts():
    return astro._timescale()


def _instants(debut, fin, pas_min):
    ts = _ts()
    n = int((fin.tt - debut.tt) * 1440 / pas_min) + 1
    return ts.tt_jd(debut.tt + np.arange(n) * pas_min / 1440.0)


def _hauteur_soleil(lieu, instants):
    terre_lieu = _eph()["earth"] + lieu
    return terre_lieu.at(instants).observe(_eph()["sun"]).apparent().altaz()[0].degrees


def _direction(identifiant, lat, lon, alt, instant):
    elevation, azimut = astro.altaz(identifiant, lat, lon, alt, instant)
    return {"azimut": round(azimut, 1), "elevation": round(elevation, 1)}


def _hauteurs(identifiant, lat, lon, alt, instants):
    return astro._vu_du_lieu(identifiant, lat, lon, alt, instants).altaz()[0].degrees


# --- Ce soir -----------------------------------------------------------------------------------

def ce_soir(objets, lat, lon, alt, debut):
    """La nuit qui vient (ou la nuit en cours) et les astres qu'on y voit au-dessus de 10°.
    objets : [(id, nom, identifiant)]. Renvoie {debut_nuit, fin_nuit, astres[]} ; debut_nuit est
    None s'il ne fait pas nuit dans les 24 h (été au-delà du cercle polaire)."""
    lieu = wgs84.latlon(lat, lon, elevation_m=alt)
    instants = _instants(debut, _ts().tt_jd(debut.tt + 1.0), PAS_MIN)
    nuit = _hauteur_soleil(lieu, instants) < SOLEIL_NUIT
    if not nuit.any():
        return {"debut_nuit": None, "fin_nuit": None, "astres": []}
    i0 = int(np.argmax(nuit))  # premier instant de nuit
    i1 = i0
    while i1 + 1 < len(nuit) and nuit[i1 + 1]:
        i1 += 1
    fenetre = instants[i0:i1 + 1]
    astres = []
    for objet_id, nom, ident in objets:
        try:
            h = _hauteurs(ident, lat, lon, alt, fenetre)
        except (KeyError, ValueError):
            continue
        visibles = np.nonzero(h >= HAUTEUR_MINI)[0]
        if len(visibles) == 0:
            continue
        meilleur = int(np.argmax(h))
        astres.append({
            "objet_id": objet_id,
            "nom": nom,
            "de": fenetre[int(visibles[0])].utc_iso(),
            "a": fenetre[int(visibles[-1])].utc_iso(),
            "hauteur_max": round(float(h[meilleur]), 1),
            "instant": fenetre[meilleur].utc_iso(),  # le meilleur moment : au plus haut
            "direction": _direction(ident, lat, lon, alt, fenetre[meilleur]),
        })
    astres.sort(key=lambda a: a["de"])
    return {"debut_nuit": fenetre[0].utc_iso(), "fin_nuit": fenetre[-1].utc_iso(), "astres": astres}


# --- Phases de la Lune -------------------------------------------------------------------------

def phases_lune(lat, lon, alt, debut, fin, lune_id=None):
    temps, phases = almanac.find_discrete(debut, fin, almanac.moon_phases(_eph()))
    return [
        {
            "type": "phase_lune",
            "titre": NOMS_PHASES[int(p)],
            "phase": int(p),  # 0 nouvelle, 1 premier quartier, 2 pleine, 3 dernier quartier
            "instant": t.utc_iso(),
            "objet_id": lune_id,
            "direction": _direction("moon", lat, lon, alt, t),
        }
        for t, p in zip(temps, phases)
    ]


# --- Rapprochements (conjonctions) -------------------------------------------------------------

def conjonctions(astres, lat, lon, alt, debut, fin):
    """astres : [(id, nom, identifiant, categorie)] (Lune et planètes). Un événement par
    rapprochement observable : au meilleur moment de la nuit la plus proche du plus petit écart."""
    ts = _ts()
    lieu = wgs84.latlon(lat, lon, elevation_m=alt)
    # Une heure de pas suffit pour trouver les minimums (la Lune parcourt 0,5° par heure)
    instants = _instants(ts.tt_jd(debut.tt - 0.5), ts.tt_jd(fin.tt + 0.5), 60)
    positions = {}
    for a in astres:
        try:
            positions[a[0]] = astro._vu_du_lieu(a[2], lat, lon, alt, instants)
        except (KeyError, ValueError):
            continue
    presents = [a for a in astres if a[0] in positions]
    evenements = []
    for i, a in enumerate(presents):
        for b in presents[i + 1:]:
            seuil = ECART_LUNE_PLANETE if "lune" in (a[3], b[3]) else ECART_PLANETES
            ecart = positions[a[0]].separation_from(positions[b[0]]).degrees
            for k in range(1, len(ecart) - 1):
                if not (ecart[k] <= ecart[k - 1] and ecart[k] < ecart[k + 1] and ecart[k] <= seuil):
                    continue
                proche = instants[k]
                if not debut.tt - 0.5 <= proche.tt <= fin.tt + 0.5:
                    continue
                ev = _meilleur_moment_conjonction(a, b, lat, lon, alt, lieu, proche)
                if ev and debut.tt <= ts.tt_jd(_jd(ev["instant"])).tt <= fin.tt:
                    evenements.append(ev)
    return evenements


def _jd(texte_iso):
    from datetime import datetime
    return _ts().from_datetime(datetime.fromisoformat(texte_iso.replace("Z", "+00:00"))).tt


def _meilleur_moment_conjonction(a, b, lat, lon, alt, lieu, proche):
    """Dans les 12 h autour du plus petit écart : le moment de nuit où les deux astres sont le
    plus haut (le plus bas des deux, au moins 5°). None si ce n'est pas observable."""
    ts = _ts()
    fenetre = _instants(ts.tt_jd(proche.tt - 0.5), ts.tt_jd(proche.tt + 0.5), PAS_MIN)
    pa = astro._vu_du_lieu(a[2], lat, lon, alt, fenetre)
    pb = astro._vu_du_lieu(b[2], lat, lon, alt, fenetre)
    plus_bas = np.minimum(pa.altaz()[0].degrees, pb.altaz()[0].degrees)
    possible = (_hauteur_soleil(lieu, fenetre) < SOLEIL_NUIT) & (plus_bas >= HAUTEUR_MINI_CONJONCTION)
    if not possible.any():
        return None
    k = int(np.argmax(np.where(possible, plus_bas, -999)))
    t = fenetre[k]
    ecart = float(
        astro._vu_du_lieu(a[2], lat, lon, alt, t).separation_from(astro._vu_du_lieu(b[2], lat, lon, alt, t)).degrees
    )
    da, db = _direction(a[2], lat, lon, alt, t), _direction(b[2], lat, lon, alt, t)
    # La Lune en premier dans le titre (« La Lune et Jupiter »), sinon l'ordre de la base
    premier, second = (b, a) if b[3] == "lune" else (a, b)
    return {
        "type": "conjonction",
        "titre": f"{premier[1]} et {second[1]} à {ecart:.1f}°".replace(".", ","),
        "instant": t.utc_iso(),
        "objet_id": premier[0],
        "objets": [premier[0], second[0]],
        "ecart": round(ecart, 1),
        # Regarder entre les deux (moyenne des directions, azimut par le plus court chemin)
        "direction": {
            "azimut": round((da["azimut"] + ((db["azimut"] - da["azimut"] + 540) % 360 - 180) / 2) % 360, 1),
            "elevation": round((da["elevation"] + db["elevation"]) / 2, 1),
        },
    }


# --- Essaims d'étoiles filantes ----------------------------------------------------------------

def _longitude_soleil(t):
    """Longitude écliptique (J2000) du Soleil vu de la Terre, en degrés : la référence de l'IMO."""
    lat_, lon_, _ = _eph()["earth"].at(t).observe(_eph()["sun"]).frame_latlon(ecliptic_J2000_frame)
    return lon_.degrees


def maximum_essaim(longitude, debut, fin):
    """Instants où la longitude du Soleil atteint `longitude` entre debut et fin."""
    def depasse(t):
        return ((_longitude_soleil(t) - longitude) % 360) < 180
    depasse.step_days = 5
    temps, valeurs = almanac.find_discrete(debut, fin, depasse)
    return [t for t, v in zip(temps, valeurs) if v]


def essaims(lat, lon, alt, debut, fin):
    ts = _ts()
    lieu = wgs84.latlon(lat, lon, elevation_m=alt)
    terre_lieu = _eph()["earth"] + lieu
    evenements = []
    for nom, longitude, ra, dec, zhr in ESSAIMS:
        # On cherche aussi un peu avant : la nuit du maximum peut commencer avant la fenêtre
        for maximum in maximum_essaim(longitude, ts.tt_jd(debut.tt - 1), ts.tt_jd(fin.tt + 1)):
            radiant = Star(ra_hours=ra / 15.0, dec_degrees=dec)
            fenetre = _instants(ts.tt_jd(maximum.tt - 0.5), ts.tt_jd(maximum.tt + 0.5), PAS_MIN)
            h_radiant = terre_lieu.at(fenetre).observe(radiant).apparent().altaz()[0].degrees
            noir = _hauteur_soleil(lieu, fenetre) < SOLEIL_NUIT_NOIRE
            if not (noir & (h_radiant > 0)).any():
                continue  # radiant jamais levé de nuit ici (hémisphère opposé)
            k = int(np.argmax(np.where(noir, h_radiant, -999)))
            t = fenetre[k]
            if not debut.tt <= t.tt <= fin.tt:
                continue
            lune = terre_lieu.at(t).observe(_eph()["moon"]).apparent()
            eclairement = float(almanac.fraction_illuminated(_eph(), "moon", t))
            azimut = terre_lieu.at(t).observe(radiant).apparent().altaz()[1].degrees
            evenements.append({
                "type": "essaim",
                "titre": nom,
                "instant": t.utc_iso(),  # le radiant au plus haut pendant la nuit noire
                "maximum": maximum.utc_iso(),
                "zhr": zhr,  # nombre par heure dans un ciel parfait, radiant au zénith
                "lune_genante": bool(eclairement > 0.5 and lune.altaz()[0].degrees > 0),
                "objet_id": None,
                "direction": {"azimut": round(float(azimut), 1), "elevation": round(float(h_radiant[k]), 1)},
            })
    return evenements


# --- Éclipses de Lune --------------------------------------------------------------------------

def eclipses_lune(lat, lon, alt, debut, fin, lune_id=None):
    temps, genres, _ = eclipselib.lunar_eclipses(debut, fin, _eph())
    evenements = []
    for t, genre in zip(temps, genres):
        if int(genre) not in NOMS_ECLIPSES:
            continue
        direction = _direction("moon", lat, lon, alt, t)
        if direction["elevation"] <= 0:
            continue  # Lune couchée ici au maximum de l'éclipse
        evenements.append({
            "type": "eclipse_lune",
            "titre": f"Éclipse de Lune {NOMS_ECLIPSES[int(genre)]}",
            "instant": t.utc_iso(),
            "objet_id": lune_id,
            "direction": direction,
        })
    return evenements


# --- Passages visibles des satellites ----------------------------------------------------------

def passages_visibles(satellites_base, lat, lon, alt, debut, fin):
    """satellites_base : [(id, nom, identifiant)]. Seulement les passages visibles à l'œil nu,
    à 20° ou plus, et à moins de 7 jours de l'époque du TLE (au-delà, l'heure annoncée est fausse)."""
    evenements = []
    for objet_id, nom, ident in satellites_base:
        try:
            epoque = _jd(satellites.tle(satellites.numero_de(ident))["epoque"])
            t0 = max(debut.tt, epoque - DUREE_PASSAGES_MAX_J)
            t1 = min(fin.tt, epoque + DUREE_PASSAGES_MAX_J)
            if t1 <= t0:
                continue
            liste = astro.passages(ident, lat, lon, alt, _ts().tt_jd(t0), (t1 - t0) * 24)
        except (KeyError, ValueError):  # dont satellites.TleIndisponible
            continue
        for p in liste:
            if not p["visible"] or p["hauteur_max"] < HAUTEUR_MINI_PASSAGE or _jd(p["culmination"]) < debut.tt:
                continue
            t = _ts().tt_jd(_jd(p["culmination"]))
            evenements.append({
                "type": "passage",
                "titre": f"Passage de {nom}",
                "instant": p["culmination"],
                "lever": p["lever"],
                "coucher": p["coucher"],
                "hauteur_max": p["hauteur_max"],
                "azimut_lever": p["azimut_lever"],
                "azimut_coucher": p["azimut_coucher"],
                "objet_id": objet_id,
                "direction": _direction(ident, lat, lon, alt, t),
            })
    return evenements


# --- Partie 8.2 : éclipses de Soleil, oppositions, élongations, occultations, saisons ----------

RAYON_SOLEIL_KM = 696_000.0
RAYON_LUNE_KM = 1_737.4
PLANETES_EXTERIEURES = [("Mars", "mars barycenter"), ("Jupiter", "jupiter barycenter"), ("Saturne", "saturn barycenter")]
PLANETES_INTERIEURES = [("Mercure", "mercury"), ("Vénus", "venus")]
NOMS_SAISONS = ["Équinoxe de printemps", "Solstice d'été", "Équinoxe d'automne", "Solstice d'hiver"]


def _id_de(objets, identifiant):
    return next((o[0] for o in objets if o[2] == identifiant), None)


def eclipses_soleil(lat, lon, alt, debut, fin):
    """Éclipses de Soleil vues d'ici : à chaque nouvelle Lune, on cherche (pas d'une minute,
    Soleil levé) si les disques de la Lune et du Soleil se recouvrent. `magnitude` : part du
    diamètre du Soleil couverte au maximum (1 = totale). Jamais regarder le Soleil sans
    lunettes d'éclipse : rappelé dans le titre côté appli."""
    ts = _ts()
    temps, phases = almanac.find_discrete(ts.tt_jd(debut.tt - 0.3), ts.tt_jd(fin.tt + 0.3), almanac.moon_phases(_eph()))
    lieu = _eph()["earth"] + wgs84.latlon(lat, lon, elevation_m=alt)
    evenements = []
    for t, phase in zip(temps, phases):
        if phase != 0:
            continue
        fenetre = _instants(ts.tt_jd(t.tt - 0.25), ts.tt_jd(t.tt + 0.25), 1)
        soleil = lieu.at(fenetre).observe(_eph()["sun"]).apparent()
        lune = lieu.at(fenetre).observe(_eph()["moon"]).apparent()
        ecart = soleil.separation_from(lune).radians
        r_s = np.arcsin(RAYON_SOLEIL_KM / soleil.distance().km)
        r_l = np.arcsin(RAYON_LUNE_KM / lune.distance().km)
        hauteur = soleil.altaz()[0].degrees
        couvert = (ecart < r_s + r_l) & (hauteur > 0)
        if not couvert.any():
            continue
        k = int(np.argmin(np.where(couvert, ecart, np.inf)))
        magnitude = float((r_s[k] + r_l[k] - ecart[k]) / (2 * r_s[k]))
        if ecart[k] <= abs(r_l[k] - r_s[k]):
            genre = "totale" if r_l[k] > r_s[k] else "annulaire"
        else:
            genre = "partielle"
        if not debut.tt <= fenetre[k].tt <= fin.tt:
            continue
        indices = np.nonzero(couvert)[0]
        evenements.append({
            "type": "eclipse_soleil",
            "titre": f"Éclipse de Soleil {genre}",
            "instant": fenetre[k].utc_iso(),
            "debut": fenetre[int(indices[0])].utc_iso(),
            "fin": fenetre[int(indices[-1])].utc_iso(),
            "magnitude": round(min(magnitude, 1.0), 2),
            "important": True,
            "objet_id": None,
            "direction": {"azimut": round(float(soleil.altaz()[1].degrees[k]), 1), "elevation": round(float(hauteur[k]), 1)},
        })
    return evenements


def oppositions(objets, lat, lon, alt, debut, fin):
    """Opposition d'une planète extérieure : face au Soleil, au plus près et au plus brillant,
    visible toute la nuit. Le moment donné est minuit environ (au plus haut) la nuit de l'opposition."""
    evenements = []
    for nom, ident in PLANETES_EXTERIEURES:
        temps, valeurs = almanac.find_discrete(debut, fin, almanac.oppositions_conjunctions(_eph(), _eph()[ident]))
        for t, v in zip(temps, valeurs):
            if v != 1:
                continue
            meilleur = ce_soir([(None, nom, ident)], lat, lon, alt, _ts().tt_jd(t.tt - 0.5))["astres"]
            moment = _ts().tt_jd(_jd(meilleur[0]["instant"])) if meilleur else t
            evenements.append({
                "type": "opposition",
                "titre": f"Opposition de {nom}",
                "instant": moment.utc_iso(),
                "opposition": t.utc_iso(),
                "important": True,
                "objet_id": _id_de(objets, ident),
                "direction": _direction(ident, lat, lon, alt, moment),
            })
    return evenements


def elongations(objets, lat, lon, alt, debut, fin):
    """Plus grande élongation de Mercure ou Vénus : au plus loin du Soleil, le meilleur moment
    pour la voir (à l'est du Soleil : le soir ; à l'ouest : le matin)."""
    ts = _ts()
    terre = _eph()["earth"]
    evenements = []
    for nom, ident in PLANETES_INTERIEURES:
        def elongation(t):
            e = terre.at(t)
            return e.observe(_eph()["sun"]).separation_from(e.observe(_eph()[ident])).degrees
        elongation.step_days = 5
        temps, valeurs = find_maxima(debut, fin, elongation)
        for t, angle in zip(temps, valeurs):
            e = terre.at(t)
            lon_soleil = e.observe(_eph()["sun"]).frame_latlon(ecliptic_J2000_frame)[1].degrees
            lon_planete = e.observe(_eph()[ident]).frame_latlon(ecliptic_J2000_frame)[1].degrees
            soir = bool(((lon_planete - lon_soleil) % 360) < 180)  # à l'est du Soleil
            # Meilleur moment : 45 min après le coucher du Soleil (ou avant son lever)
            jour = ts.tt_jd(math.floor(t.tt - 0.5) + 0.5)
            lieu = wgs84.latlon(lat, lon, elevation_m=alt)
            f = almanac.sunrise_sunset(_eph(), lieu)
            tt, vv = almanac.find_discrete(jour, ts.tt_jd(jour.tt + 1.5), f)
            choix = [x for x, v in zip(tt, vv) if bool(v) != soir]  # coucher (v=0) le soir, lever (1) le matin
            moment = ts.tt_jd(choix[0].tt + (0.03125 if soir else -0.03125)) if choix else t
            evenements.append({
                "type": "elongation",
                "titre": f"{nom} au plus loin du Soleil ({round(float(angle))}°, {'le soir' if soir else 'le matin'})",
                "instant": moment.utc_iso(),
                "elongation": round(float(angle), 1),
                "soir": soir,
                "important": False,
                "objet_id": _id_de(objets, ident),
                "direction": _direction(ident, lat, lon, alt, moment),
            })
    return evenements


def occultations(objets, lat, lon, alt, debut, fin):
    """La Lune passe devant une planète ou une étoile de la base, visible d'ici (de nuit, Lune
    levée). On repère les rapprochements à moins de 1,5° (pas d'une heure), puis on affine à la minute."""
    ts = _ts()
    lieu_topo = wgs84.latlon(lat, lon, elevation_m=alt)
    instants = _instants(debut, fin, 60)
    lune_h = astro._vu_du_lieu("moon", lat, lon, alt, instants)
    evenements = []
    for objet_id, nom, ident, categorie in objets:
        if categorie not in ("planete", "etoile") or satellites.numero_de(ident) is not None:
            continue
        try:
            ecart = lune_h.separation_from(astro._vu_du_lieu(ident, lat, lon, alt, instants)).degrees
        except (KeyError, ValueError):
            continue
        proches = np.nonzero(ecart < 1.5)[0]
        dernier = -999
        for k in proches:
            if k - dernier < 12:  # même rapprochement (il dure quelques heures) : déjà examiné
                continue
            dernier = int(k)
            fenetre = _instants(ts.tt_jd(instants[k].tt - 0.15), ts.tt_jd(instants[k].tt + 0.15), 1)
            lune = astro._vu_du_lieu("moon", lat, lon, alt, fenetre)
            astre = astro._vu_du_lieu(ident, lat, lon, alt, fenetre)
            sep = lune.separation_from(astre).radians
            r_l = np.arcsin(RAYON_LUNE_KM / lune.distance().km)
            cache = (sep < r_l) & (lune.altaz()[0].degrees > 5) & (_hauteur_soleil(lieu_topo, fenetre) < SOLEIL_NUIT)
            if not cache.any():
                continue
            indices = np.nonzero(cache)[0]
            t = fenetre[int(indices[0])]
            evenements.append({
                "type": "occultation",
                "titre": f"La Lune cache {nom}",
                "instant": t.utc_iso(),  # disparition derrière la Lune
                "fin": fenetre[int(indices[-1])].utc_iso(),  # réapparition (ou fin de visibilité)
                "important": categorie == "planete",
                "objet_id": objet_id,
                "direction": _direction(ident, lat, lon, alt, t),
            })
    return evenements


def saisons(lat, lon, alt, debut, fin):
    temps, valeurs = almanac.find_discrete(debut, fin, almanac.seasons(_eph()))
    nord = lat >= 0
    return [
        {
            "type": "saison",
            # Dans l'hémisphère sud, les saisons sont inversées
            "titre": NOMS_SAISONS[int(v) if nord else (int(v) + 2) % 4],
            "instant": t.utc_iso(),
            "important": False,
            "objet_id": None,
            "direction": None,
        }
        for t, v in zip(temps, valeurs)
    ]


# --- Tout ensemble -----------------------------------------------------------------------------

def evenements(objets, lat, lon, alt, debut, jours):
    """objets : [(id, nom, identifiant, categorie)] de la base, avec un identifiant de calcul.
    Événements triés par instant."""
    fin = _ts().tt_jd(debut.tt + jours)
    lune_id = next((o[0] for o in objets if o[2] == "moon"), None)
    sats = [o[:3] for o in objets if satellites.numero_de(o[2]) is not None]
    astres = [o for o in objets if o[3] in ("planete", "lune") and satellites.numero_de(o[2]) is None]
    liste = (
        phases_lune(lat, lon, alt, debut, fin, lune_id)
        + conjonctions(astres, lat, lon, alt, debut, fin)
        + essaims(lat, lon, alt, debut, fin)
        + eclipses_lune(lat, lon, alt, debut, fin, lune_id)
        + passages_visibles(sats, lat, lon, alt, debut, fin)
        + eclipses_soleil(lat, lon, alt, debut, fin)
        + oppositions(objets, lat, lon, alt, debut, fin)
        + elongations(objets, lat, lon, alt, debut, fin)
        + occultations(objets, lat, lon, alt, debut, fin)
        + saisons(lat, lon, alt, debut, fin)
    )
    for e in liste:
        e.setdefault("important", e["type"] in IMPORTANTS or (e["type"] == "essaim" and e.get("zhr", 0) >= 50))
        e.setdefault("source", "calcul")  # Partie 8.3 : « NOAA SWPC », « COBS »... pour les sources externes
    return sorted(liste, key=lambda e: e["instant"])
