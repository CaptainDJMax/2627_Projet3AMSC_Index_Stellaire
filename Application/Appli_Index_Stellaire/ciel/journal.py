"""Partie 9 : le journal d'observation.

Deux sortes de lignes, rangées ensemble du plus récent au plus ancien :
- les **observations** notées par l'utilisateur (modèle `Observation`) : quoi, quand, où, ciel,
  instrument, note ;
- les **pointages du bras** (historique des commandes, appli `appareil`), lus sans être recopiés.

Lire le journal est libre, comme la carte. Écrire ou effacer demande le code de pilotage (Partie 5) :
c'est le carnet du propriétaire. Le journal reste dans la base (pas dans Git : il est personnel).
"""

import csv
import io
import json
from datetime import datetime, timedelta

from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from appareil import pilotage

from .astro import altaz, instant_depuis
from .lieu import lieu_courant
from .models import ObjetCeleste, Observation

LIMITE_PAR_DEFAUT = 100
LIMITE_MAXI = 500
JOURS_POINTAGES = 60  # les pointages du bras montrés dans le journal
NOTE_MAXI = 2000


def _iso(d):
    return d.isoformat().replace("+00:00", "Z") if d else None


def _direction(identifiant, latitude, longitude, quand):
    """{azimut, elevation} de la cible à cet instant et ce lieu (pour « revoir » l'observation sur
    la carte), ou None si elle n'est plus calculable."""
    if not identifiant:
        return None
    try:
        el, az = altaz(identifiant, latitude, longitude, 0, instant_depuis(quand))
    except (KeyError, ValueError):
        return None
    return {"azimut": round(az, 1), "elevation": round(el, 1)}


def _identifiant(objet, ra, dec):
    if objet is not None:
        return objet.identifiant_skyfield
    return f"radec:{ra},{dec}" if ra is not None and dec is not None else ""


def observation_json(o):
    return {
        "id": o.id,
        "quand": _iso(o.quand),
        "nom": o.nom,
        "objet_id": o.objet_id,
        "coordonnees": {"ra": o.ra, "dec": o.dec} if o.objet_id is None and o.ra is not None else None,
        "lieu": {"latitude": o.latitude, "longitude": o.longitude},
        "ciel": o.ciel,
        "instrument": o.instrument,
        "note": o.note,
        "direction": _direction(_identifiant(o.objet, o.ra, o.dec), o.latitude, o.longitude, o.quand),
    }


def pointages(objet_id=None, limite=LIMITE_PAR_DEFAUT, lieu=None):
    """Les pointages du bras des 60 derniers jours : {quand, fin, nom, objet_id, coordonnees, visite}.
    Une visite guidée (Partie 8.5) donne une ligne par étape. `fin` : début de la commande suivante
    (ou None si c'est la commande en cours)."""
    from appareil.models import Commande  # import tardif : `ciel` ne dépend pas d'`appareil` au chargement

    depuis = timezone.now() - timedelta(days=JOURS_POINTAGES)
    commandes = list(Commande.objects.filter(cree_le__gte=depuis).select_related("objet").order_by("cree_le"))
    lignes = []
    for i, c in enumerate(commandes):
        # Fin : début de la commande suivante. Pour la dernière, inconnue (en cours, ou arrêtée sans
        # que l'heure de l'arrêt soit gardée)
        fin_commande = commandes[i + 1].cree_le if i + 1 < len(commandes) else None
        if c.programme:
            for _, etape, debut, fin in c.etapes_datees():
                # Étapes réellement atteintes avant que la commande soit remplacée
                if fin_commande is not None and debut >= fin_commande:
                    break
                bornes = [x for x in (fin, fin_commande) if x is not None]
                fin_effective = min(bornes) if bornes else None
                lignes.append({
                    "quand": _iso(max(debut, c.cree_le)), "fin": _iso(fin_effective), "nom": etape["nom"],
                    "objet_id": etape["objet_id"],
                    "coordonnees": None if etape["objet_id"] is not None else {"ra": etape["ra"], "dec": etape["dec"]},
                    "visite": True,
                })
        else:
            cible = c._cible(c.cree_le)
            lignes.append({
                "quand": _iso(c.cree_le), "fin": _iso(fin_commande), "nom": cible["nom"],
                "objet_id": cible["objet_id"], "coordonnees": cible["coordonnees"], "visite": False,
            })
    if objet_id is not None:
        lignes = [l for l in lignes if l["objet_id"] == objet_id]
    lignes.sort(key=lambda l: l["quand"], reverse=True)
    lignes = lignes[:limite]
    if lieu is not None:
        identifiants = dict(ObjetCeleste.objects.filter(id__in={l["objet_id"] for l in lignes}).values_list("id", "identifiant_skyfield"))
        for l in lignes:
            c = l["coordonnees"]
            ident = identifiants.get(l["objet_id"], "") if l["objet_id"] is not None else _identifiant(None, c["ra"], c["dec"])
            quand = datetime.fromisoformat(l["quand"].replace("Z", "+00:00"))
            l["direction"] = _direction(ident, lieu["latitude"], lieu["longitude"], quand)
    return lignes


def _lire_filtres(request):
    objet_id = request.GET.get("objet")
    objet_id = int(objet_id) if objet_id not in (None, "") else None
    limite = int(request.GET.get("limite", LIMITE_PAR_DEFAUT))
    return objet_id, max(1, min(LIMITE_MAXI, limite))


@require_GET
def lire(request):
    """GET /api/ciel/journal/?objet=<id>&limite=1..500 : {observations[], pointages[]}."""
    try:
        objet_id, limite = _lire_filtres(request)
    except ValueError:
        return JsonResponse({"erreur": "Paramètres 'objet' et 'limite' : des entiers."}, status=400)
    obs = Observation.objects.all()
    if objet_id is not None:
        obs = obs.filter(objet_id=objet_id)
    return JsonResponse(
        {"observations": [observation_json(o) for o in obs.select_related("objet")[:limite]],
         "pointages": pointages(objet_id, limite, lieu_courant(request))},
        json_dumps_params={"ensure_ascii": False},
    )


def _nombre(corps, cle, mini, maxi):
    v = corps.get(cle)
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not mini <= v <= maxi:
        raise ValueError(cle)
    return float(v)


@require_POST
@pilotage.pilotage_requis
def noter(request):
    """POST /api/ciel/journal/noter/ {objet_id ou ra/dec (+ nom), quand (ISO, facultatif),
    ciel, instrument, note} : ajoute une observation, au lieu courant. Code de pilotage requis."""
    try:
        corps = json.loads(request.body or b"{}")
        if not isinstance(corps, dict):
            raise ValueError("corps")
        objet, ra, dec, nom = None, None, None, ""
        if "objet_id" in corps:
            if isinstance(corps["objet_id"], bool) or not isinstance(corps["objet_id"], int):
                raise ValueError("objet_id")
            objet = ObjetCeleste.objects.filter(pk=corps["objet_id"]).first()
            if objet is None:
                return JsonResponse({"erreur": "Astre introuvable."}, status=404)
            nom = objet.nom
        else:
            ra, dec = _nombre(corps, "ra", 0, 360), _nombre(corps, "dec", -90, 90)
            nom = corps.get("nom") or "Point du ciel"
            if ra is None or dec is None or not isinstance(nom, str) or len(nom) > 100:
                raise ValueError("point")
        maintenant = timezone.now()
        if corps.get("quand"):
            quand = datetime.fromisoformat(str(corps["quand"]).replace("Z", "+00:00"))
            if quand.tzinfo is None:
                raise ValueError("quand sans fuseau")
            if quand > maintenant + timedelta(minutes=5) or quand < maintenant - timedelta(days=3650):
                return JsonResponse({"erreur": "Date d'observation impossible (dans le futur ?)."}, status=400)
        else:
            quand = maintenant
        ciel = corps.get("ciel", Observation.Ciel.INCONNU)
        instrument = corps.get("instrument", Observation.Instrument.OEIL)
        note = corps.get("note", "")
        if ciel not in Observation.Ciel.values or instrument not in Observation.Instrument.values:
            raise ValueError("choix")
        if not isinstance(note, str) or len(note) > NOTE_MAXI:
            raise ValueError("note")
    except (ValueError, TypeError):
        return JsonResponse({"erreur": "Observation invalide (astre, date, ciel, instrument ou note)."}, status=400)

    lieu = lieu_courant(request)
    o = Observation.objects.create(
        quand=quand, objet=objet, ra=ra, dec=dec, nom=nom.strip(), ciel=ciel, instrument=instrument,
        note=note.strip(), latitude=lieu["latitude"], longitude=lieu["longitude"],
    )
    return JsonResponse({"observation": observation_json(o)}, status=201, json_dumps_params={"ensure_ascii": False})


@require_POST
@pilotage.pilotage_requis
def effacer(request, observation_id):
    """POST /api/ciel/journal/<id>/effacer/ : efface une observation (code requis)."""
    supprimees, _ = Observation.objects.filter(pk=observation_id).delete()
    if not supprimees:
        return JsonResponse({"erreur": "Observation introuvable."}, status=404)
    return JsonResponse({"efface": observation_id})


def _cellule(valeur):
    """Contre l'injection de formules dans un tableur : un texte qui commence par = + - @
    (ou une tabulation) est précédé d'une apostrophe."""
    texte = "" if valeur is None else str(valeur)
    return "'" + texte if texte[:1] in ("=", "+", "-", "@", "\t", "\r") else texte


@require_GET
def exporter(request):
    """GET /api/ciel/journal/export.csv : toutes les observations, pour un tableur (séparateur ;)."""
    sortie = io.StringIO()
    sortie.write("﻿")  # BOM : Excel reconnaît l'UTF-8 (accents)
    ecrivain = csv.writer(sortie, delimiter=";")
    ecrivain.writerow(["date (UTC)", "astre", "ascension droite", "déclinaison", "latitude", "longitude",
                       "ciel", "instrument", "note"])
    for o in Observation.objects.order_by("quand"):
        ecrivain.writerow([
            _iso(o.quand), _cellule(o.nom), o.ra if o.ra is not None else "", o.dec if o.dec is not None else "",
            round(o.latitude, 4), round(o.longitude, 4), o.get_ciel_display(), o.get_instrument_display(),
            _cellule(o.note),
        ])
    reponse = HttpResponse(sortie.getvalue(), content_type="text/csv; charset=utf-8")
    reponse["Content-Disposition"] = 'attachment; filename="journal-index-stellaire.csv"'
    return reponse
