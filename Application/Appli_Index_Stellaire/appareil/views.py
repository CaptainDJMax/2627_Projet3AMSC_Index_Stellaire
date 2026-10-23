import json
import logging
import math

from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from ciel.astro import maintenant
from ciel.models import ObjetCeleste

from . import services
from .models import Appareil

logger = logging.getLogger(__name__)

INTERVALLE_MS = 1000  # cadence de synchronisation demandée à l'appareil


def _erreur(message, statut):
    return JsonResponse({"erreur": message}, status=statut)


# ===========================================================================
# Côté appareil (ESP32) : authentifié par un jeton, pas de session ni de CSRF
# ===========================================================================


def _appareil_authentifie(request):
    entete = request.headers.get("Authorization", "")
    if not entete.startswith("Bearer "):
        return None
    return Appareil.objects.filter(jeton=entete[7:].strip()).first()


def _nombre(corps, cle, mini, maxi):
    """Nombre optionnel du corps JSON, borné. ValueError s'il est invalide."""
    valeur = corps.get(cle)
    if valeur is None:
        return None
    if isinstance(valeur, bool) or not isinstance(valeur, (int, float)):
        raise ValueError(cle)
    if not math.isfinite(valeur) or not mini <= valeur <= maxi:
        raise ValueError(cle)
    return float(valeur)


def _commande_pour_appareil(appareil, instant):
    commande = services.commande_active(appareil)
    if commande is None:
        return None
    try:
        cible = services.cible_de(commande, instant)
    except (KeyError, ValueError):
        logger.warning("Cible impossible à calculer pour %s", commande.objet)
        return None
    return {
        "id": commande.id,
        "mode": "pointer",
        "objet": {"id": commande.objet.id, "nom": commande.objet.nom},
        "cible": cible,
    }


@csrf_exempt
@require_POST
def synchroniser(request):
    """L'appareil envoie son état et reçoit sa consigne, en un seul aller-retour."""
    appareil = _appareil_authentifie(request)
    if appareil is None:
        return _erreur("Jeton d'appareil manquant ou invalide.", 401)

    try:
        corps = json.loads(request.body or b"{}")
        if not isinstance(corps, dict):
            raise ValueError("corps")
        azimut = _nombre(corps, "azimut", -3600, 3600)  # la bague collectrice tourne sans fin
        elevation = _nombre(corps, "elevation", -90, 90)
        batterie = _nombre(corps, "batterie", 0, 100)
        mode = corps.get("mode", appareil.mode)
        if mode not in Appareil.Mode.values:
            raise ValueError("mode")
    except ValueError:
        return _erreur("Corps JSON invalide (azimut, elevation, batterie, mode).", 400)

    appareil.derniere_vue = timezone.now()
    appareil.mode = mode
    if azimut is not None:
        appareil.azimut = azimut % 360
    if elevation is not None:
        appareil.elevation = elevation
    if batterie is not None:
        appareil.batterie = round(batterie)
    appareil.save()

    instant = maintenant()
    return JsonResponse({
        "heure_serveur": instant.utc_iso(),
        "intervalle_ms": INTERVALLE_MS,
        "commande": _commande_pour_appareil(appareil, instant),
    })


# ===========================================================================
# Côté interface web : état, choix d'une cible, arrêt
# ===========================================================================


def _etat(appareil):
    """Ce que l'interface affiche : l'appareil, la commande en cours, l'écart."""
    if appareil is None:
        return {"appareil": None, "commande": None, "ecart_deg": None}

    commande = services.commande_active(appareil)
    resume_commande = None
    ecart = None
    if commande is not None:
        try:
            cible = services.cible_de(commande)
        except (KeyError, ValueError):
            cible = None
        resume_commande = {
            "objet": {"id": commande.objet.id, "nom": commande.objet.nom},
            "depuis": commande.cree_le.isoformat(),
            "cible": cible,
        }
        if cible and appareil.azimut is not None and appareil.elevation is not None:
            ecart = round(
                services.ecart_angulaire(
                    (appareil.azimut, appareil.elevation), (cible["azimut"], cible["elevation"])
                ),
                2,
            )

    ciel = services.position_ciel_du_bras(appareil)
    return {
        "appareil": {
            "nom": appareil.nom,
            "connecte": appareil.connecte,
            "derniere_vue": appareil.derniere_vue.isoformat() if appareil.derniere_vue else None,
            "azimut": appareil.azimut,
            "elevation": appareil.elevation,
            "batterie": appareil.batterie,
            "mode": appareil.mode,
            "ra": ciel["ra"] if ciel else None,
            "dec": ciel["dec"] if ciel else None,
        },
        "commande": resume_commande,
        "ecart_deg": ecart,
    }


@require_GET
def etat_pointage(request):
    return JsonResponse(_etat(services.appareil_principal()))


@require_POST
def definir_commande(request):
    appareil = services.appareil_principal()
    if appareil is None:
        return _erreur("Aucun appareil enregistré.", 404)
    try:
        corps = json.loads(request.body or b"{}")
        objet_id = corps["objet_id"]
        if isinstance(objet_id, bool) or not isinstance(objet_id, int):
            raise ValueError("objet_id")
    except (ValueError, KeyError, TypeError):
        return _erreur("Corps JSON attendu : {\"objet_id\": <entier>}.", 400)

    objet = ObjetCeleste.objects.filter(pk=objet_id).exclude(identifiant_skyfield="").first()
    if objet is None:
        return _erreur("Objet introuvable ou sans identifiant Skyfield.", 404)

    services.definir_cible(appareil, objet)
    return JsonResponse(_etat(appareil))


@require_POST
def arreter_pointage(request):
    appareil = services.appareil_principal()
    if appareil is None:
        return _erreur("Aucun appareil enregistré.", 404)
    services.arreter(appareil)
    return JsonResponse(_etat(appareil))
