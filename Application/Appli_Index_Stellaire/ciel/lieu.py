"""Partie 6.4 : le lieu à utiliser pour les calculs du ciel et du pointage, par ordre de
préférence :

1. Le robot, s'il est connecté et a rapporté sa position GPS (Partie 6.2) ;
2. La position partagée par ce navigateur (bouton « Partager ma position »), gardée en session ;
3. Le lieu par défaut des réglages (LIEU_PAR_DEFAUT).

Un seul navigateur peut partager sa position à la fois (projet mono-utilisateur, comme le
pilotage, Partie 5). Elle n'est jamais envoyée au robot : elle sert seulement de secours, pour
viser correctement avant que le GPS de l'appareil n'ait un point.
"""

from django.conf import settings

CLE_SESSION = "lieu_partage"
DUREE_S = 12 * 3600  # une position de téléphone vieillit vite (le porteur se déplace)


def lieu_partage(request):
    """{latitude, longitude, altitude_m} partagé par ce navigateur, ou None."""
    return request.session.get(CLE_SESSION)


def definir_partage(request, latitude, longitude, altitude_m):
    request.session[CLE_SESSION] = {
        "latitude": latitude, "longitude": longitude, "altitude_m": altitude_m,
    }
    request.session.set_expiry(DUREE_S)


def retirer_partage(request):
    request.session.pop(CLE_SESSION, None)


def lieu_courant(request):
    """Lieu pour les calculs du ciel (carte, fiches, événements) : robot connecté avec GPS,
    sinon position partagée par ce navigateur, sinon LIEU_PAR_DEFAUT."""
    from appareil.services import appareil_principal, lieu_observation  # import tardif : évite que `ciel` dépende d'`appareil` au chargement des apps

    appareil = appareil_principal()
    if appareil is not None and appareil.connecte and appareil.latitude is not None:
        return lieu_observation(appareil)
    partage = lieu_partage(request)
    if partage is not None:
        return partage
    return settings.LIEU_PAR_DEFAUT
