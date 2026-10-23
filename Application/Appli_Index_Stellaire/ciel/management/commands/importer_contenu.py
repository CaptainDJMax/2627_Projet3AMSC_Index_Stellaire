"""Importe les astres depuis le dossier contenu/ : un fichier JSON par astre.

    python manage.py importer_contenu
    python manage.py importer_contenu --dossier chemin/vers/contenu

Le dossier contenu/ est partagé par Git ; la base (db.sqlite3) ne l'est pas. Chacun reconstruit
sa base avec cette commande après un « git pull ».

- Un astre est reconnu par son NOM : il est créé s'il n'existe pas, mis à jour sinon.
- Le fichier fait foi : un champ vide dans le fichier vide le champ dans la base.
- L'image est copiée de contenu/images/ vers media/objets_celestes/.
- Rien n'est jamais supprimé de la base.
- Tous les fichiers sont vérifiés AVANT d'importer quoi que ce soit : une seule erreur, et rien
  n'est importé (la liste des erreurs est affichée).
"""

import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from ciel import astro
from ciel.models import Constellation, ObjetCeleste

CHAMPS_TEXTE = ("identifiant_skyfield", "description", "image", "image_source", "image_auteur", "image_licence")
CHAMPS_LISTE = ("sources", "constellations")
CHAMPS_CONNUS = {"nom", "categorie", *CHAMPS_TEXTE, *CHAMPS_LISTE}
DOSSIER_MEDIA = "objets_celestes"  # même dossier que le champ ImageField (upload_to)


def dossier_par_defaut():
    return Path(settings.BASE_DIR) / "contenu"


class Command(BaseCommand):
    help = "Importe les astres du dossier contenu/ (un fichier JSON par astre) dans la base."

    def add_arguments(self, parser):
        parser.add_argument("--dossier", default=str(dossier_par_defaut()), help="dossier contenu/ à lire")

    def handle(self, *args, **options):
        dossier = Path(options["dossier"])
        fichiers = sorted((dossier / "astres").glob("*.json"))
        if not fichiers:
            raise CommandError(f"Aucun fichier .json dans {dossier / 'astres'}")

        astres, erreurs = self._lire_et_verifier(fichiers, dossier)
        if erreurs:
            raise CommandError("Rien n'a été importé. À corriger :\n- " + "\n- ".join(erreurs))

        bilan = {"créé": 0, "mis à jour": 0, "inchangé": 0}
        with transaction.atomic():
            for chemin, donnees in astres:
                resultat = self._importer(donnees, dossier)
                bilan[resultat] += 1
                if resultat != "inchangé":
                    self.stdout.write(f"  {resultat} : {donnees['nom']} ({chemin.name})")

        self._avertir_positions(astres)
        self.stdout.write(self.style.SUCCESS(
            f"{len(astres)} astres lus : {bilan['créé']} créés, {bilan['mis à jour']} mis à jour, "
            f"{bilan['inchangé']} inchangés."
        ))

    # --- Vérification de tous les fichiers ----------------------------------------------

    def _lire_et_verifier(self, fichiers, dossier):
        categories = {valeur for valeur, _ in ObjetCeleste.Categorie.choices}
        astres, erreurs, noms = [], [], {}
        for chemin in fichiers:
            try:
                texte = chemin.read_text(encoding="utf-8")
                if "<<<<<<<" in texte or ">>>>>>>" in texte:
                    erreurs.append(
                        f"{chemin.name} : conflit Git non résolu (le même astre a été modifié des deux côtés). "
                        "Garder une des deux versions entre <<<<<<< et >>>>>>>, effacer ces lignes, puis commit."
                    )
                    continue
                donnees = json.loads(texte)
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as erreur:
                erreurs.append(f"{chemin.name} : fichier illisible ({erreur})")
                continue
            if not isinstance(donnees, dict):
                erreurs.append(f"{chemin.name} : le fichier doit contenir un objet {{ ... }}")
                continue
            probleme = self._verifier(donnees, dossier, categories)
            if probleme:
                erreurs.append(f"{chemin.name} : {probleme}")
                continue
            nom = donnees["nom"].strip()
            if nom in noms:
                erreurs.append(f"{chemin.name} : le nom « {nom} » est déjà utilisé par {noms[nom]}")
                continue
            noms[nom] = chemin.name
            astres.append((chemin, donnees))
        return astres, erreurs

    def _verifier(self, donnees, dossier, categories):
        inconnus = set(donnees) - CHAMPS_CONNUS
        if inconnus:
            return "champ(s) inconnu(s) : " + ", ".join(sorted(inconnus)) + " (faute de frappe ?)"
        if not isinstance(donnees.get("nom"), str) or not donnees["nom"].strip():
            return "le champ « nom » est obligatoire"
        if donnees.get("categorie") not in categories:
            return "« categorie » doit valoir : " + ", ".join(sorted(categories))
        for champ in CHAMPS_TEXTE:
            if not isinstance(donnees.get(champ, ""), str):
                return f"« {champ} » doit être un texte"
        for champ in CHAMPS_LISTE:
            valeur = donnees.get(champ, [])
            if not isinstance(valeur, list) or not all(isinstance(v, str) for v in valeur):
                return f"« {champ} » doit être une liste de textes, par exemple [\"...\"]"
        image = donnees.get("image", "")
        if image:
            if "/" in image or "\\" in image or image.startswith("."):
                return "« image » doit être un simple nom de fichier (par exemple venus.jpg)"
            if not (dossier / "images" / image).is_file():
                return f"image introuvable : images/{image}"
            manquants = [c for c in ("image_source", "image_auteur", "image_licence") if not donnees.get(c, "").strip()]
            if manquants:
                return "image sans crédit complet, il manque : " + ", ".join(manquants)
        source = donnees.get("image_source", "")
        if source and not source.startswith(("https://", "http://")):
            return "« image_source » doit être une adresse web (https://...)"
        return None

    # --- Import d'un astre ----------------------------------------------------------------

    def _importer(self, donnees, dossier):
        nom = donnees["nom"].strip()
        objet = ObjetCeleste.objects.filter(nom=nom).first()
        cree = objet is None
        if cree:
            objet = ObjetCeleste(nom=nom)
        avant = None if cree else self._etat(objet)

        objet.categorie = donnees["categorie"]
        objet.identifiant_skyfield = donnees.get("identifiant_skyfield", "").strip()
        objet.description = donnees.get("description", "").strip()
        objet.image_source = donnees.get("image_source", "").strip()
        objet.image_auteur = donnees.get("image_auteur", "").strip()
        objet.image_licence = donnees.get("image_licence", "").strip()
        objet.sources = "\n".join(s.strip() for s in donnees.get("sources", []) if s.strip())

        image_copiee = False
        image = donnees.get("image", "")
        if image:
            image_copiee = self._copier_image(dossier / "images" / image, image)
            objet.image.name = f"{DOSSIER_MEDIA}/{image}"
        else:
            objet.image = None
        objet.save()

        constellations = [Constellation.objects.get_or_create(nom=n.strip())[0]
                          for n in donnees.get("constellations", []) if n.strip()]
        objet.constellations.set(constellations)

        if cree:
            return "créé"
        return "mis à jour" if image_copiee or self._etat(objet) != avant else "inchangé"

    def _etat(self, objet):
        return (
            objet.categorie, objet.identifiant_skyfield, objet.description, objet.image.name or "",
            objet.image_source, objet.image_auteur, objet.image_licence, objet.sources,
            tuple(sorted(c.nom for c in objet.constellations.all())),
        )

    def _copier_image(self, source, nom):
        """Copie l'image dans media/objets_celestes/ si elle a changé. Renvoie True si copiée."""
        destination = Path(settings.MEDIA_ROOT) / DOSSIER_MEDIA / nom
        contenu = source.read_bytes()
        if destination.is_file() and destination.read_bytes() == contenu:
            return False
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(contenu)
        return True

    # --- Avertissements (n'empêchent pas l'import) -------------------------------------------

    def _avertir_positions(self, astres):
        """Signale les astres dont la position n'est pas calculable (ils n'apparaîtront pas sur la carte)."""
        lieu = settings.LIEU_PAR_DEFAUT
        instant = astro.maintenant()
        for _, donnees in astres:
            ident = donnees.get("identifiant_skyfield", "").strip()
            if not ident:
                self.stdout.write(self.style.WARNING(f"  {donnees['nom']} : pas d'identifiant de calcul, absent de la carte"))
                continue
            try:
                astro.altaz(ident, lieu["latitude"], lieu["longitude"], lieu["altitude_m"], instant)
            except (KeyError, ValueError):
                self.stdout.write(self.style.WARNING(
                    f"  {donnees['nom']} : identifiant « {ident} » non calculable pour l'instant, absent de la carte"
                ))
