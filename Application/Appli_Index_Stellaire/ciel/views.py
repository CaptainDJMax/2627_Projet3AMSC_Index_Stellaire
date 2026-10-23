import logging
from datetime import datetime, timezone

from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET

from .astro import altaz, instant_depuis, levers_couchers, maintenant, radec, trajectoire
from .models import ObjetCeleste

logger = logging.getLogger(__name__)


def _entier(request, nom, defaut, mini, maxi):
    """Lit un paramètre d'URL entier, borné entre mini et maxi."""
    try:
        valeur = int(request.GET.get(nom, defaut))
    except ValueError:
        return defaut
    return max(mini, min(maxi, valeur))


def _instant_demande(request):
    """Lit ?instant=<ISO 8601> ; sans paramètre, maintenant. Lève ValueError si invalide."""
    texte = request.GET.get("instant")
    if not texte:
        return maintenant()
    dt = datetime.fromisoformat(texte.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    if not 1950 <= dt.year <= 2049:  # plage couverte par l'éphéméride DE421
        raise ValueError("instant hors plage")
    return instant_depuis(dt)


@require_GET
def liste_objets(request):
    """Positions des objets calculables, à l'instant demandé (ou maintenant)."""
    lieu = settings.LIEU_PAR_DEFAUT
    try:
        instant = _instant_demande(request)  # même instant pour tous les objets
    except ValueError:
        return JsonResponse(
            {"erreur": "Paramètre 'instant' invalide (ISO 8601, 1950-2049)."}, status=400
        )
    objets = []

    for objet in ObjetCeleste.objects.exclude(identifiant_skyfield=""):
        ident = objet.identifiant_skyfield
        try:
            elevation, azimut = altaz(
                ident, lieu["latitude"], lieu["longitude"], lieu["altitude_m"], instant
            )
            ra, dec = radec(
                ident, lieu["latitude"], lieu["longitude"], lieu["altitude_m"], instant
            )
        except (KeyError, ValueError):
            # Un identifiant faux ne doit pas casser toute la carte
            logger.warning(
                "Identifiant Skyfield invalide pour %r : %r",
                objet.nom,
                ident,
            )
            continue
        objets.append(
            {
                "id": objet.id,
                "nom": objet.nom,
                "categorie": objet.categorie,
                "elevation": round(elevation, 2),
                "azimut": round(azimut, 2),
                "ra": round(ra, 4),
                "dec": round(dec, 4),
                "visible": elevation > 0,
            }
        )

    return JsonResponse(
        {"instant": instant.utc_iso(), "lieu": lieu, "objets": objets},
        json_dumps_params={"ensure_ascii": False},
    )


@require_GET
def detail_objet(request, objet_id):
    """Fiche complète d'un objet : contenu, position, trajectoire,
    levers et couchers, à l'instant demandé (ou maintenant). Paramètres
    facultatifs : ?duree=24 (heures, 1 à 72) et ?pas=10 (minutes, 1 à 60)."""
    try:
        objet = ObjetCeleste.objects.get(pk=objet_id)
    except ObjetCeleste.DoesNotExist:
        return JsonResponse({"erreur": "Objet introuvable."}, status=404)
    ident = objet.identifiant_skyfield
    if not ident:
        return JsonResponse(
            {"erreur": "Cet objet n'a pas d'identifiant de calcul."}, status=404
        )

    try:
        instant = _instant_demande(request)
    except ValueError:
        return JsonResponse(
            {"erreur": "Paramètre 'instant' invalide (ISO 8601, 1950-2049)."}, status=400
        )
    duree = _entier(request, "duree", 24, 1, 72)
    pas = _entier(request, "pas", 10, 1, 60)

    lieu = settings.LIEU_PAR_DEFAUT
    lat, lon, alt = lieu["latitude"], lieu["longitude"], lieu["altitude_m"]

    try:
        elevation, azimut = altaz(ident, lat, lon, alt, instant)
        evenements = levers_couchers(ident, lat, lon, alt, instant, duree)
        points = trajectoire(ident, lat, lon, alt, instant, duree, pas)
    except (KeyError, ValueError):
        logger.warning("Identifiant Skyfield invalide pour %r : %r", objet.nom, ident)
        return JsonResponse({"erreur": "Identifiant de calcul invalide."}, status=404)

    return JsonResponse(
        {
            "id": objet.id,
            "nom": objet.nom,
            "categorie": objet.categorie,
            "description": objet.description,
            "image": objet.image.url if objet.image else None,
            "constellations": [c.nom for c in objet.constellations.all()],
            "instant": instant.utc_iso(),
            "lieu": lieu,
            "position": {
                "elevation": round(elevation, 2),
                "azimut": round(azimut, 2),
                "visible": elevation > 0,
            },
            "levers_couchers": evenements,
            "trajectoire": points,
        },
        json_dumps_params={"ensure_ascii": False},
    )


@ensure_csrf_cookie  # dépose le cookie CSRF dont le JavaScript aura besoin pour ses requêtes POST
def carte(request):
    """Page principale : la carte du ciel."""
    lieu = {**settings.LIEU_PAR_DEFAUT, "fuseau": settings.TIME_ZONE}
    return render(request, "ciel/carte.html", {"lieu": lieu})
