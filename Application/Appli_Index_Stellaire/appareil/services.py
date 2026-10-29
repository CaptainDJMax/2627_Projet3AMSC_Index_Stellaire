"""Logique métier du pointage, indépendante de HTTP (testable seule)."""

import math

from django.conf import settings
from django.db import transaction

from ciel.astro import altaz, radec_depuis_altaz, trajectoire

from .models import Appareil, Commande


def lieu_observation():
    """Où se trouve le bras. Pour l'instant : le lieu par défaut des réglages.
    Plus tard (Partie 13), ce sera la position GPS rapportée par l'appareil."""
    return settings.LIEU_PAR_DEFAUT


def appareil_principal():
    """Le projet est mono-appareil : on prend le premier. None s'il n'y en a pas."""
    return Appareil.objects.order_by("id").first()


def commande_active(appareil):
    return appareil.commandes.filter(active=True).select_related("objet").first()


@transaction.atomic
def definir_cible(appareil, objet):
    """Remplace la commande en cours par un pointage sur `objet`."""
    appareil.commandes.filter(active=True).update(active=False)
    return Commande.objects.create(appareil=appareil, objet=objet)


def arreter(appareil):
    appareil.commandes.filter(active=True).update(active=False)


def cible_de(commande, instant=None):
    """Où doit pointer le bras maintenant pour viser l'objet de la commande.

    L'élévation peut être négative : le bras est une structure ouverte, il sait
    pointer à travers la Terre (objets de l'autre côté du globe)."""
    lieu = lieu_observation()
    elevation, azimut = altaz(
        commande.objet.identifiant_skyfield,
        lieu["latitude"], lieu["longitude"], lieu["altitude_m"],
        instant,
    )
    return {"azimut": round(azimut, 3), "elevation": round(elevation, 3), "visible": elevation > 0}


# Partie 6.1 : trajectoire longue, pour que le bras suive sa cible même sans réseau
PAS_TRAJECTOIRE_S = 60  # une position par minute ; l'appareil interpole entre deux points
DUREE_TRAJECTOIRE_H = 48  # l'autonomie visée


def trajectoire_de(commande, debut, heures=DUREE_TRAJECTOIRE_H):
    """Positions [azimut, élévation] (degrés, 2 décimales) du bras pour viser l'objet de la
    commande, une par minute de `debut` à `debut + heures`, bornes comprises."""
    lieu = lieu_observation()
    points = trajectoire(
        commande.objet.identifiant_skyfield,
        lieu["latitude"], lieu["longitude"], lieu["altitude_m"],
        debut, heures, PAS_TRAJECTOIRE_S // 60,
    )
    return [[round(p["azimut"], 2), round(p["elevation"], 2)] for p in points]


def position_ciel_du_bras(appareil):
    """Où pointe le bras, en coordonnées du ciel (ra, dec) : de quoi le dessiner sur la carte.
    None tant que l'appareil n'a jamais rapporté sa position."""
    if appareil.azimut is None or appareil.elevation is None:
        return None
    lieu = lieu_observation()
    ra, dec = radec_depuis_altaz(
        appareil.azimut, appareil.elevation, lieu["latitude"], lieu["longitude"], lieu["altitude_m"]
    )
    return {"ra": round(ra, 3), "dec": round(dec, 3)}


def ecart_angulaire(a, b):
    """Angle (degrés) entre deux directions (azimut, élévation), par la trigonométrie sphérique."""
    az1, el1, az2, el2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    c = math.sin(el1) * math.sin(el2) + math.cos(el1) * math.cos(el2) * math.cos(az1 - az2)
    return math.degrees(math.acos(max(-1.0, min(1.0, c))))
