"""Partie 14.1 bis : aperçu d'une visite guidée AVANT de la lancer.

POST /api/pointage/visite/apercu/ (lecture seule : pas de code de pilotage, CSRF comme les autres POST)
    {"debut": ISO 8601 ou null (maintenant), "etapes": [{"objet_id": n, "duree_min": m} ou
                                                         {"ra": .., "dec": .., "duree_min": m}]}
-> {"debut", "etapes": [{"debut", "fin", "hauteur_debut", "hauteur_fin", "hauteur_min", "sous_horizon"}]}

Pour chaque étape : son horaire (début de la visite + durées des étapes d'avant) et la hauteur de la
cible pendant l'étape, vue de là où est le bras. « sous_horizon » : la cible passe sous l'horizon
pendant l'étape (le bras viserait à travers le sol). Une étape non calculable a ses hauteurs à null.
"""

import json
from datetime import datetime, timedelta

import numpy as np
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_POST

from ciel import astro
from ciel.lieu import lieu_partage
from ciel.models import ObjetCeleste

from . import services

PAS_S = 300  # une hauteur toutes les 5 minutes, plus la fin de l'étape


def _erreur(message):
    return JsonResponse({"erreur": message}, status=400)


def _hauteurs(identifiant, lieu, debut, duree_s):
    secondes = np.append(np.arange(0, duree_s, PAS_S), duree_s)
    t0 = astro.instant_depuis(debut)
    t = astro._timescale().tt_jd(t0.tt + secondes / 86400.0)
    hauteur = astro._vu_du_lieu(identifiant, lieu["latitude"], lieu["longitude"], lieu["altitude_m"], t).altaz()[0].degrees
    return [round(float(h), 1) for h in (hauteur[0], hauteur[-1], np.min(hauteur))]


@require_POST
def apercu_visite(request):
    try:
        corps = json.loads(request.body or b"{}")
        brutes = corps["etapes"]
        if not isinstance(brutes, list) or not 1 <= len(brutes) <= services.ETAPES_MAX:
            raise ValueError("etapes")
        texte = corps.get("debut")
        if texte is None:
            debut = timezone.now()
        else:
            debut = datetime.fromisoformat(str(texte).replace("Z", "+00:00"))
            if debut.tzinfo is None:
                raise ValueError("debut sans fuseau")
    except (ValueError, KeyError, TypeError, AttributeError):
        return _erreur('Corps JSON attendu : {"debut": ISO ou null, "etapes": [{"objet_id": n, "duree_min": m}, ...]}.')

    lieu = services.lieu_observation(services.appareil_principal(), lieu_partage(request))
    resultat = []
    instant = debut.replace(microsecond=0)
    for b in brutes:
        if not isinstance(b, dict):
            return _erreur("Chaque étape doit être un objet { ... }.")
        duree = b.get("duree_min")
        if isinstance(duree, bool) or not isinstance(duree, int) or not 1 <= duree <= services.DUREE_ETAPE_MAX_MIN:
            return _erreur("duree_min doit être un entier de 1 à 240.")
        identifiant = None
        if isinstance(b.get("objet_id"), int) and not isinstance(b.get("objet_id"), bool):
            objet = ObjetCeleste.objects.filter(pk=b["objet_id"]).exclude(identifiant_skyfield="").first()
            identifiant = objet.identifiant_skyfield if objet else None
        elif all(isinstance(b.get(k), (int, float)) and not isinstance(b.get(k), bool) for k in ("ra", "dec")):
            if -90 <= b["dec"] <= 90:
                identifiant = f"radec:{b['ra'] % 360},{b['dec']}"
        fin = instant + timedelta(minutes=duree)
        hauteurs = [None, None, None]
        if identifiant:
            try:
                hauteurs = _hauteurs(identifiant, lieu, instant, duree * 60)
            except (KeyError, ValueError):
                pass
        resultat.append({
            "debut": instant.isoformat(), "fin": fin.isoformat(),
            "hauteur_debut": hauteurs[0], "hauteur_fin": hauteurs[1], "hauteur_min": hauteurs[2],
            "sous_horizon": hauteurs[2] is not None and hauteurs[2] < 0,
        })
        instant = fin
    return JsonResponse({"debut": debut.replace(microsecond=0).isoformat(), "etapes": resultat})
