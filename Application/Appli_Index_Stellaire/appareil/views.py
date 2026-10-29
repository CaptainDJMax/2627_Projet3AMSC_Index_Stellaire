import json
import logging
import math

from django.http import JsonResponse
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from ciel.astro import instant_depuis, maintenant
from ciel.lieu import lieu_partage
from ciel.models import ObjetCeleste

from . import pilotage, services
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
        logger.warning("Cible impossible à calculer pour %s", commande.nom)
        return None
    return {
        "id": commande.id,
        "mode": "pointer",
        "objet": commande.resume_objet(),  # id None pour un point du ciel (8.4)
        "coordonnees": commande.coordonnees,  # 8.4 : {ra, dec} pour un point du ciel, sinon None
        "cible": cible,
        # Partie 6.1 : où télécharger la trajectoire longue (une fois par nouvelle commande)
        "trajectoire": reverse("appareil:trajectoire"),
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
        # Partie 6.2 : position GPS, facultative ; latitude et longitude vont ensemble
        latitude = _nombre(corps, "latitude", -90, 90)
        longitude = _nombre(corps, "longitude", -180, 180)
        altitude_m = _nombre(corps, "altitude_m", -500, 9000)
        if (latitude is None) != (longitude is None):
            raise ValueError("latitude/longitude")
    except ValueError:
        return _erreur(
            "Corps JSON invalide (azimut, elevation, batterie, mode, latitude, longitude, altitude_m).", 400
        )

    appareil.derniere_vue = timezone.now()
    appareil.mode = mode
    if azimut is not None:
        appareil.azimut = azimut % 360
    if elevation is not None:
        appareil.elevation = elevation
    if batterie is not None:
        appareil.batterie = round(batterie)
    if latitude is not None:
        appareil.latitude, appareil.longitude = latitude, longitude
        appareil.altitude_m = altitude_m if altitude_m is not None else appareil.altitude_m
        appareil.lieu_mis_a_jour = appareil.derniere_vue
    appareil.save()

    instant = maintenant()
    return JsonResponse({
        "heure_serveur": instant.utc_iso(),
        "intervalle_ms": INTERVALLE_MS,
        "commande": _commande_pour_appareil(appareil, instant),
    })


@require_GET
def trajectoire_appareil(request):
    """Partie 6.1 : la trajectoire longue de la commande en cours, pour l'autonomie.

    L'appareil la télécharge quand l'id de la commande change, puis suit seul en interpolant
    entre deux points : il continue même si le réseau tombe. ?heures=1..48 (défaut 48).
    Réponse : {commande, type: "positions", debut, pas_s, format, points[[azimut, elevation]],
    tle, lieu}, ou {commande: null} sans commande.

    Partie 6.2 : pour un satellite, `tle` = {nom, ligne1, ligne2, epoque} (sinon null) : le robot
    calcule la position avec SGP4 ; les points (toutes les 5 s sur 6 h) servent de secours et de
    contrôle. `lieu` = le lieu pour lequel les points sont calculés (GPS de l'appareil s'il l'a
    envoyé)."""
    appareil = _appareil_authentifie(request)
    if appareil is None:
        return _erreur("Jeton d'appareil manquant ou invalide.", 401)
    commande = services.commande_active(appareil)
    if commande is None:
        return JsonResponse({"commande": None})
    try:
        heures = int(request.GET.get("heures", services.DUREE_TRAJECTOIRE_H))
    except ValueError:
        return _erreur("Paramètre 'heures' invalide (entier de 1 à 48).", 400)
    heures = max(1, min(services.DUREE_TRAJECTOIRE_H, heures))

    # Début à la seconde entière : `debut` est envoyé sans fraction de seconde, et l'ISS
    # parcourt jusqu'à 1° par seconde (sans cet arrondi, 0,4° d'erreur sur chaque point).
    debut = instant_depuis(maintenant().utc_datetime().replace(microsecond=0))
    try:
        traj = services.trajectoire_pour_appareil(commande, debut, heures)
    except (KeyError, ValueError) as erreur:
        logger.warning("Trajectoire impossible à calculer pour %s : %s", commande.nom, erreur)
        return _erreur(f"Trajectoire impossible à calculer pour cet objet ({erreur}).", 422)
    return JsonResponse({
        "commande": {"id": commande.id, "objet": commande.resume_objet()},
        "type": "positions",  # toujours des points ; un satellite a en plus son TLE (champ tle)
        "debut": debut.utc_iso(),
        "pas_s": traj["pas_s"],
        "format": ["azimut", "elevation"],
        "points": traj["points"],
        "tle": traj["tle"],  # Partie 6.2
        "lieu": traj["lieu"],  # Partie 6.2
    })


# ===========================================================================
# Côté interface web : état, choix d'une cible, arrêt
# ===========================================================================


def _etat(appareil, secours=None):
    """Ce que l'interface affiche : l'appareil, la commande en cours, l'écart.
    `secours` (Partie 6.4) : position partagée par ce navigateur, utilisée tant que le robot
    n'a pas encore de GPS à lui — jamais à la place d'un GPS déjà rapporté."""
    if appareil is None:
        return {"appareil": None, "commande": None, "ecart_deg": None}

    commande = services.commande_active(appareil)
    resume_commande = None
    ecart = None
    if commande is not None:
        try:
            cible = services.cible_de(commande, secours=secours)
        except (KeyError, ValueError):
            cible = None
        resume_commande = {
            "objet": commande.resume_objet(),
            "coordonnees": commande.coordonnees,  # 8.4
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

    ciel = services.position_ciel_du_bras(appareil, secours=secours)
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


def _reponse_etat(request, appareil):
    """L'état du pointage, plus le champ « pilotage » (ce navigateur peut-il piloter le bras ?)."""
    return JsonResponse({**_etat(appareil, secours=lieu_partage(request)), "pilotage": pilotage.etat(request)})


@require_GET
def etat_pointage(request):
    return _reponse_etat(request, services.appareil_principal())


@require_POST
@pilotage.pilotage_requis
def definir_commande(request):
    appareil = services.appareil_principal()
    if appareil is None:
        return _erreur("Aucun appareil enregistré.", 404)
    try:
        corps = json.loads(request.body or b"{}")
        if not isinstance(corps, dict):
            raise ValueError("corps")
        if "objet_id" not in corps and "ra" in corps:
            # Partie 8.4 (F18) : un point du ciel {"ra": 0..360, "dec": -90..90, "nom": facultatif}
            ra = _nombre(corps, "ra", -360, 360)
            dec = _nombre(corps, "dec", -90, 90)
            nom = corps.get("nom", "")
            if ra is None or dec is None or not isinstance(nom, str) or len(nom) > 60:
                raise ValueError("point")
            services.definir_point(appareil, ra, dec, nom.strip())
            return _reponse_etat(request, appareil)
        objet_id = corps["objet_id"]
        if isinstance(objet_id, bool) or not isinstance(objet_id, int):
            raise ValueError("objet_id")
    except (ValueError, KeyError, TypeError):
        return _erreur(
            'Corps JSON attendu : {"objet_id": <entier>} ou {"ra": <degrés>, "dec": <degrés>}.', 400
        )

    objet = ObjetCeleste.objects.filter(pk=objet_id).exclude(identifiant_skyfield="").first()
    if objet is None:
        return _erreur("Objet introuvable ou sans identifiant Skyfield.", 404)

    services.definir_cible(appareil, objet)
    return _reponse_etat(request, appareil)


@require_POST
@pilotage.pilotage_requis
def arreter_pointage(request):
    appareil = services.appareil_principal()
    if appareil is None:
        return _erreur("Aucun appareil enregistré.", 404)
    services.arreter(appareil)
    return _reponse_etat(request, appareil)


# ===========================================================================
# Partie 5 : le code de pilotage (ouvrir / fermer l'autorisation de ce navigateur)
# ===========================================================================


@require_POST
def ouvrir_pilotage(request):
    """POST {"code": "..."} : un bon code autorise ce navigateur pendant 30 jours."""
    if not pilotage.code_configure():
        return _erreur("Code de pilotage non configuré sur le serveur (fichier code_pilotage.txt).", 503)
    attente = pilotage.secondes_de_blocage(request)
    if attente:
        return JsonResponse(
            {"erreur": "Trop d'essais. Réessaie plus tard.", "attente_s": attente}, status=429
        )
    try:
        code = json.loads(request.body or b"{}")["code"]
        if not isinstance(code, str):
            raise ValueError("code")
    except (ValueError, KeyError, TypeError):
        return _erreur('Corps JSON attendu : {"code": "..."}.', 400)

    if pilotage.code_correct(code):
        pilotage.oublier_echecs(request)
        pilotage.autoriser(request)
        return JsonResponse({"pilotage": pilotage.etat(request)})

    restants = pilotage.noter_echec(request)
    if restants == 0:
        logger.warning("Pilotage : trop de codes faux depuis %s", request.META.get("REMOTE_ADDR"))
        return JsonResponse(
            {"erreur": "Trop d'essais. Réessaie plus tard.", "attente_s": pilotage.secondes_de_blocage(request)},
            status=429,
        )
    return JsonResponse({"erreur": "Code incorrect.", "essais_restants": restants}, status=403)


@require_POST
def fermer_pilotage(request):
    """Retire l'autorisation de ce navigateur (bouton « Verrouiller »)."""
    pilotage.retirer(request)
    return JsonResponse({"pilotage": pilotage.etat(request)})
