# ciel/astro.py
from functools import lru_cache
from pathlib import Path

import numpy as np
from skyfield import almanac
from skyfield.api import EarthSatellite, Loader, Star, wgs84
from skyfield.data import hipparcos

from . import satellites

# Dossier à la racine du projet (à côté de manage.py), quel que soit
# l'endroit d'où on lance la commande
DOSSIER_DONNEES = Path(__file__).resolve().parent.parent / "donnees_skyfield"
charge = Loader(str(DOSSIER_DONNEES))


@lru_cache(maxsize=1)
def _timescale():
    return charge.timescale()


@lru_cache(maxsize=1)
def _ephemerides():
    # Positions du Soleil, de la Lune et des planètes
    return charge("de421.bsp")


@lru_cache(maxsize=1)
def _catalogue_hipparcos():
    # Catalogue d'environ 118 000 étoiles
    with charge.open(hipparcos.URL) as f:
        return hipparcos.load_dataframe(f)


def _corps(identifiant):
    """'hip:21421' -> une étoile du catalogue Hipparcos.
    Sinon, un nom de corps de l'éphéméride (ex. 'jupiter barycenter')."""
    if identifiant.startswith("hip:"):
        numero = int(identifiant[4:])
        return Star.from_dataframe(_catalogue_hipparcos().loc[numero])
    return _ephemerides()[identifiant]


# --- Partie 6.2 : satellites (« sat:25544 » = l'ISS), calculés par SGP4 à partir du TLE ----------

@lru_cache(maxsize=8)
def _satellite_depuis_tle(ligne1, ligne2, nom):
    return EarthSatellite(ligne1, ligne2, nom, _timescale())


def _satellite(identifiant):
    """Le satellite (Skyfield) si l'identifiant est « sat:NUMERO », sinon None.
    Lève satellites.TleIndisponible (une ValueError) sans TLE utilisable."""
    numero = satellites.numero_de(identifiant)
    if numero is None:
        return None
    d = satellites.tle(numero)
    return _satellite_depuis_tle(d["ligne1"], d["ligne2"], d["nom"])


def _vu_du_lieu(identifiant, latitude, longitude, altitude_m, instants, apparente=True):
    """Position de l'astre vue depuis le lieu, à un ou plusieurs instants.

    Satellite : position topocentrique directe (il est tout près, pas de temps de lumière
    à corriger). Autres astres : observation depuis la Terre, apparente ou astrométrique."""
    topos = wgs84.latlon(latitude, longitude, elevation_m=altitude_m)
    sat = _satellite(identifiant)
    if sat is not None:
        return (sat - topos).at(instants)
    position = (_ephemerides()["earth"] + topos).at(instants).observe(_corps(identifiant))
    return position.apparent() if apparente else position


def altaz(identifiant, latitude, longitude, altitude_m=0, instant=None):
    """Retourne (élévation, azimut) en degrés.
    instant : un objet temps Skyfield. Par défaut, maintenant."""
    if instant is None:
        instant = _timescale().now()
    apparent = _vu_du_lieu(identifiant, latitude, longitude, altitude_m, instant)
    elevation, azimut, _ = apparent.altaz()
    return float(elevation.degrees), float(azimut.degrees)


def radec_depuis_altaz(azimut, elevation, latitude, longitude, altitude_m=0, instant=None):
    """Direction (azimut, élévation) vue du lieu -> (ascension droite, déclinaison) en degrés.

    C'est l'inverse de `altaz` : sert à placer sur la carte l'endroit où pointe le bras."""
    t = instant if instant is not None else _timescale().now()
    lieu = _ephemerides()["earth"] + wgs84.latlon(latitude, longitude, elevation_m=altitude_m)
    ra, dec, _ = lieu.at(t).from_altaz(alt_degrees=elevation, az_degrees=azimut).radec()
    return float(ra._degrees), float(dec.degrees)


def radec(identifiant, latitude, longitude, altitude_m=0, instant=None):
    """Ascension droite et déclinaison (en degrés), repère J2000 (ICRS).

    Retourne (ra, dec), avec ra entre 0 et 360. C'est le repère des catalogues
    d'étoiles, donc celui de la carte : planètes et étoiles s'alignent.
    """
    t = instant if instant is not None else _timescale().now()
    ra, dec, _ = _vu_du_lieu(identifiant, latitude, longitude, altitude_m, t, apparente=False).radec()
    return float(ra._degrees), float(dec.degrees)


def maintenant():
    """Instant présent (objet temps Skyfield, en UTC)."""
    return _timescale().now()


def trajectoire(identifiant, latitude, longitude, altitude_m=0,
                debut=None, duree_h=24, pas_min=10):
    """Positions successives d'un astre : liste de dicts
    {instant (UTC), elevation, azimut}, un point tous les pas_min minutes
    (pas_min peut être fractionnaire : 5 / 60 = un point toutes les 5 s, pour l'ISS)."""
    ts = _timescale()
    if debut is None:
        debut = ts.now()
    n = int(round(duree_h * 60 / pas_min)) + 1
    instants = ts.tt_jd(debut.tt + np.arange(n) * pas_min / 1440.0)
    apparent = _vu_du_lieu(identifiant, latitude, longitude, altitude_m, instants)
    elevation, azimut, _ = apparent.altaz()
    return [
        {"instant": i, "elevation": round(float(e), 2), "azimut": round(float(a), 2)}
        for i, e, a in zip(instants.utc_iso(), elevation.degrees, azimut.degrees)
    ]


def levers_couchers(identifiant, latitude, longitude, altitude_m=0,
                    debut=None, duree_h=24):
    """Levers et couchers d'un astre dans la fenêtre donnée : liste de dicts
    {instant (UTC), evenement}. Liste vide si l'astre ne se lève ni ne se
    couche (toujours visible, comme Polaris, ou jamais visible)."""
    ts = _timescale()
    if debut is None:
        debut = ts.now()
    fin = ts.tt_jd(debut.tt + duree_h / 24.0)
    lieu = wgs84.latlon(latitude, longitude, elevation_m=altitude_m)
    sat = _satellite(identifiant)
    if sat is not None:
        # Satellite : début (0) et fin (2) de chaque passage au-dessus de l'horizon
        temps, types = sat.find_events(lieu, debut, fin, altitude_degrees=0.0)
        return [
            {"instant": t.utc_iso(), "evenement": "lever" if y == 0 else "coucher"}
            for t, y in zip(temps, types) if y in (0, 2)
        ]
    est_leve = almanac.risings_and_settings(
        _ephemerides(), _corps(identifiant), lieu, horizon_degrees=-0.5667
    )
    temps, types = almanac.find_discrete(debut, fin, est_leve)
    return [
        {"instant": t.utc_iso(), "evenement": "lever" if y else "coucher"}
        for t, y in zip(temps, types)
    ]


def instant_depuis(dt):
    """datetime avec fuseau -> instant Skyfield."""
    return _timescale().from_datetime(dt)


# --- Partie 6.3 : l'ISS sur la carte et ses passages -------------------------------------------

def est_satellite(identifiant):
    return satellites.numero_de(identifiant) is not None


def trace_satellite(identifiant, latitude, longitude, altitude_m=0, instant=None,
                    avant_min=2, apres_min=10, pas_s=15):
    """Trajet du satellite autour de l'instant, pour la carte : {debut (UTC), pas_s, points}
    avec points = [[ra, dec, elevation, azimut], ...] (degrés, J2000), de instant - avant_min
    à instant + apres_min. Le navigateur interpole entre deux points : le satellite avance
    sur la carte sans redemander sa position au serveur."""
    ts = _timescale()
    instant = instant if instant is not None else ts.now()
    n = int((avant_min + apres_min) * 60 / pas_s) + 1
    debut = ts.tt_jd(instant.tt - avant_min / 1440.0)
    instants = ts.tt_jd(debut.tt + np.arange(n) * pas_s / 86400.0)
    position = _vu_du_lieu(identifiant, latitude, longitude, altitude_m, instants)
    ra, dec, _ = position.radec()
    elevation, azimut, _ = position.altaz()
    return {
        "debut": debut.utc_iso(),
        "pas_s": pas_s,
        "points": [
            [round(float(r), 3), round(float(d), 3), round(float(e), 2), round(float(a), 2)]
            for r, d, e, a in zip(ra._degrees, dec.degrees, elevation.degrees, azimut.degrees)
        ],
    }


def passages(identifiant, latitude, longitude, altitude_m=0, debut=None, duree_h=48, hauteur_mini=10):
    """Passages du satellite au-dessus de l'horizon : liste de dicts {lever, culmination, coucher
    (UTC ; un passage en cours a son vrai lever, dans le passé ; coucher None s'il finit après
    la fenêtre),
    hauteur_max, azimut_lever, azimut_coucher, visible}. Seuls les passages qui montent à
    hauteur_mini degrés ou plus sont gardés (plus bas, on ne le voit pas derrière les obstacles).
    visible : satellite éclairé par le Soleil pendant que le ciel est noir (Soleil à plus de 6°
    sous l'horizon) au moment de la culmination, donc visible à l'œil nu."""
    ts = _timescale()
    debut = debut if debut is not None else ts.now()
    fin = ts.tt_jd(debut.tt + duree_h / 24.0)
    sat = _satellite(identifiant)
    if sat is None:
        return []
    topos = wgs84.latlon(latitude, longitude, elevation_m=altitude_m)
    # On cherche depuis 30 min plus tôt : un passage en cours (au plus une quinzaine de minutes)
    # a ainsi son vrai lever ; les passages déjà finis sont retirés plus bas.
    avant = ts.tt_jd(debut.tt - 30 / 1440.0)
    temps, types = sat.find_events(topos, avant, fin, altitude_degrees=0.0)

    # Regrouper les événements : lever (0), culmination(s) (1), coucher (2)
    groupes, courant = [], None
    for t, y in zip(temps, types):
        if y == 0:
            courant = {"lever": t, "culminations": [], "coucher": None}
            groupes.append(courant)
        else:
            if courant is None:  # passage déjà commencé au début de la fenêtre
                courant = {"lever": None, "culminations": [], "coucher": None}
                groupes.append(courant)
            if y == 1:
                courant["culminations"].append(t)
            else:
                courant["coucher"] = t
                courant = None

    vu = sat - topos
    terre_lieu = _ephemerides()["earth"] + topos
    soleil = _ephemerides()["sun"]
    resultat = []
    for g in groupes:
        if not g["culminations"] or (g["coucher"] is not None and g["coucher"].tt < debut.tt):
            continue
        hauteurs = [vu.at(t).altaz()[0].degrees for t in g["culminations"]]
        i = int(np.argmax(hauteurs))
        if hauteurs[i] < hauteur_mini:
            continue
        culmination = g["culminations"][i]
        hauteur_soleil = terre_lieu.at(culmination).observe(soleil).apparent().altaz()[0].degrees
        eclaire = bool(sat.at(culmination).is_sunlit(_ephemerides()))

        def azimut(t):
            return None if t is None else round(float(vu.at(t).altaz()[1].degrees), 1)

        resultat.append({
            "lever": g["lever"].utc_iso() if g["lever"] is not None else None,
            "culmination": culmination.utc_iso(),
            "coucher": g["coucher"].utc_iso() if g["coucher"] is not None else None,
            "hauteur_max": round(float(hauteurs[i]), 1),
            "azimut_lever": azimut(g["lever"]),
            "azimut_coucher": azimut(g["coucher"]),
            "visible": bool(eclaire and hauteur_soleil < -6),
        })
    return resultat
