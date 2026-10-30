"""Apparence des astres étendus sur la carte : Soleil, Lune, amas et ciel profond.

Ajoutée au champ `apparence` de /api/ciel/objets/ (seulement pour ces astres-là) :
la carte les dessine à leur vraie taille dans le ciel au lieu d'un simple rond, sans
cacher les étoiles (voiles en lumière additive, très transparents ; voir carte.js).

- Soleil : {"type": "soleil", "diametre": degrés}
- Lune :   {"type": "lune", "diametre": degrés, "eclairement": 0..1, "angle_soleil": degrés}
           angle_soleil = direction du Soleil vue de la Lune, du nord vers l'est (angle de
           position) : c'est le côté éclairé.
- Amas :   {"type": "amas", "diametre": degrés}
- Ciel profond : {"type": "ellipse", "grand_axe": degrés, "petit_axe": degrés,
                  "angle": degrés (grand axe, du nord vers l'est), "teinte": "galaxie" | "nebuleuse"}
"""

import math

from skyfield import almanac

from . import astro

RAYON_SOLEIL_KM = 696_000
RAYON_LUNE_KM = 1_737.4

# Taille et orientation des objets connus. Valeurs arrondies des catalogues (Messier/NGC) :
# c'est un repère pour l'œil, pas une mesure. Clé = nom de l'astre (comme dans contenu/astres/).
# Pour un nouvel objet sans ligne ici, la valeur par défaut de sa catégorie s'applique.
FORMES = {
    "Galaxie d'Andromède": {"type": "ellipse", "grand_axe": 3.2, "petit_axe": 1.0, "angle": 38, "teinte": "galaxie"},
    "Nébuleuse d'Orion": {"type": "ellipse", "grand_axe": 1.1, "petit_axe": 0.9, "angle": 0, "teinte": "nebuleuse"},
    "Pléiades": {"type": "amas", "diametre": 1.8},
}
PAR_DEFAUT = {
    "amas": {"type": "amas", "diametre": 0.5},
    "ciel_profond": {"type": "ellipse", "grand_axe": 0.5, "petit_axe": 0.5, "angle": 0, "teinte": "galaxie"},
}


def _diametre(rayon_km, distance_km):
    return round(2 * math.degrees(math.asin(min(1.0, rayon_km / distance_km))), 4)


def angle_de_position(ra1, dec1, ra2, dec2):
    """Angle (degrés, 0 = nord, 90 = est) de la direction du point 2 vu depuis le point 1."""
    r = math.radians
    d_ra = r(ra2 - ra1)
    y = math.sin(d_ra) * math.cos(r(dec2))
    x = math.cos(r(dec1)) * math.sin(r(dec2)) - math.sin(r(dec1)) * math.cos(r(dec2)) * math.cos(d_ra)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def apparence(objet, lieu, instant, ra=None, dec=None):
    """Dictionnaire d'apparence de l'objet (voir en tête du fichier), ou None pour un astre ponctuel."""
    ident = objet.identifiant_skyfield
    if objet.categorie in ("soleil", "lune") and ident in ("sun", "moon"):
        position = astro._vu_du_lieu(
            ident, lieu["latitude"], lieu["longitude"], lieu["altitude_m"], instant, apparente=False
        )
        distance = float(position.distance().km)
        if ident == "sun":
            return {"type": "soleil", "diametre": _diametre(RAYON_SOLEIL_KM, distance)}
        if ra is None:
            ra, dec = astro.radec(ident, lieu["latitude"], lieu["longitude"], lieu["altitude_m"], instant)
        ra_s, dec_s = astro.radec("sun", lieu["latitude"], lieu["longitude"], lieu["altitude_m"], instant)
        return {
            "type": "lune",
            "diametre": _diametre(RAYON_LUNE_KM, distance),
            "eclairement": round(float(almanac.fraction_illuminated(astro._ephemerides(), "moon", instant)), 3),
            "angle_soleil": round(angle_de_position(ra, dec, ra_s, dec_s), 1),
        }
    forme = FORMES.get(objet.nom) or PAR_DEFAUT.get(objet.categorie)
    return dict(forme) if forme else None
