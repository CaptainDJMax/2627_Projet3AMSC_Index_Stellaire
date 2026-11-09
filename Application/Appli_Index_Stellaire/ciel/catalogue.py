"""Catalogue automatique : plus de 1 000 astres en plus des fiches écrites à la main (contenu/).

Deux étages :
1. La BASE, livrée avec l'appli (ciel/donnees/catalogue_base.json, aucun réseau nécessaire) :
   919 étoiles jusqu'à la magnitude 4,5 (base HYG), les 110 objets de Messier (OpenNGC),
   Uranus et Neptune. Noms, positions, magnitudes, taille et forme du ciel profond.
2. L'ENRICHISSEMENT, téléchargé une fois par mois quand il y a internet : le résumé de l'article
   Wikipédia en français (texte sous licence CC BY-SA 4.0, crédit affiché dans la fiche) et, pour
   le ciel profond, les planètes et les étoiles les plus brillantes, une image de Wikimedia Commons
   dont la licence est vérifiée (domaine public, CC0, CC BY ou CC BY-SA ; jamais NC ni ND).
   Il est gardé dans donnees_catalogue/ (hors de Git) : tout reste disponible hors ligne.

Règles :
- Les fiches écrites à la main (origine « contenu ») ont toujours la priorité : un astre du catalogue
  qui les double (même identifiant, même nom, ou à moins de 0,1° pour un point du ciel) est ignoré.
- Rien n'est jamais supprimé de la base (l'historique des pointages y fait référence).
- Les tests n'appellent jamais internet : _get_json et _get_octets sont remplacés.
"""

import html
import json
import logging
import math
import re
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from django.conf import settings
from django.db import transaction

logger = logging.getLogger(__name__)

FICHIER_BASE = Path(__file__).resolve().parent / "donnees" / "catalogue_base.json"
PERIODE = timedelta(days=30)
MAGNITUDE_IMAGES_ETOILES = 2.5  # au-delà, les images d'étoiles sont surtout des cartes : on s'en passe
PAUSE_S = 0.2  # entre deux requêtes : on reste poli avec les serveurs de Wikimedia
ECHECS_RESEAU_MAXI = 10  # erreurs réseau d'affilée avant d'abandonner (connexion perdue)
DOSSIER_IMAGES = "objets_celestes/catalogue"  # dans media/
USER_AGENT = ("IndexStellaire/1.0 (projet etudiant ENSEA ; "
              "https://github.com/CaptainDJMax/2627_Projet3AMSC_Index_Stellaire)")
CREDIT_WIKIPEDIA = "Texte : Wikipédia en français, CC BY-SA 4.0"

# Un résumé n'est gardé que s'il parle bien de ce genre d'astre (« Castor » est aussi un animal)
MOTS_CLES = {
    "etoile": ("étoile", "système stellaire", "binaire", "géante", "naine", "supergéante", "système triple"),
    "amas": ("amas", "astérisme", "étoiles", "nuage", "étoile double"),
    "ciel_profond": ("galaxie", "nébuleuse", "rémanent", "amas"),
    "planete": ("planète",),
}
LICENCE_OK = re.compile(r"^(cc0|cc[ -]?by(-sa)?([ -]?\d(\.\d)?)?$|cc[ -]?by(-sa)?[ -]\d|public domain|domaine public|pd\b|pd-)", re.I)
LICENCE_INTERDITE = re.compile(r"\b(nc|nd)\b|non[- ]?commercial|no[- ]?deriv|fair use|copyright", re.I)


class PasDeReseau(Exception):
    pass


# --- Fichiers ------------------------------------------------------------------------------------

def dossier():
    d = Path(settings.BASE_DIR) / "donnees_catalogue"
    d.mkdir(exist_ok=True)
    return d


def _lire(nom, defaut):
    try:
        return json.loads((dossier() / nom).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return defaut


def _ecrire(nom, donnees):
    chemin = dossier() / nom
    temporaire = chemin.with_suffix(".tmp")
    temporaire.write_text(json.dumps(donnees, ensure_ascii=False, indent=1), encoding="utf-8")
    temporaire.replace(chemin)  # jamais de fichier à moitié écrit si le PC s'éteint


def charger_base():
    return json.loads(FICHIER_BASE.read_text(encoding="utf-8"))["astres"]


def lire_etat():
    return _lire("etat.json", {})


def mise_a_jour_due(maintenant=None):
    """Vrai si la dernière mise à jour réussie par internet date de plus de 30 jours (ou jamais)."""
    maintenant = maintenant or datetime.now(timezone.utc)
    derniere = lire_etat().get("derniere_mise_a_jour")
    if not derniere:
        return True
    try:
        return maintenant - datetime.fromisoformat(derniere) > PERIODE
    except ValueError:
        return True


# --- Réseau (remplacé dans les tests) ----------------------------------------------------------------

def _get_json(url):
    requete = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(requete, timeout=20) as reponse:
        return json.loads(reponse.read(5_000_000).decode("utf-8"))


def _get_octets(url):
    requete = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(requete, timeout=60) as reponse:
        contenu = reponse.read(30_000_001)
    if len(contenu) > 30_000_000:
        raise ValueError("image trop lourde")
    return contenu


# --- Wikipédia et Wikimedia Commons ----------------------------------------------------------------

def resume_wikipedia(titre, categorie):
    """Résumé de l'article fr.wikipedia.org « titre » s'il existe et parle du bon genre d'astre.
    {titre, page, extrait, image (adresse ou None)} ou None. Lève les erreurs réseau (sauf 404)."""
    url = "https://fr.wikipedia.org/api/rest_v1/page/summary/" + urllib.parse.quote(titre.replace(" ", "_"), safe="")
    try:
        d = _get_json(url)
    except urllib.error.HTTPError as erreur:
        if erreur.code == 404:
            return None
        raise
    if not isinstance(d, dict) or d.get("type") != "standard":
        return None  # page d'homonymie, page absente...
    extrait = (d.get("extract") or "").strip()
    verification = (str(d.get("description") or "") + " " + extrait).lower()
    if not extrait or not any(m in verification for m in MOTS_CLES.get(categorie, ())):
        return None
    image = (d.get("originalimage") or d.get("thumbnail") or {}).get("source")
    page = ((d.get("content_urls") or {}).get("desktop") or {}).get("page") or (
        "https://fr.wikipedia.org/wiki/" + urllib.parse.quote(d.get("title", titre).replace(" ", "_")))
    return {"titre": d.get("title", titre), "page": page, "extrait": extrait[:3000], "image": image}


def fichier_commons(url_image):
    """Nom du fichier sur Wikimedia Commons à partir de l'adresse de l'image, ou None si l'image
    n'est pas sur Commons (image propre à Wikipédia en français : souvent non libre)."""
    if not url_image or "/wikipedia/commons/" not in url_image:
        return None
    morceaux = url_image.split("/wikipedia/commons/", 1)[1].split("/")
    if morceaux[0] == "thumb" and len(morceaux) >= 4:
        nom = morceaux[3]
    elif len(morceaux) >= 3:
        nom = morceaux[2]
    else:
        return None
    return urllib.parse.unquote(nom)


def licence_acceptee(licence):
    licence = (licence or "").strip()
    return bool(licence) and bool(LICENCE_OK.match(licence)) and not LICENCE_INTERDITE.search(licence)


def _texte_brut(valeur):
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", valeur or "")).split())


def infos_image(nom_fichier):
    """Adresse (réduite à 800 px), page, auteur et licence d'un fichier de Commons ; None si la
    licence n'est pas libre ou si les informations manquent."""
    url = ("https://commons.wikimedia.org/w/api.php?action=query&format=json&formatversion=2"
           "&prop=imageinfo&iiprop=url%7Cextmetadata&iiurlwidth=800&titles="
           + urllib.parse.quote("File:" + nom_fichier))
    d = _get_json(url)
    try:
        info = d["query"]["pages"][0]["imageinfo"][0]
    except (KeyError, IndexError, TypeError):
        return None
    meta = info.get("extmetadata") or {}
    licence = _texte_brut((meta.get("LicenseShortName") or {}).get("value"))
    if not licence_acceptee(licence):
        return None
    auteur = _texte_brut((meta.get("Artist") or {}).get("value")) or _texte_brut((meta.get("Credit") or {}).get("value"))
    return {
        "url": info.get("thumburl") or info.get("url"),
        "page": info.get("descriptionurl") or "https://commons.wikimedia.org/wiki/File:" + urllib.parse.quote(nom_fichier),
        "auteur": (auteur or "auteur non indiqué (voir la page de l'image)")[:200],
        "licence": licence[:100],
    }


def nom_de_fichier(cle):
    return re.sub(r"[^a-z0-9]+", "_", cle.lower()).strip("_") + ".jpg"


def enrichir(astres, limite=None, refaire=False, journal=None):
    """Télécharge résumés et images. Reprend là où une mise à jour interrompue s'était arrêtée
    (une entrée de moins de 30 jours n'est pas redemandée, sauf avec refaire). Lève PasDeReseau
    si internet ne répond pas du tout."""
    from ciel.management.commands.telecharger_images import reduire

    ecrire = journal or (lambda texte: None)
    cache = _lire("enrichissement.json", {})
    maintenant = datetime.now(timezone.utc)
    dossier_images = Path(settings.MEDIA_ROOT) / DOSSIER_IMAGES
    dossier_images.mkdir(parents=True, exist_ok=True)
    stats = {"textes": 0, "images": 0, "sans_article": 0, "deja_a_jour": 0}
    echecs_de_suite = 0
    a_traiter = astres if limite is None else astres[:limite]
    for i, a in enumerate(a_traiter):
        ancien = cache.get(a["cle"])
        if ancien and not refaire:
            try:
                if maintenant - datetime.fromisoformat(ancien["date"]) < PERIODE:
                    stats["deja_a_jour"] += 1
                    continue
            except (KeyError, ValueError):
                pass
        try:
            resume = None
            for titre in a.get("wikipedia", []):
                resume = resume_wikipedia(titre, a["categorie"])
                time.sleep(PAUSE_S)
                if resume:
                    break
            entree = {"date": maintenant.isoformat()}
            if resume:
                entree.update(titre=resume["titre"], page=resume["page"], extrait=resume["extrait"])
                stats["textes"] += 1
                veut_image = a["categorie"] != "etoile" or (a.get("magnitude") or 99) <= MAGNITUDE_IMAGES_ETOILES
                nom = fichier_commons(resume["image"]) if veut_image else None
                if nom:
                    info = infos_image(nom)
                    time.sleep(PAUSE_S)
                    if info:
                        fichier = nom_de_fichier(a["cle"])
                        (dossier_images / fichier).write_bytes(reduire(_get_octets(info["url"])))
                        entree["image"] = {"fichier": fichier, "source": info["page"],
                                           "auteur": info["auteur"], "licence": info["licence"]}
                        stats["images"] += 1
            else:
                stats["sans_article"] += 1
            if ancien and ancien.get("image") and "image" not in entree and resume is None:
                entree["image"] = ancien["image"]  # rien de neuf : on garde l'ancienne image
            cache[a["cle"]] = entree
            echecs_de_suite = 0
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as erreur:
            echecs_de_suite += 1
            logger.warning("Catalogue : %s non mis à jour (%s)", a["cle"], erreur)
            if echecs_de_suite >= ECHECS_RESEAU_MAXI:
                _ecrire("enrichissement.json", cache)
                if stats["textes"] == 0 and stats["sans_article"] == 0:
                    raise PasDeReseau(str(erreur))
                ecrire("Connexion perdue : mise à jour arrêtée, elle reprendra la prochaine fois.")
                stats["interrompu"] = True
                return stats
        if (i + 1) % 50 == 0:
            _ecrire("enrichissement.json", cache)
            ecrire(f"  {i + 1} / {len(a_traiter)} astres...")
    _ecrire("enrichissement.json", cache)
    return stats


# --- Import dans la base -----------------------------------------------------------------------------

def _normaliser(nom):
    nom = unicodedata.normalize("NFKD", nom).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", nom).strip()


def _radec(identifiant):
    if identifiant.startswith("radec:"):
        try:
            ra, dec = (float(x) for x in identifiant[6:].split(","))
            return ra, dec
        except ValueError:
            return None
    return None


def _ecart_deg(a, b):
    r = math.radians
    c = (math.sin(r(a[1])) * math.sin(r(b[1])) + math.cos(r(a[1])) * math.cos(r(b[1])) * math.cos(r(a[0] - b[0])))
    return math.degrees(math.acos(max(-1.0, min(1.0, c))))


def _description(a):
    """Texte de secours, sans internet : le genre d'astre et sa magnitude."""
    morceaux = []
    if a["categorie"] == "etoile":
        morceaux.append("Étoile" + (f" de type spectral {a['type']}" if a.get("type") else ""))
    elif a["categorie"] == "planete":
        morceaux.append(a.get("type", "Planète").capitalize())
    else:
        morceaux.append((a.get("type") or "Objet du ciel profond").capitalize())
    if a.get("magnitude") is not None:
        morceaux.append(f"magnitude {str(a['magnitude']).replace('.', ',')}")
    texte = ", ".join(morceaux) + "."  # la désignation est déjà sous le nom, dans la fiche
    return texte + " Le résumé de Wikipédia arrivera à la prochaine mise à jour avec internet."


def importer(base=None, enrichissement=None):
    """Crée ou met à jour les astres du catalogue dans la base. {crees, mis_a_jour, ignores}."""
    from .models import ObjetCeleste

    base = base if base is not None else charger_base()
    enrichissement = enrichissement if enrichissement is not None else _lire("enrichissement.json", {})
    contenu = list(ObjetCeleste.objects.filter(origine=ObjetCeleste.Origine.CONTENU))
    idents_contenu = {o.identifiant_skyfield for o in contenu if o.identifiant_skyfield}
    noms_contenu = {_normaliser(o.nom) for o in contenu}
    points_contenu = [p for p in (_radec(o.identifiant_skyfield) for o in contenu) if p]
    existants = {o.cle_catalogue: o for o in ObjetCeleste.objects.filter(origine=ObjetCeleste.Origine.CATALOGUE)}
    stats = {"crees": 0, "mis_a_jour": 0, "ignores": 0}
    dossier_media = Path(settings.MEDIA_ROOT)
    with transaction.atomic():
        for a in base:
            point = _radec(a["identifiant"])
            nom_court = a["nom"].split(" · ", 1)[-1]
            if (a["identifiant"] in idents_contenu or _normaliser(a["nom"]) in noms_contenu
                    or _normaliser(nom_court) in noms_contenu
                    or (point and any(_ecart_deg(point, p) < 0.1 for p in points_contenu))):
                stats["ignores"] += 1  # déjà une fiche écrite à la main : elle a la priorité
                ancien = existants.get(a["cle"])
                if ancien is not None and ancien.identifiant_skyfield:
                    # Importé avant que la fiche existe : on le retire de la carte et de la recherche
                    # sans l'effacer (l'historique des pointages peut y faire référence)
                    ancien.identifiant_skyfield = ""
                    ancien.save(update_fields=["identifiant_skyfield"])
                continue
            e = enrichissement.get(a["cle"]) or {}
            o = existants.get(a["cle"])
            cree = o is None
            if cree:
                o = ObjetCeleste(origine=ObjetCeleste.Origine.CATALOGUE, cle_catalogue=a["cle"])
            credits = []
            if e.get("extrait"):
                credits.append(CREDIT_WIKIPEDIA)
            if a.get("credit_donnees"):
                credits.append("Données : " + a["credit_donnees"])
            valeurs = {
                "nom": a["nom"], "categorie": a["categorie"], "identifiant_skyfield": a["identifiant"],
                "designation": a.get("designation", ""), "magnitude": a.get("magnitude"), "forme": a.get("forme"),
                "description": e.get("extrait") or _description(a),
                "description_credit": " · ".join(credits),
                "sources": e.get("page", ""),
            }
            image = e.get("image")
            if image and (dossier_media / DOSSIER_IMAGES / image["fichier"]).is_file():
                valeurs.update(image=f"{DOSSIER_IMAGES}/{image['fichier']}", image_source=image["source"],
                               image_auteur=image["auteur"], image_licence=image["licence"])
            else:
                valeurs.update(image=None, image_source="", image_auteur="", image_licence="")
            change = cree or any(
                (getattr(o, k).name or None if k == "image" else getattr(o, k)) != v for k, v in valeurs.items()
            )
            if not change:
                continue
            for k, v in valeurs.items():
                setattr(o, k, v)
            o.save()
            stats["crees" if cree else "mis_a_jour"] += 1
    return stats


# --- Tout ensemble -----------------------------------------------------------------------------------

def mettre_a_jour(hors_ligne=False, limite=None, refaire=False, journal=None):
    """Mise à jour complète : enrichissement par internet (sauf hors_ligne), puis import.
    Sans réseau, importe quand même la base et ce qui avait déjà été téléchargé."""
    ecrire = journal or (lambda texte: None)
    base = charger_base()
    etat = lire_etat()
    resultat = {"astres": len(base), "reseau": False}
    if not hors_ligne:
        try:
            resultat.update(enrichir(base, limite=limite, refaire=refaire, journal=ecrire))
            resultat["reseau"] = True
            if not resultat.get("interrompu") and limite is None:
                etat["derniere_mise_a_jour"] = datetime.now(timezone.utc).isoformat()
        except PasDeReseau as erreur:
            ecrire(f"Pas d'internet ({erreur}) : on garde la dernière version téléchargée.")
            etat["dernier_echec"] = datetime.now(timezone.utc).isoformat()
    resultat.update(importer(base))
    etat["dernier_import"] = datetime.now(timezone.utc).isoformat()
    etat["astres_importes"] = len(base)
    _ecrire("etat.json", etat)
    return resultat


_tache = None


def lancer_si_besoin(journal=None):
    """Au démarrage du serveur (python manage.py servir) : importe la base tout de suite si elle ne
    l'a jamais été, puis lance la mise à jour par internet en arrière-plan si elle a plus de 30 jours.
    Sans internet, rien ne casse : on réessaiera au prochain démarrage."""
    global _tache
    ecrire = journal or (lambda texte: None)
    if lire_etat().get("astres_importes") != len(charger_base()):
        ecrire("Catalogue : premier import (sans internet)...")
        mettre_a_jour(hors_ligne=True)
    if not mise_a_jour_due() or (_tache is not None and _tache.is_alive()):
        return None

    def travail():
        try:
            r = mettre_a_jour(journal=lambda t: logger.info("Catalogue : %s", t))
            logger.warning("Catalogue mis à jour : %s", r)  # WARNING : visible dans logs/ en production
        except Exception:  # noqa: BLE001 — une erreur ne doit jamais arrêter le serveur
            logger.exception("Mise à jour du catalogue impossible")

    ecrire("Catalogue : mise à jour mensuelle lancée en arrière-plan (Wikipédia, Commons)...")
    _tache = threading.Thread(target=travail, name="catalogue", daemon=True)
    _tache.start()
    return _tache
