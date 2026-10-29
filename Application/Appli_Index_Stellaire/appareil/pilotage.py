"""Partie 5 : le code de pilotage.

Piloter le bras (« Pointer », « Arrêter ») demande un code ; regarder le ciel et l'état de
l'appareil, non. Le projet est mono-utilisateur : pas de comptes, un seul code.

- Le code est dans le réglage CODE_PILOTAGE (lu par settings.py dans le fichier code_pilotage.txt
  ou la variable d'environnement INDEX_STELLAIRE_CODE) : jamais dans le code source.
- Un bon code autorise CE navigateur pendant 30 jours (session Django), jusqu'à « Verrouiller ».
- Changer le code retire l'autorisation à tous les navigateurs déjà autorisés.
- Après 5 codes faux, l'adresse IP est bloquée 15 minutes.
- L'appareil (ESP32) n'est pas concerné : il garde son jeton (/api/appareil/sync/).
"""

import hashlib
import hmac
import time
from functools import wraps

from django.conf import settings
from django.core.cache import cache
from django.http import JsonResponse

DUREE_AUTORISATION_S = 30 * 24 * 3600
ESSAIS_MAX = 5
BLOCAGE_S = 15 * 60
CLE_SESSION = "pilotage"


def code_configure():
    """Le code attendu, ou "" s'il n'est pas configuré (le pilotage est alors refusé)."""
    return str(getattr(settings, "CODE_PILOTAGE", "") or "").strip()


def _empreinte(code):
    """Ce qu'on garde en session : pas le code, une empreinte liée au code actuel."""
    return hashlib.sha256(f"{settings.SECRET_KEY}|pilotage|{code}".encode()).hexdigest()


def est_autorise(request):
    code = code_configure()
    return bool(code) and hmac.compare_digest(str(request.session.get(CLE_SESSION, "")), _empreinte(code))


def etat(request):
    """Champ « pilotage » ajouté aux réponses de l'API de pointage."""
    return {"autorise": est_autorise(request), "configure": bool(code_configure())}


def code_correct(propose):
    attendu = code_configure()
    return bool(attendu) and hmac.compare_digest(propose.strip().encode(), attendu.encode())


def autoriser(request):
    request.session.cycle_key()  # nouvel identifiant de session après l'authentification
    request.session[CLE_SESSION] = _empreinte(code_configure())
    request.session.set_expiry(DUREE_AUTORISATION_S)


def retirer(request):
    request.session.pop(CLE_SESSION, None)


# --- Limite d'essais, par adresse IP ------------------------------------------------------

def _cle_essais(request):
    return "pilotage-essais:" + (request.META.get("REMOTE_ADDR") or "inconnue")


def secondes_de_blocage(request):
    donnees = cache.get(_cle_essais(request)) or {}
    return max(0, int(donnees.get("bloque_jusqu_a", 0) - time.time()))


def noter_echec(request):
    """Compte un code faux. Renvoie le nombre d'essais restants (0 = bloqué pour BLOCAGE_S)."""
    cle = _cle_essais(request)
    donnees = cache.get(cle) or {"echecs": 0, "bloque_jusqu_a": 0}
    donnees["echecs"] += 1
    restants = ESSAIS_MAX - donnees["echecs"]
    if restants <= 0:
        donnees = {"echecs": 0, "bloque_jusqu_a": time.time() + BLOCAGE_S}
        restants = 0
    cache.set(cle, donnees, BLOCAGE_S)
    return restants


def oublier_echecs(request):
    cache.delete(_cle_essais(request))


# --- Décorateur pour les vues qui font bouger le bras ---------------------------------------

def pilotage_requis(vue):
    @wraps(vue)
    def enveloppe(request, *args, **kwargs):
        if not est_autorise(request):
            return JsonResponse(
                {"erreur": "Code de pilotage requis.", "code_requis": True, "pilotage": etat(request)},
                status=403,
            )
        return vue(request, *args, **kwargs)

    return enveloppe
