# ciel/astro.py
from functools import lru_cache
from pathlib import Path

import numpy as np
from skyfield import almanac
from skyfield.api import Loader, Star, wgs84
from skyfield.data import hipparcos

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


def altaz(identifiant, latitude, longitude, altitude_m=0, instant=None):
    """Retourne (élévation, azimut) en degrés.
    instant : un objet temps Skyfield. Par défaut, maintenant."""
    if instant is None:
        instant = _timescale().now()
    lieu = _ephemerides()["earth"] + wgs84.latlon(
        latitude, longitude, elevation_m=altitude_m
    )
    apparent = lieu.at(instant).observe(_corps(identifiant)).apparent()
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
    lieu = _ephemerides()["earth"] + wgs84.latlon(latitude, longitude, elevation_m=altitude_m)
    ra, dec, _ = lieu.at(t).observe(_corps(identifiant)).radec()
    return float(ra._degrees), float(dec.degrees)


def maintenant():
    """Instant présent (objet temps Skyfield, en UTC)."""
    return _timescale().now()


def trajectoire(identifiant, latitude, longitude, altitude_m=0,
                debut=None, duree_h=24, pas_min=10):
    """Positions successives d'un astre : liste de dicts
    {instant (UTC), elevation, azimut}, un point tous les pas_min minutes."""
    ts = _timescale()
    if debut is None:
        debut = ts.now()
    n = int(duree_h * 60 / pas_min) + 1
    instants = ts.tt_jd(debut.tt + np.arange(n) * pas_min / 1440.0)
    lieu = _ephemerides()["earth"] + wgs84.latlon(
        latitude, longitude, elevation_m=altitude_m
    )
    apparent = lieu.at(instants).observe(_corps(identifiant)).apparent()
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
