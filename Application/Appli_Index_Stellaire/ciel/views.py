import json
import logging
from datetime import datetime, timezone

from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from .astro import (
    altaz, est_satellite, infos, instant_depuis, levers_couchers, maintenant, passages, radec,
    trace_satellite, trajectoire,
)
from . import evenements as calcul_evenements
from . import sources_externes
from .lieu import definir_partage, lieu_courant, lieu_partage, retirer_partage
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
    lieu = lieu_courant(request)
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
            # Partie 6.3 : un satellite bouge vite ; son trajet sur 12 min permet au navigateur
            # de le faire avancer entre deux chargements
            trace = trace_satellite(
                ident, lieu["latitude"], lieu["longitude"], lieu["altitude_m"], instant
            ) if est_satellite(ident) else None
        except (KeyError, ValueError):
            # Un identifiant faux ne doit pas casser toute la carte
            logger.warning(
                "Identifiant Skyfield invalide pour %r : %r",
                objet.nom,
                ident,
            )
            continue
        donnees = {
            "id": objet.id,
            "nom": objet.nom,
            "categorie": objet.categorie,
            "elevation": round(elevation, 2),
            "azimut": round(azimut, 2),
            "ra": round(ra, 4),
            "dec": round(dec, 4),
            "visible": elevation > 0,
        }
        if trace is not None:
            donnees["trace"] = trace  # satellites seulement
        objets.append(donnees)

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

    lieu = lieu_courant(request)
    lat, lon, alt = lieu["latitude"], lieu["longitude"], lieu["altitude_m"]

    try:
        elevation, azimut = altaz(ident, lat, lon, alt, instant)
        evenements = levers_couchers(ident, lat, lon, alt, instant, duree)
        points = trajectoire(ident, lat, lon, alt, instant, duree, pas)
        # Partie 6.3 : prochains passages (48 h) pour un satellite, None pour les autres astres
        prochains = passages(ident, lat, lon, alt, instant) if est_satellite(ident) else None
        # Partie 8.1 : magnitude, coordonnées, constellation, distance, et la nuit qui vient
        plus = infos(ident, lat, lon, alt, instant)
        soir = calcul_evenements.ce_soir([(objet.id, objet.nom, ident)], lat, lon, alt, instant)
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
            # Ajoutés pour le contenu (Partie 10) : crédit obligatoire de l'image et sources du texte
            "image_credit": {
                "source": objet.image_source,
                "auteur": objet.image_auteur,
                "licence": objet.image_licence,
            } if objet.image else None,
            "sources": [s.strip() for s in objet.sources.splitlines() if s.strip()],
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
            "passages": prochains,  # Partie 6.3
            # Partie 8.1
            **plus,  # magnitude, ra, dec, constellation_iau, distance_km, distance_al, eclairement
            "ce_soir": {
                "debut_nuit": soir["debut_nuit"],
                "fin_nuit": soir["fin_nuit"],
                # {de, a, hauteur_max, instant} si l'astre monte à 10° ou plus pendant la nuit, sinon None
                "visible": {k: soir["astres"][0][k] for k in ("de", "a", "hauteur_max", "instant")}
                if soir["astres"] else None,
            },
        },
        json_dumps_params={"ensure_ascii": False},
    )


@require_GET
def evenements(request):
    """Partie 7 : ce qu'on peut voir à l'œil nu. ?instant=<ISO 8601> (défaut : maintenant),
    ?jours=1..31 (défaut 7). Réponse : {instant, jours, lieu, ce_soir, evenements[]}."""
    try:
        instant = _instant_demande(request)
    except ValueError:
        return JsonResponse(
            {"erreur": "Paramètre 'instant' invalide (ISO 8601, 1950-2049)."}, status=400
        )
    try:
        jours = int(request.GET.get("jours", 7))
    except ValueError:
        return JsonResponse({"erreur": "Paramètre 'jours' invalide (entier de 1 à 31)."}, status=400)
    jours = max(1, min(31, jours))

    lieu = lieu_courant(request)
    lat, lon, alt = lieu["latitude"], lieu["longitude"], lieu["altitude_m"]
    objets = [
        (o.id, o.nom, o.identifiant_skyfield, o.categorie)
        for o in ObjetCeleste.objects.exclude(identifiant_skyfield="").order_by("nom")
    ]
    # « Ce soir » : la Lune et les planètes (les étoiles sont toujours là, elles n'en sont pas)
    soir = [o[:3] for o in objets if o[3] in ("planete", "lune")]
    liste = calcul_evenements.evenements(objets, lat, lon, alt, instant, jours)
    # Partie 8.3 : aurores et comètes, prises à des sources en temps réel (si internet)
    fin = instant.ts.tt_jd(instant.tt + jours)
    externes, statuts = sources_externes.evenements_externes(lat, lon, alt, instant, fin)
    return JsonResponse(
        {
            "instant": instant.utc_iso(),
            "jours": jours,
            "lieu": lieu,
            "ce_soir": calcul_evenements.ce_soir(soir, lat, lon, alt, instant),
            "evenements": sorted(liste + externes, key=lambda e: e["instant"]),
            "sources": [{"nom": "Calcul interne (Skyfield, éphéméride JPL DE421)", "page": "https://rhodesmill.org/skyfield/",
                         "licence": "", "etat": "ok", "age_h": None}] + statuts,
        },
        json_dumps_params={"ensure_ascii": False},
    )


@ensure_csrf_cookie  # dépose le cookie CSRF dont le JavaScript aura besoin pour ses requêtes POST
def carte(request):
    """Page principale : la carte du ciel."""
    lieu = {**lieu_courant(request), "fuseau": settings.TIME_ZONE, "partage": lieu_partage(request) is not None}
    return render(request, "ciel/carte.html", {"lieu": lieu})


@require_POST
def partager_lieu(request):
    """Partie 6.4 : ce navigateur partage sa position (bouton « Partager ma position »), ou la
    retire. POST {"latitude": .., "longitude": .., "altitude_m": ..} ou {"partager": false}.
    Ne touche pas le GPS du robot : sert seulement de secours tant qu'il n'en a pas."""
    try:
        corps = json.loads(request.body or b"{}")
        if not isinstance(corps, dict):
            raise ValueError("corps")
    except ValueError:
        return JsonResponse({"erreur": "Corps JSON invalide."}, status=400)

    if corps.get("partager") is False:
        retirer_partage(request)
        return JsonResponse({"lieu": None})

    try:
        latitude = float(corps["latitude"])
        longitude = float(corps["longitude"])
        altitude_m = float(corps.get("altitude_m") or 0)
    except (KeyError, TypeError, ValueError):
        return JsonResponse(
            {"erreur": 'Corps JSON attendu : {"latitude": .., "longitude": .., "altitude_m": ..}.'},
            status=400,
        )
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return JsonResponse({"erreur": "Coordonnées hors limites."}, status=400)

    definir_partage(request, latitude, longitude, altitude_m)
    return JsonResponse({"lieu": lieu_partage(request)})
